import copy
import json
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import db
from app.main import create_app

EVENTOS = json.loads((Path(__file__).resolve().parents[1] / "data" / "eventos.json").read_text())


@pytest.fixture
def client():
    return TestClient(create_app(":memory:"))


def ev(name, **changes):
    return copy.deepcopy(EVENTOS[name]) | changes


def form(client, name, **changes):
    return client.post("/events/form", json=ev(name, **changes)).json()


def whatsapp(client, name):
    return client.post("/events/whatsapp", json=ev(name)).json()


def count(client, table):
    return client.app.state.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def test_c1_origem_campanha_preservada_ate_venda(client):
    lead = form(client, "C1_form_1001")
    assert (lead["status"], lead["origin_type"], lead["source_channel"], lead["queue"]) == (
        "processado", "observada", "meta", "comercial-sp")

    venda = client.post("/events/erp/sale", json=ev("venda_c1", crm_opportunity_id=lead["opportunity_id"])).json()
    assert venda["status"] == "processado"

    opp = client.get(f"/opportunities/{lead['opportunity_id']}").json()
    assert opp["status"] == "ganha"
    assert opp["vendas"][0]["erp_sale_id"] == "ERP-2026-5001"
    first = opp["primeiro_toque"]
    assert (first["utm_campaign"], first["utm_content"], first["click_id_type"], first["entry_point"]) == (
        "sp-micropigmentacao-captacao-202610", "video-01", "fbclid", "lp-sp-micro-01")
    assert not any("@" in str(v) for v in first.values())  # toque sem dado pessoal
    assert client.get("/quality/report").json()["vendas"]["por_origem_primeiro_toque"] == {"observada:meta": 1}


def test_c2_qr_unidade_distinto_de_whatsapp_direto(client):
    qr = whatsapp(client, "C2a_whatsapp_qr_cps")
    direto = whatsapp(client, "C2b_whatsapp_direto")
    assert (qr["origin_type"], qr["source_channel"], qr["queue"]) == ("observada", "qr_code", "comercial-cps")
    assert (direto["origin_type"], direto["source_channel"], direto["queue"]) == ("desconhecida", None, "triagem-bot")

    t_qr = client.get(f"/people/{qr['person_id']}/journey").json()["toques"][0]
    assert (t_qr["entry_point"], t_qr["unit"], t_qr["product"]) == ("qr-cps-recepcao-01", "cps", "paciente_modelo")
    t_dir = client.get(f"/people/{direto['person_id']}/journey").json()["toques"][0]
    sem_origem = ("utm_source", "utm_medium", "utm_campaign", "utm_content", "click_id", "ad_id", "entry_point")
    assert all(t_dir[k] is None for k in sem_origem)
    assert client.get("/quality/report").json()["issues_abertas"] == {}  # WhatsApp direto sem código é esperado


def test_c3_pessoa_existente_nova_campanha(client):
    c1 = form(client, "C1_form_1001")
    c3 = whatsapp(client, "C3_ana_volta_por_anuncio_ctwa")  # outro formato de telefone, outro nome no perfil
    assert c3["person_id"] == c1["person_id"]
    assert c3["opportunity_id"] != c1["opportunity_id"]
    assert (c3["origin_type"], c3["source_channel"], c3["queue"]) == ("observada", "meta_ctwa", "comercial-rj")

    jornada = client.get(f"/people/{c1['person_id']}/journey").json()
    assert len(jornada["oportunidades"]) == 2 and len(jornada["toques"]) == 2
    opp1 = client.get(f"/opportunities/{c1['opportunity_id']}").json()
    assert opp1["primeiro_toque"]["utm_campaign"] == "sp-micropigmentacao-captacao-202610"  # 1º toque intacto
    assert opp1["primeiro_toque"] == opp1["ultimo_toque"]

    c3b = whatsapp(client, "C3b_ana_mesmo_anuncio_de_novo")  # 3º contato, mesmo produto e unidade
    assert c3b["opportunity_id"] == c3["opportunity_id"]
    opp2 = client.get(f"/opportunities/{c3['opportunity_id']}").json()
    assert opp2["primeiro_toque"]["event_id"] == c3["event_id"]
    assert opp2["ultimo_toque"]["event_id"] == c3b["event_id"]
    assert count(client, "person") == 1 and count(client, "handoff") == 2


def test_touchpoint_append_only(client):
    form(client, "C1_form_1001")
    conn = client.app.state.conn
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        conn.execute("UPDATE touchpoint SET utm_source = 'google'")
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        conn.execute("DELETE FROM touchpoint")


def test_formulario_sem_identificador_rejeitado(client):
    r = client.post("/events/form", json=ev("C1_form_1001", email="sem-arroba", phone="123"))
    assert r.status_code == 422
    assert count(client, "inbound_event") == 0


