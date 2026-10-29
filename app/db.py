"""Todo o SQL da demo. Cada evento recebido grava recibo e efeitos numa transação só."""
import json
import sqlite3
import threading
from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path

from app import domain

SCHEMA = Path(__file__).with_name("schema.sql").read_text()
TOUCH_FIELDS = ("contact_channel", "utm_source", "utm_medium", "utm_campaign", "utm_id", "utm_content",
                "click_id_type", "click_id", "ad_id", "entry_point", "unit", "product", "declared", "click_session_id")
# shortcut: serializa escrita e leitura; com Postgres, transação e conexão por requisição. Reentrante: a rota do
# WhatsApp lê o protocolo e grava o toque sob a mesma trava
LOCK = threading.RLock()
TEST_OPPS = "SELECT id FROM opportunity WHERE is_test"


def connect(path):
    # uma conexão compartilhada entre threads (check_same_thread=False): todo uso passa pelo LOCK
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def now():
    return datetime.now(UTC).isoformat(timespec="seconds")


def audit(conn, actor, action, entity, entity_id, event_id):
    conn.execute("INSERT INTO audit_log (at, actor, action, entity, entity_id, event_id) VALUES (?, ?, ?, ?, ?, ?)",
                 (now(), actor, action, entity, entity_id, event_id))


def open_issue(conn, kind, entry_point, event_id, detail, actor):
    issue_id = conn.execute(
        "INSERT INTO tracking_issue (kind, entry_point, event_id, detail, created_at) VALUES (?, ?, ?, ?, ?) RETURNING id",
        (kind, entry_point, event_id, json.dumps(detail), now())).fetchone()["id"]
    audit(conn, actor, "issue.aberta", "tracking_issue", issue_id, event_id)


def quarantine(conn, event_id, issues, actor):
    """Estaciona o evento sem aplicar nada. Pendência já aberta do mesmo tipo não se repete no reenvio, e a de um
    motivo que o reenvio não tem mais (órfã que voltou divergente) é resolvida."""
    conn.execute("UPDATE inbound_event SET status = 'quarentena' WHERE id = ?", (event_id,))
    conn.execute("UPDATE tracking_issue SET status = 'resolvida' WHERE event_id = ? AND status = 'aberta'"
                 " AND kind NOT IN (SELECT value FROM json_each(?))", (event_id, json.dumps([k for k, _, _ in issues])))
    for kind, entry_point, detail in issues:
        if not conn.execute("SELECT 1 FROM tracking_issue WHERE event_id = ? AND kind = ? AND status = 'aberta'",
                            (event_id, kind)).fetchone():
            open_issue(conn, kind, entry_point, event_id, detail, actor)
    return {"status": "quarentena", "event_id": event_id, "motivo": issues[0][0]}


def release(conn, event_id, action, actor):
    """Reenvio de evento em quarentena que agora passa: fecha as pendências dele e volta a 'processado'."""
    conn.execute("UPDATE inbound_event SET status = 'processado' WHERE id = ?", (event_id,))
    conn.execute("UPDATE tracking_issue SET status = 'resolvida' WHERE event_id = ? AND status = 'aberta'", (event_id,))
    audit(conn, actor, action, "inbound_event", event_id, event_id)


def receive(conn, source, dedup_key, payload, actor, stored=None):
    """Grava o recibo. Devolve (event_id, None) se é novo, ou (event_id, 'reprocessar' | 'duplicado' | 'conflito')."""
    # o hash é sempre do payload original (dedup); o que se grava pode ser uma versão reduzida (stored)
    digest, raw = domain.payload_hash(payload), json.dumps(payload if stored is None else stored, ensure_ascii=False)
    row = conn.execute(
        "INSERT INTO inbound_event (source, dedup_key, payload_hash, payload, received_at) VALUES (?, ?, ?, ?, ?)"
        " ON CONFLICT (source, dedup_key) DO NOTHING RETURNING id",
        (source, dedup_key, digest, raw, now())).fetchone()
    if row:
        return row["id"], None
    first = conn.execute("UPDATE inbound_event SET duplicates = duplicates + 1 WHERE source = ? AND dedup_key = ?"
                         " RETURNING id, payload_hash, status", (source, dedup_key)).fetchone()
    if first["status"] == "quarentena":
        # nada foi aplicado: o reenvio troca o payload e é processado de novo (único caso em que o recibo muda)
        conn.execute("UPDATE inbound_event SET payload = ?, payload_hash = ? WHERE id = ?", (raw, digest, first["id"]))
        return first["id"], "reprocessar"
    if first["payload_hash"] == digest:
        return first["id"], "duplicado"
    # mesma chave com conteúdo diferente: não sobrescreve o recibo original, registra para alguém olhar
    # o hash do conteúdo novo diz o que divergiu sem copiar dado pessoal para a pendência
    open_issue(conn, "evento_conflitante", None, first["id"],
               {"source": source, "dedup_key": dedup_key, "payload_hash_novo": digest}, actor)
    return first["id"], "conflito"


