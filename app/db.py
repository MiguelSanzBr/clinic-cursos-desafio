"""Todo o SQL da demo. Cada evento recebido grava recibo e efeitos numa transação só."""
import json
import sqlite3
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from app import domain

SCHEMA = Path(__file__).with_name("schema.sql").read_text()
TOUCH_FIELDS = ("contact_channel", "utm_source", "utm_medium", "utm_campaign", "utm_id", "utm_content",
                "click_id_type", "click_id", "ad_id", "entry_point", "unit", "product", "declared")


def connect(path):
    # shortcut: uma conexão compartilhada entre threads (check_same_thread=False), sem lock; requisições simultâneas
    # podem se misturar na mesma transação. Trocar por conexão por requisição (ou Postgres) antes de tráfego real.
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
    open_issue(conn, "evento_conflitante", None, first["id"], {"source": source, "dedup_key": dedup_key}, actor)
    return first["id"], "conflito"


def resolve_person(conn, identifiers, name, event_id, actor):
    """Acha a pessoa só por identificador normalizado. Nome nunca entra no matching."""
    found = {}
    for kind, value in identifiers:
        row = conn.execute("SELECT person_id FROM person_identifier WHERE kind = ? AND value = ?", (kind, value)).fetchone()
        if row:
            found[kind] = row["person_id"]
    if found:
        person_id = found.get("phone") or found["email"]
        if len(set(found.values())) > 1:
            # telefone e e-mail apontam para pessoas diferentes: não funde sozinho, fica para revisão humana
            open_issue(conn, "identidade_conflitante", None, event_id, {"person_ids": sorted(set(found.values()))}, actor)
    else:
        person_id = conn.execute("INSERT INTO person (name, created_at) VALUES (?, ?) RETURNING id",
                                 (name, now())).fetchone()["id"]
        audit(conn, actor, "person.criada", "person", person_id, event_id)
    for kind, value in identifiers:
        if kind not in found:
            conn.execute("INSERT INTO person_identifier (kind, value, person_id, event_id) VALUES (?, ?, ?, ?)",
                         (kind, value, person_id, event_id))
    return person_id


def open_opportunity(conn, person_id, product, unit, event_id, actor):
    """Reusa a oportunidade aberta de mesma pessoa+produto+unidade; senão cria e põe o encaminhamento na outbox."""
    row = conn.execute("SELECT id, unit FROM opportunity WHERE person_id = ? AND product = ? AND unit = ?"
                       " AND status = 'aberta'", (person_id, product, unit)).fetchone()
    if row:
        return row
    row = conn.execute("INSERT INTO opportunity (person_id, product, unit, created_at) VALUES (?, ?, ?, ?)"
                       " RETURNING id, unit", (person_id, product, unit, now())).fetchone()
    audit(conn, actor, "opportunity.criada", "opportunity", row["id"], event_id)
    conn.execute("INSERT INTO handoff (opportunity_id, queue, created_at) VALUES (?, ?, ?)",
                 (row["id"], domain.queue_for(unit), now()))
    return row


def record_contact(conn, source, dedup_key, payload, identifiers, name, touch, occurred_at, issues, consent=None,
                   stored=None):
    """Formulário ou WhatsApp: recibo, pessoa, oportunidade, toque e pendências, tudo ou nada."""
    actor = f"webhook:{source}"
    with conn:
        event_id, repeated = receive(conn, source, dedup_key, payload, actor, stored)
        if repeated in ("duplicado", "conflito"):
            return {"status": repeated, "event_id": event_id}
        person_id = resolve_person(conn, identifiers, name, event_id, actor)
        origin_type, source_channel = domain.classify(touch)
        opp = None
        if origin_type != "observada" and not touch.get("product") and not touch.get("unit"):
            # sem evidência, sem produto e sem unidade (ex.: "obrigada" no WhatsApp) e com oportunidade aberta: é
            # continuação da conversa, não interesse novo. Não cria 'a_definir' nem manda para a triagem.
            # shortcut: mesmo assim a mensagem vira toque (desconhecida) e pode virar último toque; filtrar mensagens
            # de conversa já aberta antes de usar atribuição por último toque.
            opp = conn.execute("SELECT id, unit FROM opportunity WHERE person_id = ? AND status = 'aberta'"
                               " ORDER BY id DESC LIMIT 1", (person_id,)).fetchone()
        opp = opp or open_opportunity(conn, person_id, touch.get("product") or "a_definir",
                                      touch.get("unit") or "desconhecida", event_id, actor)
        row = {k: touch.get(k) for k in TOUCH_FIELDS} | {
            "person_id": person_id, "opportunity_id": opp["id"], "event_id": event_id, "occurred_at": occurred_at,
            "origin_type": origin_type, "source_channel": source_channel}
        conn.execute(f"INSERT INTO touchpoint ({', '.join(row)}) VALUES ({', '.join(':' + k for k in row)})", row)
        for kind, entry_point, detail in issues:
            open_issue(conn, kind, entry_point, event_id, detail, actor)
        if consent is not None:
            conn.execute("INSERT INTO consent (person_id, purpose, granted, event_id, at)"
                         " VALUES (?, 'marketing', ?, ?, ?)",
                         (person_id, consent, event_id, occurred_at))
    return {"status": "processado", "event_id": event_id, "person_id": person_id, "opportunity_id": opp["id"],
            "origin_type": origin_type, "source_channel": source_channel, "queue": domain.queue_for(opp["unit"])}