def test_id_inexistente_404_e_webhook_sem_mensagem_ignorado(client):
    assert client.get("/opportunities/999").status_code == 404
    assert client.get("/people/999/journey").status_code == 404
    status_entrega = {"object": "whatsapp_business_account",
                      "entry": [{"id": "WABA_1", "changes": [{"field": "messages", "value": {"statuses": []}}]}]}
    assert client.post("/events/whatsapp", json=status_entrega).json() == {"status": "ignorado"}


def test_c4_evento_duplicado_sem_efeito(client):
    first = form(client, "C1_form_1001")
    first_wa = whatsapp(client, "C2a_whatsapp_qr_cps")
    tables = ("inbound_event", "person", "person_identifier", "opportunity", "touchpoint", "handoff", "consent",
              "audit_log")
    before = {t: count(client, t) for t in tables}

    again = form(client, "C1_form_1001")
    again_wa = whatsapp(client, "C2a_whatsapp_qr_cps")
    assert again == {"status": "duplicado", "event_id": first["event_id"]}
    assert again_wa == {"status": "duplicado", "event_id": first_wa["event_id"]}
    assert {t: count(client, t) for t in tables} == before
    assert client.get("/quality/report").json()["eventos"]["duplicatas_recebidas"] == 2


def test_duplicado_payload_diferente_registra_conflito(client):
    first = form(client, "C1_form_1001")
    r = form(client, "C1_form_1001", phone="(11) 91111-2222")  # mesmo submission_id, conteúdo diferente
    assert r == {"status": "conflito", "event_id": first["event_id"]}

    conn = client.app.state.conn
    stored = conn.execute("SELECT payload FROM inbound_event WHERE id = ?", (first["event_id"],)).fetchone()[0]
    assert json.loads(stored)["phone"] == "(11) 98765-4321"  # recibo original não foi sobrescrito
    assert count(client, "touchpoint") == 1 and count(client, "person_identifier") == 2
    assert client.get("/quality/report").json()["issues_abertas"] == {"evento_conflitante": 1}


def test_c5_venda_erp_atualiza_oportunidade(client):
    lead = form(client, "C1_form_1001")
    venda = ev("venda_c1", crm_opportunity_id=lead["opportunity_id"])
    r = client.post("/events/erp/sale", json=venda).json()
    assert (r["status"], r["opportunity_id"], r["person_id"]) == ("processado", lead["opportunity_id"], lead["person_id"])

    opp = client.get(f"/opportunities/{lead['opportunity_id']}").json()
    assert opp["status"] == "ganha"
    assert opp["vendas"] == [{"erp_sale_id": "ERP-2026-5001", "amount_cents": 349000,
                              "confirmed_at": "2026-10-25T13:00:00+00:00"}]
    assert opp["primeiro_toque"]["event_id"] == lead["event_id"]  # ligação com a jornada preservada

    assert client.post("/events/erp/sale", json=venda).json()["status"] == "duplicado"
    assert count(client, "erp_sale") == 1

    # oportunidade ganha não reabre: novo interesse no mesmo produto vira oportunidade nova
    volta = form(client, "C1_form_1001", submission_id="form-1099", submitted_at="2026-11-02T09:00:00-03:00")
    assert volta["person_id"] == lead["person_id"] and volta["opportunity_id"] != lead["opportunity_id"]


def test_venda_sem_oportunidade_quarentena(client):
    r = client.post("/events/erp/sale", json=ev("venda_orfa")).json()
    assert r["status"] == "quarentena"
    assert all(count(client, t) == 0 for t in ("person", "touchpoint", "opportunity", "erp_sale"))
    status = client.app.state.conn.execute("SELECT status FROM inbound_event WHERE id = ?", (r["event_id"],)).fetchone()
    assert status[0] == "quarentena"
    sem_id = client.post("/events/erp/sale", json=ev("venda_orfa", erp_sale_id="ERP-2026-5009", crm_opportunity_id=None))
    assert sem_id.json()["status"] == "quarentena"
    report = client.get("/quality/report").json()
    assert report["issues_abertas"] == {"venda_sem_oportunidade": 2}
    assert report["eventos"]["quarentena"] == 2


def test_falha_lp_sem_utm_detectada(client):
    form(client, "C1_form_1001")  # mesma LP paga, com UTM
    falha = form(client, "falha_form_1003_sem_utm")  # chegou por encurtador, sem parâmetros
    assert (falha["status"], falha["queue"]) == ("processado", "comercial-sp")  # lead aceito e encaminhado
    assert (falha["origin_type"], falha["source_channel"]) == ("desconhecida", None)  # não vira 'meta'

    issue = client.app.state.conn.execute("SELECT kind, entry_point, detail FROM tracking_issue").fetchone()
    assert (issue["kind"], issue["entry_point"], json.loads(issue["detail"])) == (
        "parametros_perdidos", "lp-sp-micro-01", {"referrer_host": "bit.ly"})
    assert client.get("/quality/report").json()["pontos_de_entrada"] == [
        {"entry_point": "lp-sp-micro-01", "total": 2, "desconhecida": 1, "com_problema": 1, "taxa_problema": 0.5,
         "liberado": False}]