def resolve_person(conn, identifiers, name, event_id, actor, test=False):
    """Acha a pessoa só por identificador normalizado. Nome nunca entra no matching."""
    found = {}
    for kind, value in identifiers:
        row = conn.execute("SELECT person_id FROM person_identifier WHERE kind = ? AND value = ?", (kind, value)).fetchone()
        if row:
            found[kind] = row["person_id"]
    person_id = found.get("phone") or found.get("bsuid") or found.get("email")
    if found.keys() == {"email"} and "phone" in dict(identifiers) and conn.execute(
            "SELECT 1 FROM person_identifier WHERE person_id = ? AND kind = 'phone'", (person_id,)).fetchone():
        person_id = None  # e-mail compartilhado (ex.: família): a dona dele tem outro telefone, este é outra pessoa
    if not person_id:
        person_id = conn.execute("INSERT INTO person (name, created_at) VALUES (?, ?) RETURNING id",
                                 (name, now())).fetchone()["id"]
        audit(conn, actor, "person.criada", "person", person_id, event_id)
    if len(people := set(found.values()) | {person_id}) > 1:
        # identificadores de pessoas diferentes: não funde sozinho, fica para revisão humana
        open_issue(conn, "identidade_conflitante", None, event_id, {"person_ids": sorted(people)}, actor)
    for kind, value in identifiers:
        # lead de teste com o telefone de alguém real não cola o e-mail da QA na pessoa real
        if kind not in found and not (test and found):
            row = conn.execute("INSERT INTO person_identifier (kind, value, person_id, event_id) VALUES (?, ?, ?, ?)"
                               " RETURNING rowid", (kind, value, person_id, event_id)).fetchone()
            audit(conn, actor, "identificador.gravado", "person_identifier", row[0], event_id)
    return person_id


def enqueue(conn, opportunity_id, queue, event_id, actor):
    """Encaminhamento na outbox, na mesma transação de quem o pediu."""
    row = conn.execute("INSERT INTO handoff (opportunity_id, queue, created_at) VALUES (?, ?, ?) RETURNING id",
                       (opportunity_id, queue, now())).fetchone()
    audit(conn, actor, "handoff.criado", "handoff", row["id"], event_id)


def open_opportunity(conn, person_id, product, unit, event_id, actor, test):
    """Reusa a oportunidade aberta de mesma pessoa+produto+unidade, ou qualifica uma ainda a_definir/desconhecida
    (ex.: WhatsApp direto que depois manda formulário); senão cria. O encaminhamento vai para a outbox."""
    # campo que o toque não sabe (a_definir/desconhecida) casa com qualquer valor: o formulário do /contato com produto
    # e sem unidade entra na aberta de SP, sem abrir outra nem mandar à triagem em paralelo à vendedora. A de mesma
    # chave vem primeiro; não há como colidir com outra aberta da mesma chave ao qualificar
    row = conn.execute("SELECT id, product, unit FROM opportunity WHERE person_id = :person AND status = 'aberta'"
                       " AND is_test = :test AND (product IN (:product, 'a_definir') OR :product = 'a_definir')"
                       " AND (unit IN (:unit, 'desconhecida') OR :unit = 'desconhecida')"
                       " ORDER BY (product = 'a_definir') + (unit = 'desconhecida'), id LIMIT 1",
                       {"person": person_id, "product": product, "unit": unit, "test": test}).fetchone()
    if row:  # o que a oportunidade já sabe não é rebaixado pelo toque que não sabe
        product = row["product"] if product == "a_definir" else product
        unit = row["unit"] if unit == "desconhecida" else unit
    if row and (row["product"], row["unit"]) == (product, unit):
        return row
    queue_of = (lambda *_: domain.TEST_QUEUE) if test else domain.queue_for
    old_queue = queue_of(row["unit"], row["product"]) if row else None
    if row:
        conn.execute("UPDATE opportunity SET product = ?, unit = ? WHERE id = ?", (product, unit, row["id"]))
        audit(conn, actor, "opportunity.requalificada", "opportunity", row["id"], event_id)
    else:
        row = conn.execute("INSERT INTO opportunity (person_id, product, unit, is_test, created_at) VALUES (?, ?, ?, ?, ?)"
                           " RETURNING id", (person_id, product, unit, test, now())).fetchone()
        audit(conn, actor, "opportunity.criada", "opportunity", row["id"], event_id)
    if queue_of(unit, product) != old_queue:  # qualificada só ganha encaminhamento novo se mudou de fila
        enqueue(conn, row["id"], queue_of(unit, product), event_id, actor)
    return {"id": row["id"], "product": product, "unit": unit}


