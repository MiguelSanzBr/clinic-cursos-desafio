PRAGMA foreign_keys = ON;

-- Recibo de todo evento que chega. A chave de dedup é o id do remetente (submission_id, wamid, erp_sale_id).
CREATE TABLE IF NOT EXISTS inbound_event (
  id           INTEGER PRIMARY KEY,
  source       TEXT NOT NULL CHECK (source IN ('form', 'whatsapp', 'erp')),
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
  kind      TEXT NOT NULL CHECK (kind IN ('phone', 'email')),
  value     TEXT NOT NULL,  -- normalizado: E.164 ou e-mail minúsculo
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
  created_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS opportunity_aberta_unica
  ON opportunity (person_id, product, unit) WHERE status = 'aberta';

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
  declared        TEXT
);
CREATE TRIGGER IF NOT EXISTS touchpoint_sem_update BEFORE UPDATE ON touchpoint
BEGIN SELECT RAISE(ABORT, 'touchpoint e append-only'); END;
CREATE TRIGGER IF NOT EXISTS touchpoint_sem_delete BEFORE DELETE ON touchpoint
BEGIN SELECT RAISE(ABORT, 'touchpoint e append-only'); END;

-- Histórico de consentimento, append-only: o vigente é o mais recente. at é a hora do evento.
CREATE TABLE IF NOT EXISTS consent (
  id        INTEGER PRIMARY KEY,
  person_id INTEGER NOT NULL REFERENCES person (id),
  purpose   TEXT NOT NULL CHECK (purpose IN ('marketing')),
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
  status         TEXT NOT NULL DEFAULT 'pendente' CHECK (status IN ('pendente', 'enviado', 'incerto')),
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
  status        TEXT NOT NULL CHECK (status IN ('pendente', 'bloqueado_sensivel')),
  created_at    TEXT NOT NULL
);

-- Pendência de qualidade do rastreamento. detail é JSON sem dado pessoal.
CREATE TABLE IF NOT EXISTS tracking_issue (
  id          INTEGER PRIMARY KEY,
  kind        TEXT NOT NULL CHECK (kind IN ('parametros_perdidos', 'utm_fora_do_padrao', 'ep_desconhecido',
                                            'anuncio_desconhecido', 'evento_conflitante', 'identidade_conflitante',
                                            'venda_sem_oportunidade', 'venda_divergente')),
  entry_point TEXT,
  event_id    INTEGER REFERENCES inbound_event (id),
  detail      TEXT NOT NULL DEFAULT '{}',
  status      TEXT NOT NULL DEFAULT 'aberta' CHECK (status IN ('aberta', 'resolvida')),
  created_at  TEXT NOT NULL
);

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
