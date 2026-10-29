PRAGMA foreign_keys = ON;

-- Recibo de todo evento que chega. A chave de dedup é o id do remetente (submission_id, wamid, erp_sale_id,
-- event_id do atendimento).
CREATE TABLE IF NOT EXISTS inbound_event (
  id           INTEGER PRIMARY KEY,
  source       TEXT NOT NULL CHECK (source IN ('form', 'whatsapp', 'erp', 'atendimento')),
  dedup_key    TEXT NOT NULL,
  payload_hash TEXT NOT NULL,
  payload      TEXT NOT NULL,
  status       TEXT NOT NULL DEFAULT 'processado' CHECK (status IN ('processado', 'quarentena')),
  duplicates   INTEGER NOT NULL DEFAULT 0,
  received_at  TEXT NOT NULL,
  UNIQUE (source, dedup_key)
);
-- Recibo imutável. Só o que está em quarentena (nada aplicado) pode trocar de payload no reenvio.
-- Exclusão LGPD seria a única outra exceção, documentada no README.
CREATE TRIGGER IF NOT EXISTS inbound_event_imutavel BEFORE UPDATE OF source, dedup_key, payload, payload_hash
ON inbound_event
WHEN NEW.source IS NOT OLD.source OR NEW.dedup_key IS NOT OLD.dedup_key
  OR (OLD.status <> 'quarentena' AND (NEW.payload IS NOT OLD.payload OR NEW.payload_hash IS NOT OLD.payload_hash))
BEGIN SELECT RAISE(ABORT, 'recibo imutavel'); END;