def record_contact(conn, source, dedup_key, payload, identifiers, name, touch, occurred_at, issues, validity_days,
                   consent=None, stored=None):
    """Formulário ou WhatsApp: recibo, pessoa, oportunidade, toque e pendências, tudo ou nada."""
    actor = f"webhook:{source}"
    with LOCK, conn:
        event_id, repeated = receive(conn, source, dedup_key, payload, actor, stored)
        if repeated in ("duplicado", "conflito"):
            return {"status": repeated, "event_id": event_id}
        if not identifiers:
            # sem identificador válido não há pessoa: o lead não se perde, espera em quarentena o reenvio corrigido
            return quarantine(conn, event_id, issues, actor)
        if repeated == "reprocessar":
            release(conn, event_id, "contato.reprocessado", actor)
        test = bool(touch.get("is_test"))
        person_id = resolve_person(conn, identifiers, name, event_id, actor, test)
        # oportunidade aberta sem toque há mais de N dias (pela hora do evento) fecha como perdida: o contato de agora
        # abre uma nova e é o primeiro toque dela, em vez de o crédito ficar com um contato de meses atrás. A que está em
        # negociação (etiqueta da vendedora) não expira sozinha: quem a fecha é a etiqueta 'perdida'
        cutoff = domain.utc_iso(datetime.fromisoformat(occurred_at) - timedelta(days=validity_days))
        for row in conn.execute("UPDATE opportunity SET status = 'perdida' WHERE person_id = ? AND status = 'aberta'"
                                " AND stage IS NULL AND is_test = ?"
                                " AND (SELECT MAX(occurred_at) FROM touchpoint WHERE opportunity_id = opportunity.id) < ?"
                                " RETURNING id", (person_id, test, cutoff)).fetchall():
            audit(conn, actor, "opportunity.expirada", "opportunity", row["id"], event_id)
        origin_type, source_channel = domain.classify(touch)
        opp = queue = None
        if not touch.get("product") and not touch.get("unit"):
            # sem produto e sem unidade (ex.: "obrigada" no WhatsApp, anúncio fora do catálogo) e com oportunidade
            # aberta: é continuação da conversa. Não cria 'a_definir' nem manda para a triagem em paralelo à vendedora.
            # Sem aberta e com uma ganha, sem evidência é aluna ("qual a sala amanhã?"): o toque vai para a ganha e a
            # conversa ao atendimento. Observado (clique em anúncio) e formulário não entram na ganha: é interesse novo.
            # shortcut: mesmo assim a mensagem vira toque e pode virar último toque; filtrar mensagens de conversa já
            # aberta antes de usar atribuição por último toque.
            opp = conn.execute("SELECT id, product, unit, status FROM opportunity WHERE person_id = ? AND is_test = ?"
                               " AND (status = 'aberta' OR (status = 'ganha' AND ?))"
                               " ORDER BY status = 'aberta' DESC, id DESC LIMIT 1",
                               (person_id, test, origin_type != "observada" and touch["contact_channel"] == "whatsapp")).fetchone()
        if opp and opp["status"] == "ganha":
            queue = domain.STUDENT_QUEUE
            if not conn.execute("SELECT 1 FROM handoff WHERE opportunity_id = ? AND queue = ?",
                                (opp["id"], queue)).fetchone():
                enqueue(conn, opp["id"], queue, event_id, actor)
        opp = opp or open_opportunity(conn, person_id, touch.get("product") or "a_definir",
                                      touch.get("unit") or "desconhecida", event_id, actor, test)
        row = {k: touch.get(k) for k in TOUCH_FIELDS} | {
            "person_id": person_id, "opportunity_id": opp["id"], "event_id": event_id, "occurred_at": occurred_at,
            "is_test": test, "origin_type": origin_type, "source_channel": source_channel, "evidence_level": domain.evidence_level(touch)}
        touch_id = conn.execute(f"INSERT INTO touchpoint ({', '.join(row)}) VALUES ({', '.join(':' + k for k in row)})"
                                " RETURNING id", row).fetchone()["id"]
        audit(conn, actor, "toque.criado", "touchpoint", touch_id, event_id)
        for kind, entry_point, detail in issues:
            open_issue(conn, kind, entry_point, event_id, detail, actor)
        for purpose, granted in ({} if test else consent or {}).items():  # aceite de QA não é da pessoa
            if granted is not None:  # campo ausente não vira "não consentiu"
                consent_id = conn.execute("INSERT INTO consent (person_id, purpose, granted, event_id, at)"
                                          " VALUES (?, ?, ?, ?, ?) RETURNING id",
                                          (person_id, purpose, granted, event_id, occurred_at)).fetchone()["id"]
                audit(conn, actor, "consentimento.gravado", "consent", consent_id, event_id)
    return {"status": "processado", "event_id": event_id, "person_id": person_id, "opportunity_id": opp["id"],
            "origin_type": origin_type, "source_channel": source_channel,
            "queue": queue or (domain.TEST_QUEUE if test else domain.queue_for(opp["unit"], opp["product"]))}