def record_sale(conn, payload, confirmed_at, catalog):
    """Venda confirmada pelo ERP. Liga pela oportunidade que o CRM mandou ao ERP."""
    actor = "webhook:erp"
    with conn:
        event_id, repeated = receive(conn, "erp", payload["erp_sale_id"], payload, actor)
        if repeated in ("duplicado", "conflito"):
            return {"status": repeated, "event_id": event_id}
        opp = conn.execute("SELECT id, person_id, product, unit FROM opportunity WHERE id = ?",
                           (payload["crm_opportunity_id"],)).fetchone()
        if problem := domain.sale_problem(payload, opp):
            # na dúvida não aplica nada: venda estacionada não cria pessoa, toque, origem nem fecha oportunidade
            conn.execute("UPDATE inbound_event SET status = 'quarentena' WHERE id = ?", (event_id,))
            if not conn.execute("SELECT 1 FROM tracking_issue WHERE event_id = ? AND kind = ? AND status = 'aberta'",
                                (event_id, problem)).fetchone():
                open_issue(conn, problem, None, event_id, {"erp_sale_id": payload["erp_sale_id"],
                                                           "crm_opportunity_id": payload["crm_opportunity_id"]}, actor)
            return {"status": "quarentena", "event_id": event_id, "motivo": problem}
        conn.execute("INSERT INTO erp_sale (erp_sale_id, opportunity_id, amount_cents, confirmed_at, event_id)"
                     " VALUES (?, ?, ?, ?, ?)",
                     (payload["erp_sale_id"], opp["id"], payload["amount_cents"], confirmed_at, event_id))
        conn.execute("UPDATE opportunity SET status = 'ganha' WHERE id = ?", (opp["id"],))
        audit(conn, actor, "opportunity.ganha", "opportunity", opp["id"], event_id)
        click = conn.execute("SELECT click_id_type, click_id FROM touchpoint WHERE opportunity_id = ? AND click_id IS NOT NULL"
                             " ORDER BY occurred_at, id LIMIT 1", (opp["id"],)).fetchone()
        if click:  # sem click id não há o que devolver à plataforma
            sensitive = catalog["products"].get(opp["product"], {}).get("sensivel", False)
            conn.execute("INSERT INTO platform_conversion (erp_sale_id, platform, click_id_type, click_id, event_id, status,"
                         " created_at) VALUES (:sale, :platform, :click_id_type, :click_id, :sale, :status, :at)",
                         domain.conversion(click["click_id_type"], click["click_id"], sensitive)
                         | {"sale": payload["erp_sale_id"], "at": now()})
        if repeated == "reprocessar":
            conn.execute("UPDATE inbound_event SET status = 'processado' WHERE id = ?", (event_id,))
            conn.execute("UPDATE tracking_issue SET status = 'resolvida' WHERE event_id = ? AND status = 'aberta'",
                         (event_id,))
            audit(conn, actor, "venda.reprocessada", "inbound_event", event_id, event_id)
    return {"status": "processado", "event_id": event_id, "person_id": opp["person_id"], "opportunity_id": opp["id"]}


def dispatch_handoffs(conn, send):
    """Entrega à fila de atendimento os encaminhamentos pendentes da outbox.

    Timeout vira 'incerto' e não é reenviado na rodada seguinte: o atendimento pode ter recebido, e reenviar às cegas
    duplicaria a conversa. Alguém confere no atendimento e decide. Outro erro deixa 'pendente' e sobe a exceção.
    """
    # shortcut: sem sync atendimento -> CRM (status da conversa não volta); entra junto com o atendimento real
    pending = conn.execute("SELECT id, opportunity_id, queue FROM handoff WHERE status = 'pendente' ORDER BY id")
    for handoff in pending.fetchall():
        try:
            send(dict(handoff))
            status = "enviado"
        except TimeoutError:
            status = "incerto"
        with conn:
            conn.execute("UPDATE handoff SET status = ? WHERE id = ?", (status, handoff["id"]))