-- Nome só para exibição: nunca entra no matching de identidade.
CREATE TABLE IF NOT EXISTS person (
  id         INTEGER PRIMARY KEY,
  name       TEXT,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS person_identifier (
  kind      TEXT NOT NULL CHECK (kind IN ('phone', 'email', 'bsuid')),
  value     TEXT NOT NULL,  -- normalizado: E.164, e-mail minúsculo ou BSUID do WhatsApp (quem usa nome de usuário)
  person_id INTEGER NOT NULL REFERENCES person (id),
  event_id  INTEGER NOT NULL REFERENCES inbound_event (id),
  PRIMARY KEY (kind, value)
);

-- Sem colunas de primeiro/último toque: são derivados de touchpoint por consulta.
CREATE TABLE IF NOT EXISTS opportunity (
  id         INTEGER PRIMARY KEY,
  person_id  INTEGER NOT NULL REFERENCES person (id),
  product    TEXT NOT NULL DEFAULT 'a_definir',
  unit       TEXT NOT NULL DEFAULT 'desconhecida',
  status     TEXT NOT NULL DEFAULT 'aberta' CHECK (status IN ('aberta', 'ganha', 'perdida')),
  stage      TEXT CHECK (stage IN ('em_negociacao')),  -- etiqueta que o atendimento devolve
  is_test    INTEGER NOT NULL DEFAULT 0,  -- de QA: lead real do mesmo telefone nunca cai nela
  created_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS opportunity_aberta_unica
  ON opportunity (person_id, product, unit, is_test) WHERE status = 'aberta';

-- Leitura do /q/: o clique (UTMs e click id) e o protocolo que vai no texto do WhatsApp. Sem dado pessoal nem IP.
CREATE TABLE IF NOT EXISTS click_session (
  id            INTEGER PRIMARY KEY,
  entry_point   TEXT NOT NULL,
  protocol      TEXT NOT NULL UNIQUE,
  utm_source    TEXT,
  utm_medium    TEXT,
  utm_campaign  TEXT,
  utm_id        TEXT,
  utm_content   TEXT,
  click_id_type TEXT CHECK (click_id_type IN ('gclid', 'gbraid', 'wbraid', 'fbclid')),
  click_id      TEXT,
  created_at    TEXT NOT NULL
);

-- Um contato. Sem dado pessoal. occurred_at é a hora do evento (UTC), não a de recebimento.
CREATE TABLE IF NOT EXISTS touchpoint (
  id              INTEGER PRIMARY KEY,
  person_id       INTEGER NOT NULL REFERENCES person (id),
  opportunity_id  INTEGER NOT NULL REFERENCES opportunity (id),
  event_id        INTEGER NOT NULL REFERENCES inbound_event (id),
  occurred_at     TEXT NOT NULL,
  contact_channel TEXT NOT NULL CHECK (contact_channel IN ('form', 'whatsapp')),
  origin_type     TEXT NOT NULL CHECK (origin_type IN ('observada', 'declarada', 'inferida', 'desconhecida')),
  source_channel  TEXT CHECK (origin_type <> 'desconhecida' OR source_channel IS NULL),
  utm_source      TEXT,
  utm_medium      TEXT,
  utm_campaign    TEXT,
  utm_id          TEXT,
  utm_content     TEXT,
  click_id_type   TEXT CHECK (click_id_type IN ('gclid', 'gbraid', 'wbraid', 'fbclid', 'ctwa_clid')),
  click_id        TEXT,
  ad_id           TEXT,
  entry_point     TEXT,
  unit            TEXT,
  product         TEXT,
  declared        TEXT,
  click_session_id INTEGER REFERENCES click_session (id),  -- mensagem que trouxe protocolo do /q/
  is_test         INTEGER NOT NULL DEFAULT 0 CHECK (is_test IN (0, 1)),  -- lead de QA: fora do relatório e das conversões
  evidence_level  TEXT CHECK (evidence_level IN ('canal', 'campanha', 'anuncio'))
                       CHECK (origin_type = 'observada' OR evidence_level IS NULL)
);
-- 1º toque da oportunidade (e dela num ponto de entrada) sem varrer a tabela: o relatório segura o LOCK
CREATE INDEX IF NOT EXISTS touchpoint_primeiro ON touchpoint (opportunity_id, occurred_at, id);
CREATE INDEX IF NOT EXISTS touchpoint_por_ponto ON touchpoint (opportunity_id, entry_point, occurred_at, id);
CREATE TRIGGER IF NOT EXISTS touchpoint_sem_update BEFORE UPDATE ON touchpoint
BEGIN SELECT RAISE(ABORT, 'touchpoint e append-only'); END;
CREATE TRIGGER IF NOT EXISTS touchpoint_sem_delete BEFORE DELETE ON touchpoint
BEGIN SELECT RAISE(ABORT, 'touchpoint e append-only'); END;

-- Histórico de consentimento por finalidade, append-only: o vigente é o mais recente. at é a hora do evento.
-- marketing = mensagens; ads = envio de dados às plataformas de anúncio.
CREATE TABLE IF NOT EXISTS consent (
  id        INTEGER PRIMARY KEY,
  person_id INTEGER NOT NULL REFERENCES person (id),
  purpose   TEXT NOT NULL CHECK (purpose IN ('marketing', 'ads')),
  granted   INTEGER NOT NULL CHECK (granted IN (0, 1)),
  event_id  INTEGER NOT NULL REFERENCES inbound_event (id),
  at        TEXT NOT NULL
);
CREATE TRIGGER IF NOT EXISTS consent_sem_update BEFORE UPDATE ON consent
BEGIN SELECT RAISE(ABORT, 'consent e append-only'); END;
CREATE TRIGGER IF NOT EXISTS consent_sem_delete BEFORE DELETE ON consent
BEGIN SELECT RAISE(ABORT, 'consent e append-only'); END;

-- Outbox do encaminhamento para o atendimento: gravado na mesma transação da oportunidade.
CREATE TABLE IF NOT EXISTS handoff (
  id             INTEGER PRIMARY KEY,
  opportunity_id INTEGER NOT NULL REFERENCES opportunity (id),
  queue          TEXT NOT NULL,
  status         TEXT NOT NULL DEFAULT 'pendente' CHECK (status IN ('pendente', 'enviando', 'enviado', 'incerto')),
  created_at     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS erp_sale (
  erp_sale_id    TEXT PRIMARY KEY,
  opportunity_id INTEGER NOT NULL REFERENCES opportunity (id),
  amount_cents   INTEGER NOT NULL,
  confirmed_at   TEXT NOT NULL,
  event_id       INTEGER NOT NULL REFERENCES inbound_event (id)
);

-- Outbox de conversões: a venda volta para a plataforma do clique (Google ou Meta). A demo não envia nada.
CREATE TABLE IF NOT EXISTS platform_conversion (
  id            INTEGER PRIMARY KEY,
  erp_sale_id   TEXT NOT NULL REFERENCES erp_sale (erp_sale_id),
  platform      TEXT NOT NULL CHECK (platform IN ('google', 'meta')),
  click_id_type TEXT,
  click_id      TEXT,
  event_id      TEXT NOT NULL,  -- = erp_sale_id: é por ele que a plataforma deduplica a conversão
  status        TEXT NOT NULL CHECK (status IN ('pendente', 'bloqueado_sensivel',
                                              'bloqueado_consentimento', 'expirado')),
  created_at    TEXT NOT NULL
);

-- Pendência de qualidade do rastreamento. detail é JSON sem dado pessoal.
CREATE TABLE IF NOT EXISTS tracking_issue (
  id          INTEGER PRIMARY KEY,
  kind        TEXT NOT NULL CHECK (kind IN ('parametros_perdidos', 'retorno_sem_parametro', 'utm_fora_do_padrao', 'ep_desconhecido',
                                            'anuncio_desconhecido', 'evento_conflitante', 'identidade_conflitante',
                                            'venda_sem_oportunidade', 'venda_divergente', 'venda_em_oportunidade_ganha',
                                            'payload_invalido', 'protocolo_invalido', 'etiqueta_sem_oportunidade',
                                            'etiqueta_ambigua')),
  entry_point TEXT,
  event_id    INTEGER REFERENCES inbound_event (id),
  detail      TEXT NOT NULL DEFAULT '{}',
  status      TEXT NOT NULL DEFAULT 'aberta' CHECK (status IN ('aberta', 'resolvida')),
  created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS tracking_issue_evento ON tracking_issue (event_id, status);

CREATE TABLE IF NOT EXISTS audit_log (
  id        INTEGER PRIMARY KEY,
  at        TEXT NOT NULL,
  actor     TEXT NOT NULL,
  action    TEXT NOT NULL,
  entity    TEXT NOT NULL,
  entity_id INTEGER NOT NULL,
  event_id  INTEGER REFERENCES inbound_event (id)
);
CREATE TRIGGER IF NOT EXISTS audit_log_sem_update BEFORE UPDATE ON audit_log
BEGIN SELECT RAISE(ABORT, 'audit_log e append-only'); END;
CREATE TRIGGER IF NOT EXISTS audit_log_sem_delete BEFORE DELETE ON audit_log
BEGIN SELECT RAISE(ABORT, 'audit_log e append-only'); END;