def record_sale(conn, payload, sale, invalid, catalog):
    """Venda confirmada pelo ERP. Liga pela oportunidade que o CRM mandou ao ERP. payload é o que chegou (recibo);
    sale é o que deu para ler dele; invalid, os campos ilegíveis."""
    actor = "webhook:erp"
    with LOCK, conn:
        event_id, repeated = receive(conn, "erp", sale["erp_sale_id"], payload, actor)
        if repeated in ("duplicado", "conflito"):
            return {"status": repeated, "event_id": event_id}
        # na dúvida não aplica nada: venda estacionada não cria pessoa, toque, origem nem fecha oportunidade
        if invalid:
            return quarantine(conn, event_id, [("payload_invalido", None, {"campos": invalid})], actor)
        opp = conn.execute("SELECT id, person_id, product, unit, status FROM opportunity WHERE id = ?",
                           (sale["crm_opportunity_id"],)).fetchone()
        if problem := domain.sale_problem(sale, opp, catalog):
            detail = {"erp_sale_id": sale["erp_sale_id"], "crm_opportunity_id": sale["crm_opportunity_id"]}
            if opp and opp["status"] == "perdida":
                # a pessoa voltou e abriu outra: aponta a aberta de mesmo produto e unidade (o índice garante uma só)
                other = conn.execute("SELECT id FROM opportunity WHERE person_id = ? AND product = ? AND unit = ?"
                                     " AND status = 'aberta'", (opp["person_id"], sale["product"], sale["unit"])).fetchone()
                detail |= {"motivo": "oportunidade_perdida"} | ({"oportunidade_aberta": other["id"]} if other else {})
            return quarantine(conn, event_id, [(problem, None, detail)], actor)
        if repeated == "reprocessar":
            release(conn, event_id, "venda.reprocessada", actor)
        row = conn.execute("INSERT INTO erp_sale (erp_sale_id, opportunity_id, amount_cents, confirmed_at, event_id)"
                           " VALUES (?, ?, ?, ?, ?) RETURNING rowid",
                           (sale["erp_sale_id"], opp["id"], sale["amount_cents"], domain.utc_iso(sale["confirmed_at"]),
                            event_id)).fetchone()
        audit(conn, actor, "venda.gravada", "erp_sale", row[0], event_id)
        # numa venda que passou por sale_problem, campo diferente só pode ser a_definir/desconhecida: a venda qualifica.
        # Um UPDATE só, para a oportunidade já sair de 'aberta' e não colidir com outra aberta da mesma chave.
        conn.execute("UPDATE opportunity SET status = 'ganha', product = ?, unit = ? WHERE id = ?",
                     (sale["product"], sale["unit"], opp["id"]))
        if (opp["product"], opp["unit"]) != (sale["product"], sale["unit"]):
            audit(conn, actor, "opportunity.requalificada", "opportunity", opp["id"], event_id)
        audit(conn, actor, "opportunity.ganha", "opportunity", opp["id"], event_id)
        # uma linha por plataforma, com o click id mais recente dela; sem click id (ou lead de teste) não há o que devolver
        latest = {}
        for click in conn.execute("SELECT click_id_type, click_id, occurred_at, evidence_level FROM touchpoint"
                                  " WHERE opportunity_id = ?"
                                  f" AND click_id IS NOT NULL AND opportunity_id NOT IN ({TEST_OPPS})"
                                  " ORDER BY occurred_at DESC, id DESC", (opp["id"],)):
            latest.setdefault(domain.PLATFORM[click["click_id_type"]], click)
        sensitive = catalog["products"].get(sale["product"], {}).get("sensivel", False)
        # vale o último registro de consentimento para anúncios; sem registro, ninguém consentiu
        consent = conn.execute("SELECT granted FROM consent WHERE person_id = ? AND purpose = 'ads'"
                               " ORDER BY at DESC, id DESC LIMIT 1", (opp["person_id"],)).fetchone()
        for platform, click in latest.items():
            # idade do clique na venda (Google: importação offline até 90 dias; Meta: cookie _fbc de 90 dias). O limite
            # de 7 dias da CAPI é outro: entre a venda (event_time) e o envio, e vale no despacho (desenho)
            days = catalog["validade_click_id_dias"][platform]
            expired = click["occurred_at"] < domain.utc_iso(sale["confirmed_at"] - timedelta(days=days))
            row = conn.execute("INSERT INTO platform_conversion (erp_sale_id, platform, click_id_type, click_id, event_id,"
                               " status, created_at) VALUES (:sale, :platform, :click_id_type, :click_id, :sale, :status,"
                               " :at) RETURNING id",
                               domain.conversion(click["click_id_type"], click["click_id"], sensitive,
                                                 bool(consent and consent["granted"]), expired)
                               | {"sale": sale["erp_sale_id"], "at": now()}).fetchone()
            audit(conn, actor, "conversao.criada", "platform_conversion", row["id"], event_id)
    return {"status": "processado", "event_id": event_id, "person_id": opp["person_id"], "opportunity_id": opp["id"]}