def touches(conn, where, value):
    return [dict(r) for r in conn.execute(f"SELECT * FROM touchpoint WHERE {where} = ? ORDER BY occurred_at, id",
                                          (value,))]


def attributed_touch(conn, opportunity_id):
    # modelo de atribuição da venda: primeiro toque. Para último toque, inverter este ORDER BY (DESC).
    return conn.execute("SELECT * FROM touchpoint WHERE opportunity_id = ? ORDER BY occurred_at, id LIMIT 1",
                        (opportunity_id,)).fetchone()


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
    opp = conn.execute("SELECT id, person_id, product, unit, status FROM opportunity WHERE id = ?",
                       (opportunity_id,)).fetchone()
    if not opp:
        return None
    history = touches(conn, "opportunity_id", opportunity_id)
    sales = conn.execute("SELECT erp_sale_id, amount_cents, confirmed_at FROM erp_sale WHERE opportunity_id = ?",
                         (opportunity_id,))
    handoffs = conn.execute("SELECT queue, status FROM handoff WHERE opportunity_id = ?", (opportunity_id,))
    return dict(opp) | {"primeiro_toque": history[0], "ultimo_toque": history[-1],
                        "vendas": [dict(r) for r in sales], "encaminhamentos": [dict(r) for r in handoffs]}


def origin_key(touch):
    # canal declarado só aparece na chave da declarada: nunca se soma ao observado
    channel = {"observada": touch["source_channel"], "declarada": touch["declared"]}.get(touch["origin_type"])
    return f"{touch['origin_type']}:{channel}" if channel else touch["origin_type"]


NO_ENTRY_POINT = "(sem ponto de entrada)"


def quality_report(conn, release_rules):
    # conta leads (1º toque de cada oportunidade), não mensagens
    leads = [attributed_touch(conn, r["id"]) for r in conn.execute("SELECT id FROM opportunity ORDER BY id").fetchall()]
    flagged = {r["event_id"] for r in conn.execute("SELECT event_id FROM tracking_issue WHERE status = 'aberta'"
                                                   " AND kind IN ('parametros_perdidos', 'utm_fora_do_padrao')")}
    points = {}
    for t in leads:
        p = points.setdefault(t["entry_point"] or NO_ENTRY_POINT, Counter(total=0, desconhecida=0, com_problema=0))
        p["total"] += 1
        p["desconhecida"] += t["origin_type"] == "desconhecida"
        p["com_problema"] += t["origin_type"] == "desconhecida" or t["event_id"] in flagged
    issues = conn.execute("SELECT kind, COUNT(*) AS n FROM tracking_issue WHERE status = 'aberta' GROUP BY kind"
                          " ORDER BY kind")
    events = conn.execute("SELECT COUNT(*) FILTER (WHERE status = 'processado') AS processado,"
                          " COUNT(*) FILTER (WHERE status = 'quarentena') AS quarentena,"
                          " COALESCE(SUM(duplicates), 0) AS duplicatas_recebidas FROM inbound_event").fetchone()
    sales = [(s["amount_cents"], attributed_touch(conn, s["opportunity_id"]))
             for s in conn.execute("SELECT opportunity_id, amount_cents FROM erp_sale").fetchall()]
    return {
        "origem_por_canal": dict(sorted(Counter(origin_key(t) for t in leads).items())),
        # shortcut: o período de observação do checklist (14 dias) fica fora da demo; só conta leads.
        # Sem ponto de entrada (WhatsApp direto, anúncio CTWA) não há canal a liberar: status None.
        "pontos_de_entrada": [
            {"entry_point": ep, **p, "taxa_problema": round(p["com_problema"] / p["total"], 3),
             "status": None if ep == NO_ENTRY_POINT else domain.release_status(p["total"], p["com_problema"], release_rules)}
            for ep, p in sorted(points.items())],
        "issues_abertas": {r["kind"]: r["n"] for r in issues},
        "eventos": dict(events),
        "vendas": {
            "total": len(sales),
            "valor_cents": sum(amount for amount, _ in sales),
            "por_origem_primeiro_toque": dict(sorted(Counter(origin_key(t) for _, t in sales).items())),
        },
        # receita que não dá para atribuir a canal observado: fica à parte, não é redistribuída
        "receita_sem_origem_cents": sum(amount for amount, t in sales if t["origin_type"] != "observada"),
    }