def test_lp_sem_utm_com_como_conheceu_nao_libera(client):
    r = form(client, "falha_form_1003_sem_utm", how_heard="instagram")
    assert r["origin_type"] == "declarada"
    # "como conheceu" preenchido não esconde a perda: o detector olha a falta de parâmetro, não o tipo de origem
    report = client.get("/quality/report").json()
    assert report["issues_abertas"] == {"parametros_perdidos": 1}
    assert report["pontos_de_entrada"] == [
        {"entry_point": "lp-sp-micro-01", "total": 1, "desconhecida": 0, "com_problema": 1, "taxa_problema": 1.0,
         "liberado": False}]


def test_relatorio_conta_leads_nao_mensagens(client):
    whatsapp(client, "C3_ana_volta_por_anuncio_ctwa")
    whatsapp(client, "C3b_ana_mesmo_anuncio_de_novo")  # mesma pessoa e oportunidade: 2 mensagens, 1 lead
    whatsapp(client, "C2b_whatsapp_direto")
    report = client.get("/quality/report").json()
    assert report["origem_por_canal"] == {"desconhecida": 1, "observada:meta_ctwa": 1}
    assert report["pontos_de_entrada"] == [
        {"entry_point": "(sem ponto de entrada)", "total": 2, "desconhecida": 1, "com_problema": 1,
         "taxa_problema": 0.5, "liberado": None}]


def test_anuncio_fora_do_catalogo_vai_para_triagem(client):
    c1 = form(client, "C1_form_1001")
    anuncio = ev("C3_ana_volta_por_anuncio_ctwa")
    anuncio["entry"][0]["changes"][0]["value"]["messages"][0]["referral"]["source_id"] = "120219999999999"
    r = client.post("/events/whatsapp", json=anuncio).json()
    # ad_id é evidência, então segue observada; mas sem campanha conhecida não herda a oportunidade aberta da LP
    assert (r["origin_type"], r["source_channel"], r["queue"]) == ("observada", "meta_ctwa", "triagem-bot")
    assert r["opportunity_id"] != c1["opportunity_id"]
    assert client.get("/quality/report").json()["issues_abertas"] == {"anuncio_desconhecido": 1}


@pytest.mark.parametrize("param, channel", [("gclid", "google"), ("gbraid", "google"), ("wbraid", "google"),
                                            ("fbclid", "meta")])
def test_click_id_da_url(client, param, channel):
    r = form(client, "declarada_form_1004", page_url=f"https://clinic.exemplo/contato?{param}=X1")
    assert (r["origin_type"], r["source_channel"]) == ("observada", channel)
    t = client.get(f"/people/{r['person_id']}/journey").json()["toques"][0]
    assert (t["click_id_type"], t["click_id"]) == (param, "X1")


def test_declarada_nao_vira_observada(client):
    r = form(client, "declarada_form_1004")
    assert (r["origin_type"], r["source_channel"], r["queue"]) == ("declarada", None, "comercial-rj")
    t = client.get(f"/people/{r['person_id']}/journey").json()["toques"][0]
    assert (t["declared"], t["utm_source"], t["entry_point"]) == ("instagram", None, "site-online-contato-01")
    report = client.get("/quality/report").json()
    assert report["origem_por_canal"] == {"declarada:instagram": 1}
    assert report["issues_abertas"] == {}  # /contato não exige parâmetros


def test_identificadores_de_pessoas_diferentes_nao_fundem(client):
    ana = form(client, "C1_form_1001")
    form(client, "falha_form_1003_sem_utm")
    # e-mail do Diego com o telefone da Ana: usa a pessoa do telefone e abre pendência, sem fundir
    mix = form(client, "falha_form_1003_sem_utm", submission_id="form-1007", phone="(11) 98765-4321")
    assert mix["person_id"] == ana["person_id"]
    assert count(client, "person") == 2
    assert client.get("/quality/report").json()["issues_abertas"]["identidade_conflitante"] == 1