def dispatch_handoffs(conn, send):
    """Entrega à fila de atendimento os encaminhamentos pendentes da outbox.

    Timeout vira 'incerto' e não é reenviado na rodada seguinte: o atendimento pode ter recebido, e reenviar às cegas
    duplicaria a conversa. Alguém confere no atendimento e decide. Outro erro devolve a 'pendente' o que não saiu e
    sobe a exceção. 'enviando' que sobra (processo caiu no meio) tem o mesmo tratamento de 'incerto'.
    """
    # shortcut: do atendimento só volta a etiqueta da conversa (record_label), não a confirmação de que o
    # encaminhamento chegou; o 'incerto' é conferido à mão até essa confirmação existir
    with LOCK, conn:
        # toma posse antes de soltar a trava: outra rodada em paralelo não vê estes como pendentes
        pending = sorted(conn.execute("UPDATE handoff SET status = 'enviando' WHERE status = 'pendente'"
                                      " RETURNING id, opportunity_id, queue").fetchall(), key=lambda h: h["id"])
        for handoff in pending:
            audit(conn, "despacho", "handoff.enviando", "handoff", handoff["id"], None)
    for i, handoff in enumerate(pending):
        try:
            send(dict(handoff))
            status = "enviado"
        except TimeoutError:
            status = "incerto"
        except Exception:
            with LOCK, conn:
                for h in pending[i:]:
                    set_handoff(conn, h["id"], "pendente")
            raise
        with LOCK, conn:
            set_handoff(conn, handoff["id"], status)


def set_handoff(conn, handoff_id, status):
    conn.execute("UPDATE handoff SET status = ? WHERE id = ?", (status, handoff_id))
    audit(conn, "despacho", f"handoff.{status}", "handoff", handoff_id, None)


def record_click(conn, entry_point, tracking, rng):
    """Leitura do /q/: grava a sessão do clique e devolve o protocolo que vai no texto do WhatsApp."""
    with LOCK, conn:
        for _ in range(10):  # protocolo já usado: sorteia outro
            row = conn.execute("INSERT INTO click_session (entry_point, protocol, utm_source, utm_medium, utm_campaign,"
                               " utm_id, utm_content, click_id_type, click_id, created_at) VALUES (:entry_point,"
                               " :protocol, :utm_source, :utm_medium, :utm_campaign, :utm_id, :utm_content,"
                               " :click_id_type, :click_id, :at) ON CONFLICT (protocol) DO NOTHING RETURNING id, protocol",
                               tracking | {"entry_point": entry_point, "protocol": domain.new_protocol(rng),
                                           "at": now()}).fetchone()
            if row:
                audit(conn, "q", "sessao.criada", "click_session", row["id"], None)
                return row["protocol"]
    raise RuntimeError("sem protocolo livre")


def click_session(conn, protocol, identifiers):
    """Sessão do protocolo e se outra pessoa (outros identificadores) já mandou mensagem com ele."""
    row = conn.execute("SELECT *, EXISTS (SELECT 1 FROM touchpoint t WHERE t.click_session_id = s.id AND t.person_id"
                       " NOT IN (SELECT person_id FROM person_identifier i JOIN json_each(?) j"
                       " ON i.kind = json_extract(j.value, '$[0]') AND i.value = json_extract(j.value, '$[1]')))"
                       " AS outra_pessoa FROM click_session s WHERE protocol = ?",
                       (json.dumps(identifiers), protocol)).fetchone()
    return dict(row) if row else None


def record_label(conn, payload, key, phone, label, opportunity_id, echo, invalid):
    """Etiqueta da conversa no atendimento (Chatwoot): em_negociacao grava o estágio e perdida fecha a oportunidade.
    A oportunidade é a da conversa (opportunity_id, que o núcleo grava no Chatwoot) ou a única aberta da pessoa."""
    actor = "webhook:atendimento"
    with LOCK, conn:
        event_id, repeated = receive(conn, "atendimento", key, payload, actor)
        if repeated in ("duplicado", "conflito"):
            return {"status": repeated, "event_id": event_id}
        if echo:
            return {"status": "ignorado", "event_id": event_id}  # etiqueta que o próprio núcleo gravou: quebra o loop
        if invalid:
            return quarantine(conn, event_id, [("payload_invalido", None, {"campos": invalid})], actor)
        # com o id da conversa basta ele (quem só tem BSUID não tem telefone); o telefone, se veio, tem de ser da pessoa
        opps = conn.execute("SELECT id, status, stage FROM opportunity WHERE (:phone IS NULL OR person_id = (SELECT"
                            " person_id FROM person_identifier WHERE kind = 'phone' AND value = :phone))"
                            " AND (id = :id OR (:id IS NULL AND status = 'aberta' AND NOT is_test))",
                            {"phone": phone, "id": opportunity_id}).fetchall()
        if len(opps) > 1:
            # duas abertas e a conversa sem o id: fechar a mais recente pode fechar a errada
            detail = {"label": label, "oportunidades": [o["id"] for o in opps]}
            return quarantine(conn, event_id, [("etiqueta_ambigua", None, detail)], actor)
        opp = opps[0] if opps else None
        # etiqueta igual ao estado que a oportunidade já tem: é o eco do que o núcleo gravou, mesmo sem origin_system
        same = opp and label in (opp["stage"], opp["status"])
        if not opp or (opp["status"] != "aberta" and not same):
            return quarantine(conn, event_id, [("etiqueta_sem_oportunidade", None, {"label": label})], actor)
        if repeated == "reprocessar":
            release(conn, event_id, "etiqueta.reprocessada", actor)
        if same:
            return {"status": "ignorado", "event_id": event_id}
        change = {"em_negociacao": "stage = 'em_negociacao'", "perdida": "status = 'perdida'"}[label]
        conn.execute(f"UPDATE opportunity SET {change} WHERE id = ?", (opp["id"],))
        audit(conn, actor, f"opportunity.{label}", "opportunity", opp["id"], event_id)
    return {"status": "processado", "event_id": event_id, "opportunity_id": opp["id"], "label": label}


def record_skipped(conn, source, detail):
    """Item do lote que não dá nem para ter recibo (ex.: mensagem que não é objeto): só a pendência, sem evento."""
    with LOCK, conn:
        open_issue(conn, "payload_invalido", None, None, detail, f"webhook:{source}")
    return {"status": "ignorado", "motivo": "payload_invalido"}


def touches(conn, where, value):
    return [dict(r) for r in conn.execute(f"SELECT * FROM touchpoint WHERE {where} = ? ORDER BY occurred_at, id",
                                          (value,))]


def attributed_touch(conn, opportunity_id):
    # modelo de atribuição do lead e da venda: primeiro toque observado; sem nenhum, o primeiro toque. Um "oi" no
    # WhatsApp direto antes do formulário pago não leva a origem. Último toque observado seria só o DESC.
    return conn.execute("SELECT * FROM touchpoint WHERE opportunity_id = ?"
                        " ORDER BY origin_type <> 'observada', occurred_at, id LIMIT 1", (opportunity_id,)).fetchone()