def test_mensagem_sem_produto_continua_oportunidade_aberta(client):
    qr = whatsapp(client, "C2a_whatsapp_qr_cps")
    seguinte = ev("C2a_whatsapp_qr_cps")
    seguinte["entry"][0]["changes"][0]["value"]["messages"][0] |= {
        "id": "wamid.QR002", "timestamp": "1792508400", "text": {"body": "obrigada!"}}
    r = client.post("/events/whatsapp", json=seguinte).json()
    # "obrigada" não é interesse novo: segue na oportunidade da CPS, sem oportunidade 'a_definir' nem triagem
    assert (r["opportunity_id"], r["queue"], r["origin_type"]) == (qr["opportunity_id"], "comercial-cps", "desconhecida")
    assert count(client, "opportunity") == 1 and count(client, "handoff") == 1


def test_handoff_timeout_fica_incerto(client):
    conn = client.app.state.conn
    form(client, "C1_form_1001")

    def timeout(handoff):
        raise TimeoutError

    db.dispatch_handoffs(conn, timeout)
    assert conn.execute("SELECT status FROM handoff").fetchone()[0] == "incerto"

    whatsapp(client, "C2a_whatsapp_qr_cps")
    sent = []
    db.dispatch_handoffs(conn, sent.append)
    assert [h["queue"] for h in sent] == ["comercial-cps"]  # o incerto não foi reenviado às cegas
    assert [r[0] for r in conn.execute("SELECT status FROM handoff ORDER BY id")] == ["incerto", "enviado"]


def test_venda_em_quarentena_reprocessada(client):
    orfa = client.post("/events/erp/sale", json=ev("venda_orfa")).json()  # oportunidade 9999 não existe
    assert orfa["status"] == "quarentena"
    lead = form(client, "C1_form_1001")  # a oportunidade certa: micropigmentacao/sp
    corrigida = ev("venda_orfa", crm_opportunity_id=lead["opportunity_id"])  # ERP reenvia com o id corrigido
    r = client.post("/events/erp/sale", json=corrigida).json()
    assert (r["status"], r["event_id"], r["opportunity_id"]) == ("processado", orfa["event_id"], lead["opportunity_id"])

    conn = client.app.state.conn
    assert count(client, "erp_sale") == 1
    assert client.get(f"/opportunities/{lead['opportunity_id']}").json()["status"] == "ganha"
    assert conn.execute("SELECT status FROM inbound_event WHERE id = ?", (orfa["event_id"],)).fetchone()[0] == "processado"
    # nada tinha sido aplicado: payload novo não é conflito, e a pendência fecha
    assert [tuple(r) for r in conn.execute("SELECT kind, status FROM tracking_issue")] == [
        ("venda_sem_oportunidade", "resolvida")]
    assert conn.execute("SELECT COUNT(*) FROM audit_log WHERE action = 'venda.reprocessada'").fetchone()[0] == 1
    assert client.post("/events/erp/sale", json=corrigida).json()["status"] == "duplicado"


def test_venda_divergente_quarentena(client):
    lead = form(client, "C1_form_1001")  # micropigmentacao/sp
    venda = ev("venda_divergente", crm_opportunity_id=lead["opportunity_id"])  # harmonizacao/rj
    assert client.post("/events/erp/sale", json=venda).json()["status"] == "quarentena"
    assert client.get(f"/opportunities/{lead['opportunity_id']}").json()["status"] == "aberta"  # não fecha a errada
    assert count(client, "erp_sale") == 0
    assert client.get("/quality/report").json()["issues_abertas"] == {"venda_divergente": 1}


def test_recibo_imutavel(client):
    form(client, "C1_form_1001")
    conn = client.app.state.conn
    for change in ("payload = '{}'", "payload_hash = 'x'", "dedup_key = 'outro'", "source = 'erp'"):
        with pytest.raises(sqlite3.IntegrityError, match="recibo imutavel"):
            conn.execute(f"UPDATE inbound_event SET {change}")
    conn.execute("UPDATE inbound_event SET duplicates = duplicates + 1")  # contador pode mudar


def test_consentimento_registrado_na_jornada(client):
    ana = form(client, "C1_form_1001")  # consent_marketing true
    whatsapp(client, "C3_ana_volta_por_anuncio_ctwa")  # WhatsApp não traz consentimento: nada gravado
    form(client, "C1_form_1001", submission_id="form-1010", submitted_at="2026-10-24T09:00:00-03:00",
         consent_marketing=False)  # revogou no envio seguinte
    form(client, "declarada_form_1004", consent_marketing=None)  # campo ausente não vira "não"
    jornada = client.get(f"/people/{ana['person_id']}/journey").json()
    assert [(c["purpose"], c["granted"], c["at"]) for c in jornada["consentimentos"]] == [
        ("marketing", True, "2026-10-20T17:03:00+00:00"), ("marketing", False, "2026-10-24T12:00:00+00:00")]
    assert count(client, "consent") == 2
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        client.app.state.conn.execute("UPDATE consent SET granted = 1")