def journey(conn, person_id):
    person = conn.execute("SELECT id, name FROM person WHERE id = ?", (person_id,)).fetchone()
    if not person:
        return None
    opps = conn.execute("SELECT id, product, unit, status FROM opportunity WHERE person_id = ? ORDER BY id",
                        (person_id,))
    consents = conn.execute("SELECT purpose, granted, at, event_id FROM consent WHERE person_id = ? ORDER BY at, id",
                            (person_id,))
    return {"person_id": person["id"], "nome": person["name"], "oportunidades": [dict(r) for r in opps],
            "toques": touches(conn, "person_id", person_id),
            "consentimentos": [dict(r) | {"granted": bool(r["granted"])} for r in consents]}


def opportunity(conn, opportunity_id):
    opp = conn.execute("SELECT id, person_id, product, unit, status, stage FROM opportunity WHERE id = ?",
                       (opportunity_id,)).fetchone()
    if not opp:
        return None
    history = touches(conn, "opportunity_id", opportunity_id)
    sales = conn.execute("SELECT erp_sale_id, amount_cents, confirmed_at FROM erp_sale WHERE opportunity_id = ?",
                         (opportunity_id,))
    handoffs = conn.execute("SELECT queue, status FROM handoff WHERE opportunity_id = ? ORDER BY id", (opportunity_id,))
    # primeiro e último são cronológicos; o atribuído é o que leva a origem no relatório (attributed_touch)
    return dict(opp) | {"toque_atribuido": dict(attributed_touch(conn, opportunity_id)),
                        "primeiro_toque": history[0], "ultimo_toque": history[-1],
                        "vendas": [dict(r) for r in sales], "encaminhamentos": [dict(r) for r in handoffs]}


def origin_key(touch):
    # canal declarado só aparece na chave da declarada: nunca se soma ao observado
    channel = {"observada": touch["source_channel"], "declarada": touch["declared"]}.get(touch["origin_type"])
    return f"{touch['origin_type']}:{channel}" if channel else touch["origin_type"]


NO_ENTRY_POINT = "(sem ponto de entrada)"


def quality_report(conn, catalog):
    rules = catalog["liberacao"]
    # conta leads (toque atribuído de cada oportunidade), não mensagens; lead de teste fica fora de contagem, liberação
    # e receita
    # paciente modelo é outro funil: conta à parte, fora da origem e da receita de curso
    opps = conn.execute(f"SELECT id, product FROM opportunity WHERE id NOT IN ({TEST_OPPS}) ORDER BY id").fetchall()
    leads = [attributed_touch(conn, r["id"]) for r in opps]
    patient = {r["id"] for r in opps if r["product"] == domain.PATIENT_PRODUCT}
    # por ponto de entrada, cada oportunidade que passou por ele, pelo 1º toque dela ali: quem volta pela LP com o link
    # quebrado também pesa na liberação da LP. Sem ponto de entrada só conta o toque atribuído ("obrigada" não é lead)
    entries = [t for t in leads if not t["entry_point"]] + conn.execute(
        f"SELECT * FROM touchpoint t WHERE opportunity_id NOT IN ({TEST_OPPS}) AND id = (SELECT id FROM touchpoint"
        " WHERE opportunity_id = t.opportunity_id AND entry_point = t.entry_point ORDER BY occurred_at, id LIMIT 1)"
    ).fetchall()
    flagged = {r["event_id"] for r in conn.execute("SELECT event_id FROM tracking_issue WHERE status = 'aberta'"
                                                   " AND kind IN ('parametros_perdidos', 'retorno_sem_parametro',"
                                                   " 'utm_fora_do_padrao')")}
    # leituras do /q/ e quantas viraram contato (sessões distintas com toque): ponto lido e sem contato aparece
    reads = {}
    for r in conn.execute("SELECT entry_point, COUNT(*) AS leituras, COUNT(DISTINCT t.click_session_id) AS chegadas"
                          " FROM click_session s LEFT JOIN (SELECT DISTINCT click_session_id FROM touchpoint) t"
                          " ON t.click_session_id = s.id GROUP BY entry_point"):
        rate = round(r["chegadas"] / r["leituras"], 3)
        # muita leitura e pouca mensagem: o QR ou o link leva a um WhatsApp onde a pessoa desiste ou apaga o protocolo.
        # É alerta, não bloqueio: robô que se passa por navegador também lê, e quem confere é o dono do ponto. Só no /q/
        # que vai ao WhatsApp: na LP a chegada é o formulário, que a taxa não vê
        low = (catalog["entry_points"].get(r["entry_point"], {}).get("q") == "whatsapp"
               and r["leituras"] >= rules["min_leituras"] and rate < rules["min_taxa_chegada"])
        whatsapp = catalog["entry_points"].get(r["entry_point"], {}).get("q") == "whatsapp"
        reads[r["entry_point"]] = {"leituras": r["leituras"]} | ({"taxa_chegada": rate} if whatsapp else {}) | (
            {"alerta": "chegada_baixa"} if low else {})
    points, history = {ep: Counter(total=0, desconhecida=0, com_problema=0) for ep in reads}, {}
    for t in sorted(entries, key=lambda t: (t["occurred_at"], t["id"])):
        ep, problem = t["entry_point"] or NO_ENTRY_POINT, t["origin_type"] == "desconhecida" or t["event_id"] in flagged
        p = points.setdefault(ep, Counter(total=0, desconhecida=0, com_problema=0))
        p["total"] += 1
        p["desconhecida"] += t["origin_type"] == "desconhecida"
        p["com_problema"] += problem
        history.setdefault(ep, []).append((t["occurred_at"], problem))
    issues = conn.execute("SELECT kind, COUNT(*) AS n FROM tracking_issue WHERE status = 'aberta' GROUP BY kind"
                          " ORDER BY kind")
    events = conn.execute("SELECT COUNT(*) FILTER (WHERE status = 'processado') AS processado,"
                          " COUNT(*) FILTER (WHERE status = 'quarentena') AS quarentena,"
                          " COALESCE(SUM(duplicates), 0) AS duplicatas_recebidas FROM inbound_event").fetchone()
    all_sales = [(s["amount_cents"], attributed_touch(conn, s["opportunity_id"])) for s in conn.execute(
        f"SELECT opportunity_id, amount_cents FROM erp_sale WHERE opportunity_id NOT IN ({TEST_OPPS})").fetchall()]
    sales = [(a, t) for a, t in all_sales if t["opportunity_id"] not in patient]
    patient_sales = [a for a, t in all_sales if t["opportunity_id"] in patient]
    # valor ilegível de venda em quarentena (ex.: "muito") não entra na soma
    quarantined = conn.execute("SELECT COALESCE(SUM(json_extract(payload, '$.amount_cents')), 0) FROM inbound_event"
                               " WHERE source = 'erp' AND status = 'quarentena'"
                               " AND json_type(payload, '$.amount_cents') = 'integer'"
                               " AND json_extract(payload, '$.amount_cents') >= 0").fetchone()[0]
    # Sem ponto de entrada (WhatsApp direto) não há canal a liberar: status None.
    pontos = [{"entry_point": ep, **p, "taxa_problema": round(p["com_problema"] / p["total"], 3) if p["total"] else None,
               "status": None if ep == NO_ENTRY_POINT else domain.release_status(history.get(ep, []), rules)}
              | reads.get(ep, {}) for ep, p in sorted(points.items())]
    liberados = {p["entry_point"] for p in pontos if p["status"] == "liberado"}
    return {
        "origem_por_canal": dict(sorted(Counter(origin_key(t) for t in leads if t["opportunity_id"] not in patient).items())),
        "paciente_modelo": {
            "origem_por_canal": dict(sorted(Counter(origin_key(t) for t in leads if t["opportunity_id"] in patient).items())),
            "vendas": len(patient_sales), "valor_cents": sum(patient_sales)},
        "pontos_de_entrada": pontos,
        "issues_abertas": {r["kind"]: r["n"] for r in issues},
        "eventos": dict(events),
        "vendas": {
            "total": len(sales),
            "valor_cents": sum(amount for amount, _ in sales),
            "por_origem_atribuida": dict(sorted(Counter(origin_key(t) for _, t in sales).items())),
            # só esta entra no custo por canal: venda de ponto ainda não liberado não contamina o indicador
            "valor_em_pontos_liberados_cents": sum(amount for amount, t in sales if t["entry_point"] in liberados),
        },
        # receita sem nenhum toque observado (o atribuído só não é observado assim), não redistribuída; quarentena (erro
        # de integração) fica no campo ao lado
        "receita_sem_origem_cents": sum(amount for amount, t in sales if t["origin_type"] != "observada"),
        "receita_em_quarentena_cents": quarantined,
    }
