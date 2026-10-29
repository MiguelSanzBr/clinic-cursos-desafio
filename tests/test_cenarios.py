import copy
import json
import re
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

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


def wa(name, message=(), contact=()):
    """Evento de WhatsApp com campos trocados na primeira mensagem e no primeiro contato."""
    payload = ev(name)
    value = payload["entry"][0]["changes"][0]["value"]
    value["messages"][0] |= dict(message)
    value["contacts"][0] |= dict(contact)
    return payload


def count(client, table):
    return client.app.state.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def test_c1_origem_campanha_preservada_ate_venda(client):
    lead = form(client, "C1_form_1001")
    assert (lead["status"], lead["origin_type"], lead["source_channel"], lead["queue"]) == (
        "processado", "observada", "ig/paid_social", "comercial-sp")

    venda = client.post("/events/erp/sale", json=ev("venda_c1", crm_opportunity_id=lead["opportunity_id"])).json()
    assert venda["status"] == "processado"

    opp = client.get(f"/opportunities/{lead['opportunity_id']}").json()
    assert opp["status"] == "ganha"
    assert opp["vendas"][0]["erp_sale_id"] == "ERP-2026-5001"
    first = opp["primeiro_toque"]
    assert (first["utm_campaign"], first["utm_id"], first["utm_content"], first["click_id_type"],
            first["entry_point"]) == ("sp-micropigmentacao-captacao", "120200000000099", "video-01", "fbclid",
                                      "lp-sp-micro-01")
    assert not any("@" in str(v) for v in first.values())  # toque sem dado pessoal
    assert client.get("/quality/report").json()["vendas"]["por_origem_atribuida"] == {"observada:ig/paid_social": 1}


def test_c2_qr_unidade_distinto_de_whatsapp_direto(client):
    qr = whatsapp(client, "C2a_whatsapp_qr_cps")
    direto = whatsapp(client, "C2b_whatsapp_direto")
    assert (qr["origin_type"], qr["source_channel"], qr["queue"]) == ("observada", "offline/qr", "agenda-cps")
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
    assert opp1["primeiro_toque"]["utm_campaign"] == "sp-micropigmentacao-captacao"  # 1º toque intacto
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


def test_formulario_sem_identificador_fica_em_quarentena(client):
    r = form(client, "C1_form_1001", email="sem-arroba", phone="123")
    assert (r["status"], r["motivo"]) == ("quarentena", "payload_invalido")
    assert count(client, "inbound_event") == 1 and count(client, "person") == 0  # recibo gravado, sem pessoa
    conn = client.app.state.conn
    assert json.loads(conn.execute("SELECT detail FROM tracking_issue").fetchone()[0]) == {"campos": ["email", "phone"]}
    corrigido = form(client, "C1_form_1001")  # reenvio com o mesmo submission_id e dados certos: reprocessado
    assert (corrigido["status"], corrigido["event_id"]) == ("processado", r["event_id"])
    assert [tuple(i) for i in conn.execute("SELECT kind, status FROM tracking_issue")] == [("payload_invalido", "resolvida")]


def test_so_sem_chave_de_idempotencia_e_422(client):
    sem_wamid = ev("C2b_whatsapp_direto")
    del sem_wamid["entry"][0]["changes"][0]["value"]["messages"][0]["id"]
    assert client.post("/events/form", json=ev("C1_form_1001", submission_id=None)).status_code == 422
    assert client.post("/events/erp/sale", json=ev("venda_orfa", erp_sale_id="")).status_code == 422
    # no lote do WhatsApp, a mensagem sem wamid vira pendência: um 422 faria a Meta reenviar o lote para sempre
    assert client.post("/events/whatsapp", json=sem_wamid).json() == {"status": "ignorado", "motivo": "payload_invalido"}
    assert count(client, "inbound_event") == 0
    # com a chave, campo ilegível não rejeita: a venda fica em quarentena com a pendência e fora da receita
    r = client.post("/events/erp/sale", json=ev("venda_orfa", amount_cents="muito")).json()
    assert (r["status"], r["motivo"]) == ("quarentena", "payload_invalido")
    assert client.get("/quality/report").json()["receita_em_quarentena_cents"] == 0


def test_campo_invalido_nao_rejeita_lead(client):
    ana = form(client, "C1_form_1001", how_heard="Instagram", consent_marketing="sim")
    jornada = client.get(f"/people/{ana['person_id']}/journey").json()
    assert jornada["toques"][0]["declared"] == "instagram"  # maiúscula normalizada
    assert [c["purpose"] for c in jornada["consentimentos"]] == ["ads"]  # "sim" não vira consentimento de marketing
    diego = form(client, "falha_form_1003_sem_utm", email=None, phone="(011) 98765-0003")  # 0 de discagem
    wa = ev("C2b_whatsapp_direto")
    wa["entry"][0]["changes"][0]["value"]["messages"][0]["from"] = "351912345678"  # wa_id de Portugal
    estrangeiro = client.post("/events/whatsapp", json=wa).json()
    assert [r["status"] for r in (ana, diego, estrangeiro)] == ["processado"] * 3
    conn = client.app.state.conn
    phones = {r[0] for r in conn.execute("SELECT value FROM person_identifier WHERE kind = 'phone'")}
    assert {"+5511987650003", "+351912345678"} <= phones
    detalhes = [json.loads(d) for (d,) in conn.execute("SELECT detail FROM tracking_issue WHERE kind = 'payload_invalido'")]
    assert detalhes == [{"campos": ["consent_marketing"]}]  # só o nome do campo, sem o valor


def test_telefone_numerico_no_formulario(client):
    r = form(client, "C1_form_1001", phone=11955550000, email=None)  # o formulário mandou número, não texto
    assert r["status"] == "processado"  # antes ia inteiro para a quarentena
    phone = client.app.state.conn.execute("SELECT value FROM person_identifier WHERE kind = 'phone'").fetchone()[0]
    assert phone == "+5511955550000"
    assert client.get("/quality/report").json()["issues_abertas"] == {}


@pytest.mark.parametrize("rota, payload, campo, status", [
    ("/events/form", ev("C1_form_1001", page_url="http://[::1"), "page_url", "processado"),
    ("/events/form", ev("falha_form_1003_sem_utm", referrer="https://[x", phone=None, email=None), "referrer",
     "quarentena"),
    ("/events/whatsapp", wa("C2a_whatsapp_qr_cps", message={"text": {"body": 123}}), "text", "processado"),
    ("/events/whatsapp", wa("C2a_whatsapp_qr_cps", contact={"profile": "Bruna"}), "profile", "processado"),
    ("/events/whatsapp", wa("C2a_whatsapp_qr_cps", message={"referral": {"source_type": "ad", "source_id": []}}),
     "referral", "processado"),
    ("/events/erp/sale", ev("venda_c1", crm_opportunity_id=2**64), "crm_opportunity_id", "quarentena"),
], ids=["page_url", "referrer_sem_identificador", "texto_nao_string", "perfil_string", "referral_lista",
        "id_maior_que_sqlite"])
def test_campo_opcional_ilegivel_vira_pendencia(client, rota, payload, campo, status):
    r = client.post(rota, json=payload)
    assert (r.status_code, r.json()["status"]) == (200, status)
    assert count(client, "inbound_event") == 1  # recibo gravado: o lead não se perde
    detalhes = client.app.state.conn.execute("SELECT detail FROM tracking_issue WHERE kind = 'payload_invalido'")
    assert any(campo in json.loads(d)["campos"] for (d,) in detalhes)


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
    detail = json.loads(conn.execute("SELECT detail FROM tracking_issue").fetchone()[0])
    original = conn.execute("SELECT payload_hash FROM inbound_event").fetchone()[0]
    assert detail["payload_hash_novo"] not in (None, original)  # dá para saber que o conteúdo mudou, sem copiá-lo


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
    volta = form(client, "C1_form_1001", submission_id="form-1099", submitted_at="2026-10-27T09:00:00-03:00")
    assert volta["person_id"] == lead["person_id"] and volta["opportunity_id"] != lead["opportunity_id"]


def test_erp_sale_id_numerico_vira_texto(client):
    lead = form(client, "C1_form_1001")
    venda = ev("venda_c1", erp_sale_id=5001, crm_opportunity_id=lead["opportunity_id"])
    assert client.post("/events/erp/sale", json=venda).json()["status"] == "processado"
    assert client.app.state.conn.execute("SELECT erp_sale_id FROM erp_sale").fetchone()[0] == "5001"
    assert client.post("/events/erp/sale", json=venda).json()["status"] == "duplicado"


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
    falha = form(client, "falha_form_1003_sem_utm")  # link do anúncio cadastrado sem parâmetros
    assert (falha["status"], falha["queue"]) == ("processado", "comercial-sp")  # lead aceito e encaminhado
    assert (falha["origin_type"], falha["source_channel"]) == ("desconhecida", None)  # não vira 'meta'

    issue = client.app.state.conn.execute("SELECT kind, entry_point, detail FROM tracking_issue").fetchone()
    assert (issue["kind"], issue["entry_point"], json.loads(issue["detail"])) == (
        "parametros_perdidos", "lp-sp-micro-01", {"referrer_host": "l.instagram.com"})
    assert client.get("/quality/report").json()["pontos_de_entrada"] == [
        {"entry_point": "lp-sp-micro-01", "total": 2, "desconhecida": 1, "com_problema": 1, "taxa_problema": 0.5,
         "status": "bloqueado"}]


def test_lp_sem_utm_com_como_conheceu_nao_libera(client):
    r = form(client, "falha_form_1003_sem_utm", how_heard="instagram")
    assert r["origin_type"] == "declarada"
    # "como conheceu" preenchido não esconde a perda: o detector olha a falta de parâmetro, não o tipo de origem
    report = client.get("/quality/report").json()
    assert report["issues_abertas"] == {"parametros_perdidos": 1}
    assert report["pontos_de_entrada"] == [
        {"entry_point": "lp-sp-micro-01", "total": 1, "desconhecida": 0, "com_problema": 1, "taxa_problema": 1.0,
         "status": "bloqueado"}]


def test_relatorio_conta_leads_nao_mensagens(client):
    whatsapp(client, "C3_ana_volta_por_anuncio_ctwa")
    whatsapp(client, "C3b_ana_mesmo_anuncio_de_novo")  # mesma pessoa e oportunidade: 2 mensagens, 1 lead
    whatsapp(client, "C2b_whatsapp_direto")
    report = client.get("/quality/report").json()
    assert report["origem_por_canal"] == {"desconhecida": 1, "observada:meta_ctwa": 1}
    assert report["pontos_de_entrada"] == [
        {"entry_point": "(sem ponto de entrada)", "total": 1, "desconhecida": 1, "com_problema": 1,
         "taxa_problema": 1.0, "status": None},
        {"entry_point": "ctwa-rj-harmo-01", "total": 1, "desconhecida": 0, "com_problema": 0,
         "taxa_problema": 0.0, "status": "amostra_insuficiente"}]


def test_liberacao_conta_oportunidade_que_passa_pelo_ponto(client):
    direto = whatsapp(client, "C2b_whatsapp_direto")  # Rafa chega pelo WhatsApp direto
    rafa = {"phone": "(21) 97777-6666", "email": "rafa@exemplo.com"}
    lp = form(client, "falha_form_1003_sem_utm", submitted_at="2026-10-22T10:00:00-03:00", **rafa)  # LP sem UTM
    form(client, "falha_form_1003_sem_utm", submission_id="form-1051", submitted_at="2026-10-23T10:00:00-03:00", **rafa)
    assert lp["opportunity_id"] == direto["opportunity_id"]
    pontos = {p["entry_point"]: (p["total"], p["com_problema"], p["status"])
              for p in client.get("/quality/report").json()["pontos_de_entrada"]}
    # a LP conta a oportunidade pelo 1º toque dela na LP (o do link quebrado); dois envios pela LP são um lead
    assert pontos == {"(sem ponto de entrada)": (1, 1, None), "lp-sp-micro-01": (1, 1, "bloqueado")}


def anuncio_desconhecido(wamid="wamid.CTWA001", numero="5511987654321"):
    return wa("C3_ana_volta_por_anuncio_ctwa", contact={"wa_id": numero}, message={
        "id": wamid, "from": numero, "referral": {"source_type": "ad", "source_id": "120219999999999"}})


def test_anuncio_fora_do_catalogo_entra_na_oportunidade_aberta(client):
    c1 = form(client, "C1_form_1001")
    r = client.post("/events/whatsapp", json=anuncio_desconhecido()).json()
    # ad_id é evidência (observada), mas sem produto nem unidade: segue a conversa aberta, sem 'a_definir' em paralelo
    assert (r["origin_type"], r["source_channel"], r["queue"]) == ("observada", "meta_ctwa", "comercial-sp")
    assert r["opportunity_id"] == c1["opportunity_id"]
    assert count(client, "opportunity") == 1 and count(client, "handoff") == 1
    sem_aberta = client.post("/events/whatsapp", json=anuncio_desconhecido("wamid.CTWA009", "5521900001111")).json()
    assert sem_aberta["queue"] == "triagem-bot"  # quem não tem oportunidade aberta vai para a triagem
    assert client.get("/quality/report").json()["issues_abertas"] == {"anuncio_desconhecido": 2}


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


def test_nao_perguntei_conta_como_desconhecida(client):
    r = form(client, "declarada_form_1004", how_heard="nao_perguntei")  # a atendente não perguntou
    assert (r["origin_type"], r["source_channel"]) == ("desconhecida", None)
    t = client.get(f"/people/{r['person_id']}/journey").json()["toques"][0]
    assert t["declared"] == "nao_perguntei"  # fica no toque para medir quantas vezes aparece
    report = client.get("/quality/report").json()
    assert report["origem_por_canal"] == {"desconhecida": 1}
    assert report["pontos_de_entrada"] == [
        {"entry_point": "site-online-contato-01", "total": 1, "desconhecida": 1, "com_problema": 1,
         "taxa_problema": 1.0, "status": "bloqueado"}]


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
    assert (r["opportunity_id"], r["queue"], r["origin_type"]) == (qr["opportunity_id"], "agenda-cps", "desconhecida")
    assert count(client, "opportunity") == 1 and count(client, "handoff") == 1


def test_aluna_sem_produto_vai_para_atendimento(client):
    ana = form(client, "C1_form_1001")
    client.post("/events/erp/sale", json=ev("venda_c1", crm_opportunity_id=ana["opportunity_id"]))
    for i, texto in enumerate(("qual a sala amanhã?", "obrigada!")):
        msg = wa("C2b_whatsapp_direto", contact={"wa_id": "5511987654321"},
                 message={"id": f"wamid.ALUNA0{i}", "from": "5511987654321", "text": {"body": texto}})
        r = client.post("/events/whatsapp", json=msg).json()
        # já comprou: não abre oportunidade nem vai para a triagem; o toque fica na oportunidade ganha
        assert (r["opportunity_id"], r["queue"]) == (ana["opportunity_id"], "atendimento-aluna")
    assert count(client, "opportunity") == 1
    opp = client.get(f"/opportunities/{ana['opportunity_id']}").json()
    assert [h["queue"] for h in opp["encaminhamentos"]] == ["comercial-sp", "atendimento-aluna"]
    report = client.get("/quality/report").json()
    assert report["origem_por_canal"] == {"observada:ig/paid_social": 1}  # não infla lead sem origem
    assert [p["entry_point"] for p in report["pontos_de_entrada"]] == ["lp-sp-micro-01"]


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
    assert [h["queue"] for h in sent] == ["agenda-cps"]  # o incerto não foi reenviado às cegas
    assert [r[0] for r in conn.execute("SELECT status FROM handoff ORDER BY id")] == ["incerto", "enviado"]


def test_despachos_em_paralelo_nao_repetem_envio(client):
    form(client, "C1_form_1001")
    whatsapp(client, "C2a_whatsapp_qr_cps")
    whatsapp(client, "C2b_whatsapp_direto")
    conn, sent = client.app.state.conn, []

    def send(handoff):
        sent.append(handoff["id"])
        time.sleep(0.05)  # envio lento: a outra rodada lê a outbox enquanto esta ainda envia

    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda _: db.dispatch_handoffs(conn, send), range(2)))
    assert sorted(sent) == [1, 2, 3]
    assert [r[0] for r in conn.execute("SELECT status FROM handoff")] == ["enviado"] * 3


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
        ("marketing", True, "2026-10-20T17:03:00+00:00"), ("ads", True, "2026-10-20T17:03:00+00:00"),
        ("marketing", False, "2026-10-24T12:00:00+00:00"), ("ads", True, "2026-10-24T12:00:00+00:00")]
    assert count(client, "consent") == 4
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        client.app.state.conn.execute("UPDATE consent SET granted = 1")


def lead_sintetico(client, i, how_heard="instagram"):
    """Lead em /contato com telefone e e-mail próprios, um a cada 6 h. Sem "como conheceu" fica desconhecida."""
    quando = (datetime(2026, 1, 1, tzinfo=UTC) + timedelta(hours=6 * i)).isoformat()  # 1000 leads cabem no passado
    return form(client, "declarada_form_1004", submission_id=f"sint-{i}", email=f"sint{i}@exemplo.com",
                phone=f"(21) 9{i:04d}-{i:04d}", how_heard=how_heard, submitted_at=quando)


def test_concorrencia_nao_perde_lead(client):
    with ThreadPoolExecutor(max_workers=50) as pool:
        results = list(pool.map(lambda i: lead_sintetico(client, i), range(50)))
    assert [r["status"] for r in results] == ["processado"] * 50
    sem_toque = "SELECT COUNT(*) FROM inbound_event WHERE id NOT IN (SELECT event_id FROM touchpoint)"
    assert client.app.state.conn.execute(sem_toque).fetchone()[0] == 0  # recibo sem toque é lead perdido
    assert count(client, "touchpoint") == 50


def test_leitura_durante_escrita_nao_quebra(client):
    escritas, leituras = [], []
    with ThreadPoolExecutor(max_workers=64) as pool:
        for i in range(100):
            escritas.append(pool.submit(lead_sintetico, client, i))
            leituras.append(pool.submit(client.get, "/quality/report"))
    assert {f.result()["status"] for f in escritas} == {"processado"}
    assert {f.result().status_code for f in leituras} == {200}


def test_liberacao_olha_os_ultimos_100_leads(client):
    for i in range(1000):  # 5 problemas antigos; depois de corrigido, os 100 mais recentes chegam limpos
        lead_sintetico(client, i, how_heard=None if i < 5 else "instagram")
    ponto = client.get("/quality/report").json()["pontos_de_entrada"][0]
    assert (ponto["total"], ponto["com_problema"], ponto["status"]) == (1000, 5, "liberado")


def test_liberacao_em_tres_estados(client):
    form(client, "C1_form_1001")
    form(client, "falha_form_1003_sem_utm")  # LP paga: 1 de 2 leads com problema
    whatsapp(client, "C2a_whatsapp_qr_cps")  # QR: 1 lead sem problema
    for i in range(30):
        lead_sintetico(client, i)

    def status():
        return {p["entry_point"]: p["status"] for p in client.get("/quality/report").json()["pontos_de_entrada"]}

    assert status() == {"lp-sp-micro-01": "bloqueado", "qr-cps-recepcao-01": "amostra_insuficiente",
                        "site-online-contato-01": "liberado"}
    # 50 leads com 2 problemas: a tabela tolera 1 em 50, mas liberado só volta a bloquear com 7 em 50 ou 5 seguidos
    for i in range(30, 48):
        lead_sintetico(client, i)
    for i in range(48, 50):
        lead_sintetico(client, i, how_heard=None)
    assert status()["site-online-contato-01"] == "liberado"


def test_receita_sem_origem(client):
    ana = form(client, "C1_form_1001")
    diego = form(client, "falha_form_1003_sem_utm")
    client.post("/events/erp/sale", json=ev("venda_c1", crm_opportunity_id=ana["opportunity_id"]))
    client.post("/events/erp/sale", json=ev("venda_orfa", crm_opportunity_id=diego["opportunity_id"]))
    client.post("/events/erp/sale", json=ev("venda_divergente", crm_opportunity_id=diego["opportunity_id"]))  # quarentena
    report = client.get("/quality/report").json()
    assert report["vendas"]["valor_cents"] == 698000
    assert report["receita_em_quarentena_cents"] == 420000
    # só a venda do Diego (chegou sem UTM): a da Ana é observada e a em quarentena fica no campo dela
    assert report["receita_sem_origem_cents"] == 349000


def test_oi_no_whatsapp_direto_nao_rouba_a_origem(client):
    direto = whatsapp(client, "C2b_whatsapp_direto")  # "oi" sem código: 1º toque desconhecida
    form(client, "consentimento_form_1005", phone="(21) 97777-6666", consent_ads=True)  # depois, /contato com gclid
    client.post("/events/erp/sale", json=ev("venda_c1", crm_opportunity_id=direto["opportunity_id"]))
    report = client.get("/quality/report").json()
    # a venda e o lead ficam com o 1º toque observado, não com o "oi"
    assert report["origem_por_canal"] == {"observada:google": 1}
    assert report["vendas"]["por_origem_atribuida"] == {"observada:google": 1}
    assert report["receita_sem_origem_cents"] == 0
    assert [(c["platform"], c["status"]) for c in conversoes(client)] == [("google", "pendente")]


def test_whatsapp_texto_nao_gravado(client):
    qr = whatsapp(client, "C2a_whatsapp_qr_cps")
    stored = client.app.state.conn.execute("SELECT payload FROM inbound_event WHERE id = ?",
                                           (qr["event_id"],)).fetchone()[0]
    assert "paciente modelo" not in stored  # o texto da conversa não fica no recibo
    assert "Bruna" not in stored  # nem o nome do perfil, que vai só para person.name
    assert client.get(f"/people/{qr['person_id']}/journey").json()["nome"] == "Bruna"
    assert json.loads(stored) == {"wamid": "wamid.QR001", "from": "5519991112222", "timestamp": 1792504800,
                                  "referral": None, "entry_point": "qr-cps-recepcao-01"}
    # dedup segue pelo hash do payload original: reenvio igual é duplicado, texto diferente é conflito
    assert whatsapp(client, "C2a_whatsapp_qr_cps")["status"] == "duplicado"
    outro = ev("C2a_whatsapp_qr_cps")
    outro["entry"][0]["changes"][0]["value"]["messages"][0]["text"]["body"] = "mudei de ideia"
    assert client.post("/events/whatsapp", json=outro).json()["status"] == "conflito"


def conversoes(client):
    return [dict(r) for r in client.app.state.conn.execute(
        "SELECT erp_sale_id, platform, click_id_type, click_id, event_id, status FROM platform_conversion ORDER BY id")]


def test_venda_gera_conversao_para_plataforma(client):
    diego = form(client, "falha_form_1003_sem_utm")  # outro lead da mesma LP chega sem UTM: a LP fica bloqueada
    ana = form(client, "C1_form_1001")  # UTM completa e fbclid
    client.post("/events/erp/sale", json=ev("venda_c1", crm_opportunity_id=ana["opportunity_id"]))
    # a conversão é do lead, não do ponto: a falha do Diego não segura a venda da Ana (a Meta só aceita até 7 dias)
    assert conversoes(client) == [{"erp_sale_id": "ERP-2026-5001", "platform": "meta", "click_id_type": "fbclid",
                                   "click_id": "IwAR0abc", "event_id": "ERP-2026-5001", "status": "pendente"}]
    so_fbclid = form(client, "C1_form_1001", submission_id="form-1020", phone="(11) 91234-0020", email=None,
                     page_url="https://clinic.exemplo/lp/micro-sp?fbclid=F1")
    client.post("/events/erp/sale", json=ev("venda_sem_consentimento", crm_opportunity_id=so_fbclid["opportunity_id"]))
    # só o fbclid não prova a campanha para nós, mas é o clique que a Meta casa: a conversão sai
    assert conversoes(client)[1] == {"erp_sale_id": "ERP-2026-5004", "platform": "meta", "click_id_type": "fbclid",
                                     "click_id": "F1", "event_id": "ERP-2026-5004", "status": "pendente"}
    client.post("/events/erp/sale", json=ev("venda_orfa", crm_opportunity_id=diego["opportunity_id"]))
    assert len(conversoes(client)) == 2  # sem click id: não há o que devolver à plataforma


def test_paciente_modelo_nunca_vai_para_plataforma(client):
    lead = form(client, "C1_form_1001", product="paciente_modelo", unit="cps")  # veio de anúncio, produto sensível
    venda = ev("venda_c1", crm_opportunity_id=lead["opportunity_id"], product="paciente_modelo", unit="cps")
    assert client.post("/events/erp/sale", json=venda).json()["status"] == "processado"
    assert conversoes(client) == [{"erp_sale_id": "ERP-2026-5001", "platform": "meta", "click_id_type": None,
                                   "click_id": None, "event_id": "ERP-2026-5001", "status": "bloqueado_sensivel"}]


@pytest.mark.parametrize("historico", [[False], [None], [True, False]], ids=["negado", "ausente", "revogado"])
def test_conversao_sem_consentimento_bloqueada(client, historico):
    # fbclid na URL; vale o último registro de consent_ads. consent_marketing (mensagens) verdadeiro não basta
    for i, consent in enumerate(historico):
        lead = form(client, "C1_form_1001", submission_id=f"form-20{i}", submitted_at=f"2026-10-2{i}T09:00:00-03:00",
                    consent_ads=consent)
    client.post("/events/erp/sale", json=ev("venda_c1", crm_opportunity_id=lead["opportunity_id"]))
    assert conversoes(client) == [{"erp_sale_id": "ERP-2026-5001", "platform": "meta", "click_id_type": None,
                                   "click_id": None, "event_id": "ERP-2026-5001", "status": "bloqueado_consentimento"}]


def test_whatsapp_direto_fecha_venda(client):
    direto = whatsapp(client, "C2b_whatsapp_direto")  # sem código: oportunidade a_definir/desconhecida
    venda = ev("venda_c1", crm_opportunity_id=direto["opportunity_id"])  # micropigmentacao/sp
    sem_produto = {k: v for k, v in venda.items() if k != "product"}
    assert client.post("/events/erp/sale", json=sem_produto).json()["motivo"] == "venda_divergente"  # quarentena
    assert client.post("/events/erp/sale", json=venda).json()["status"] == "processado"  # reenvio corrigido
    opp = client.get(f"/opportunities/{direto['opportunity_id']}").json()
    assert (opp["status"], opp["product"], opp["unit"]) == ("ganha", "micropigmentacao", "sp")
    requalificada = "SELECT COUNT(*) FROM audit_log WHERE action = 'opportunity.requalificada'"
    assert client.app.state.conn.execute(requalificada).fetchone()[0] == 1


def test_utm_incompleta_nao_vira_observada(client):
    lp = form(client, "falha_form_1003_sem_utm",
              page_url="https://clinic.exemplo/lp/micro-sp?utm_campaign=sp-micropigmentacao-captacao")
    assert (lp["origin_type"], lp["source_channel"]) == ("desconhecida", None)
    contato = form(client, "declarada_form_1004", page_url="https://clinic.exemplo/contato?utm_source=ig")
    assert (contato["origin_type"], contato["source_channel"]) == ("declarada", None)  # tem "como conheceu"
    details = client.app.state.conn.execute("SELECT detail FROM tracking_issue WHERE kind = 'utm_fora_do_padrao' ORDER BY id")
    assert [json.loads(d) for (d,) in details] == [{"campos": [], "faltando": ["utm_source", "utm_medium"]},
                                                   {"campos": [], "faltando": ["utm_medium", "utm_campaign"]}]


def test_ctwa_tem_ponto_de_entrada_e_post_nao_e_anuncio(client):
    ctwa = whatsapp(client, "C3_ana_volta_por_anuncio_ctwa")
    first = client.get(f"/opportunities/{ctwa['opportunity_id']}").json()["primeiro_toque"]
    assert (first["entry_point"], first["source_channel"]) == ("ctwa-rj-harmo-01", "meta_ctwa")
    post = ev("C2b_whatsapp_direto")
    post["entry"][0]["changes"][0]["value"]["messages"][0]["referral"] = {
        "source_url": "https://fb.me/p", "source_id": "post-77", "source_type": "post"}
    r = client.post("/events/whatsapp", json=post).json()
    assert (r["origin_type"], r["source_channel"]) == ("observada", "meta/organic_social")
    t = client.get(f"/opportunities/{r['opportunity_id']}").json()["primeiro_toque"]
    assert (t["ad_id"], t["click_id"], t["utm_campaign"]) == (None, None, None)  # post não é campanha paga


def test_atribuicao_pelo_primeiro_toque_observado(client):
    diego = form(client, "falha_form_1003_sem_utm")  # 1º toque sem UTM: desconhecida
    lp = "https://clinic.exemplo/lp/micro-sp?"
    for i, query in enumerate(("gclid=G1", "utm_source=ig&utm_medium=paid_social&utm_campaign=sp-micropigmentacao-captacao")):
        volta = form(client, "falha_form_1003_sem_utm", submission_id=f"form-101{i}",
                     submitted_at=f"2026-10-2{3 + i}T10:00:00-03:00", page_url=lp + query)
        assert volta["opportunity_id"] == diego["opportunity_id"]  # mesma oportunidade, toques observados depois
    client.post("/events/erp/sale", json=ev("venda_orfa", crm_opportunity_id=diego["opportunity_id"]))
    # o 1º observado (google), não o desconhecido de antes nem o ig de depois: sem a prioridade do observado ou com o
    # ORDER BY invertido em attributed_touch, este teste cai
    assert client.get("/quality/report").json()["vendas"]["por_origem_atribuida"] == {"observada:google": 1}


def test_lote_do_whatsapp_processa_cada_mensagem(client):
    lote = ev("C2a_whatsapp_qr_cps")
    value = lote["entry"][0]["changes"][0]["value"]
    direto = ev("C2b_whatsapp_direto")["entry"][0]["changes"][0]["value"]
    value["contacts"] += direto["contacts"]
    value["messages"] += direto["messages"]
    r = client.post("/events/whatsapp", json=lote).json()
    assert [m["status"] for m in r["resultados"]] == ["processado", "processado"]
    nomes = [client.get(f"/people/{m['person_id']}/journey").json()["nome"] for m in r["resultados"]]
    assert nomes == ["Bruna", "Rafa"]  # o nome vem do contato do mesmo wa_id
    again = client.post("/events/whatsapp", json=lote).json()  # reenvio da Meta: cada mensagem pelo seu wamid
    assert [m["status"] for m in again["resultados"]] == ["duplicado", "duplicado"]


def test_mesma_mensagem_envelope_diferente_e_duplicado(client):
    first = whatsapp(client, "C2a_whatsapp_qr_cps")
    segunda_via = ev("C2a_whatsapp_qr_cps")  # a mesma mensagem por outra via (ex.: API do Chatwoot)
    segunda_via["entry"][0]["id"] = "WABA_2"
    value = segunda_via["entry"][0]["changes"][0]["value"]
    value["contacts"][0]["profile"]["name"] = "Bruna Alves"
    value["messages"][0]["timestamp"] = 1792504800  # número em vez de texto
    r = client.post("/events/whatsapp", json=segunda_via).json()
    assert r == {"status": "duplicado", "event_id": first["event_id"]}


def test_venda_fora_do_catalogo_quarentena(client):
    direto = whatsapp(client, "C2b_whatsapp_direto")  # a_definir: sem o catálogo, qualquer produto a qualificaria
    for i, change in enumerate(({"product": "curso_x"}, {"unit": "campinas"})):
        venda = ev("venda_c1", erp_sale_id=f"ERP-2026-60{i}", crm_opportunity_id=direto["opportunity_id"], **change)
        assert client.post("/events/erp/sale", json=venda).json()["motivo"] == "venda_divergente"
    assert client.get(f"/opportunities/{direto['opportunity_id']}").json()["status"] == "aberta"


def test_segunda_venda_em_oportunidade_ganha_quarentena(client):
    ana = form(client, "C1_form_1001")
    client.post("/events/erp/sale", json=ev("venda_c1", crm_opportunity_id=ana["opportunity_id"]))
    outra = ev("venda_c1", erp_sale_id="ERP-2026-5010", crm_opportunity_id=ana["opportunity_id"])
    assert client.post("/events/erp/sale", json=outra).json()["motivo"] == "venda_em_oportunidade_ganha"
    report = client.get("/quality/report").json()
    assert (report["vendas"]["total"], report["vendas"]["valor_cents"]) == (1, 349000)  # a receita não dobra
    assert report["issues_abertas"] == {"venda_em_oportunidade_ganha": 1}


def test_formulario_qualifica_oportunidade_a_definir(client):
    direto = whatsapp(client, "C2b_whatsapp_direto")  # Rafa sem código: a_definir/desconhecida, triagem-bot
    r = form(client, "declarada_form_1004", phone="(21) 97777-6666", email="rafa@exemplo.com")  # harmonizacao/rj
    assert (r["person_id"], r["opportunity_id"], r["queue"]) == (
        direto["person_id"], direto["opportunity_id"], "comercial-rj")
    opp = client.get(f"/opportunities/{direto['opportunity_id']}").json()
    assert (opp["product"], opp["unit"]) == ("harmonizacao", "rj")
    assert [h["queue"] for h in opp["encaminhamentos"]] == ["triagem-bot", "comercial-rj"]
    requalificada = "SELECT COUNT(*) FROM audit_log WHERE action = 'opportunity.requalificada'"
    assert count(client, "opportunity") == 1 and client.app.state.conn.execute(requalificada).fetchone()[0] == 1


def test_unidade_fora_do_catalogo_vai_para_triagem(client):
    lp = form(client, "C1_form_1001", unit="campinas")  # LP de SP: "campinas" não herda "sp"
    contato = form(client, "declarada_form_1004", unit=None)  # /contato é do site institucional: sem unidade
    assert (lp["queue"], contato["queue"]) == ("triagem-bot", "triagem-bot")
    detail = client.app.state.conn.execute("SELECT detail FROM tracking_issue WHERE kind = 'payload_invalido'").fetchone()
    assert json.loads(detail[0]) == {"campos": ["unit"]}


def test_nivel_de_evidencia_e_so_canal_em_lp_paga(client):
    c1 = form(client, "C1_form_1001")  # UTM completa
    ctwa = whatsapp(client, "C3_ana_volta_por_anuncio_ctwa")
    so_fbclid = form(client, "falha_form_1003_sem_utm", page_url="https://clinic.exemplo/lp/micro-sp?fbclid=F1")
    niveis = [client.get(f"/opportunities/{r['opportunity_id']}").json()["primeiro_toque"]["evidence_level"]
              for r in (c1, ctwa, so_fbclid)]
    assert niveis == ["campanha", "anuncio", "canal"]
    issue = client.app.state.conn.execute("SELECT detail FROM tracking_issue WHERE kind = 'parametros_perdidos'").fetchone()
    assert json.loads(issue[0]) == {"referrer_host": "l.instagram.com", "motivo": "so_canal"}
    lp = next(p for p in client.get("/quality/report").json()["pontos_de_entrada"] if p["entry_point"] == "lp-sp-micro-01")
    assert (lp["total"], lp["com_problema"]) == (2, 1)  # só fbclid em LP paga não diz a campanha: conta como problema


def test_oportunidade_parada_ha_90_dias_expira(client):
    velha = form(client, "C1_form_1001", submitted_at="2026-07-20T14:03:00-03:00")
    utm = "?utm_source=google&utm_medium=cpc&utm_campaign=sp-micropigmentacao-captacao&gclid=G9"
    nova = form(client, "C1_form_1001", submission_id="form-1030", submitted_at="2026-10-20T10:00:00-03:00",
                page_url="https://clinic.exemplo/lp/micro-sp" + utm)  # 92 dias depois, outra campanha
    assert nova["opportunity_id"] != velha["opportunity_id"]
    assert client.get(f"/opportunities/{velha['opportunity_id']}").json()["status"] == "perdida"
    first = client.get(f"/opportunities/{nova['opportunity_id']}").json()["primeiro_toque"]
    assert (first["event_id"], first["source_channel"]) == (nova["event_id"], "google/cpc")
    expirada = "SELECT COUNT(*) FROM audit_log WHERE action = 'opportunity.expirada'"
    assert client.app.state.conn.execute(expirada).fetchone()[0] == 1


@pytest.mark.parametrize("data", ["2030-01-01T09:00:00-03:00", "0001-01-01T00:00:00Z"], ids=["futuro", "data_nula"])
def test_data_implausivel_vira_hora_de_recebimento(client, data):
    ana = form(client, "C1_form_1001")
    futuro = form(client, "C1_form_1001", submission_id="form-1040", submitted_at=data)
    # com a data futura a oportunidade da Ana parecia parada e fechava; com o ano 1 a conta de 90 dias estourava
    assert futuro["opportunity_id"] == ana["opportunity_id"]
    opp = client.get(f"/opportunities/{ana['opportunity_id']}").json()
    assert opp["status"] == "aberta"
    assert datetime.now(UTC) - datetime.fromisoformat(opp["ultimo_toque"]["occurred_at"]) < timedelta(minutes=1)
    detail = client.app.state.conn.execute("SELECT detail FROM tracking_issue WHERE kind = 'payload_invalido'").fetchone()
    assert json.loads(detail[0]) == {"campos": ["submitted_at"]}


def test_conversao_usa_click_id_mais_recente_de_cada_plataforma(client):
    lp = "https://clinic.exemplo/lp/micro-sp?"
    ana = form(client, "C1_form_1001")  # fbclid IwAR0abc em 20/10
    form(client, "C1_form_1001", submission_id="form-1031", submitted_at="2026-10-22T10:00:00-03:00",
         page_url=lp + "fbclid=F2")
    form(client, "C1_form_1001", submission_id="form-1032", submitted_at="2026-10-23T10:00:00-03:00",
         page_url=lp + "gclid=G2")
    client.post("/events/erp/sale", json=ev("venda_c1", crm_opportunity_id=ana["opportunity_id"]))
    assert [(c["platform"], c["click_id"], c["status"]) for c in conversoes(client)] == [
        ("google", "G2", "pendente"), ("meta", "F2", "pendente")]  # cada plataforma recebe o clique mais recente dela


@pytest.mark.parametrize("param, dias, status", [("fbclid", 8, "pendente"), ("fbclid", 91, "expirado"),
                                                  ("gclid", 89, "pendente"), ("gclid", 91, "expirado")])
def test_validade_do_click_id_por_plataforma(client, param, dias, status):
    # 90 dias de clique nas duas plataformas
    clique = datetime.fromisoformat(EVENTOS["venda_c1"]["confirmed_at"]) - timedelta(days=dias)
    lead = form(client, "C1_form_1001", page_url=f"https://clinic.exemplo/lp/micro-sp?{param}=X1",
                submitted_at=clique.isoformat())
    client.post("/events/erp/sale", json=ev("venda_c1", crm_opportunity_id=lead["opportunity_id"]))
    assert [c["status"] for c in conversoes(client)] == [status]


def test_venda_em_oportunidade_perdida_quarentena(client):
    velha = form(client, "C1_form_1001", submitted_at="2026-07-20T14:03:00-03:00")
    nova = form(client, "C1_form_1001", submission_id="form-1030", submitted_at="2026-10-20T10:00:00-03:00")
    assert client.get(f"/opportunities/{velha['opportunity_id']}").json()["status"] == "perdida"  # expirou
    r = client.post("/events/erp/sale", json=ev("venda_c1", crm_opportunity_id=velha["opportunity_id"])).json()
    assert (r["status"], r["motivo"]) == ("quarentena", "venda_divergente")
    assert [client.get(f"/opportunities/{o['opportunity_id']}").json()["status"] for o in (velha, nova)] == [
        "perdida", "aberta"]
    detail = client.app.state.conn.execute("SELECT detail FROM tracking_issue WHERE kind = 'venda_divergente'").fetchone()
    assert json.loads(detail[0]) == {"erp_sale_id": "ERP-2026-5001", "crm_opportunity_id": velha["opportunity_id"],
                                     "motivo": "oportunidade_perdida", "oportunidade_aberta": nova["opportunity_id"]}


QR_UTM = "utm_source=offline&utm_medium=qr&utm_campaign=cps-paciente_modelo-paciente"


def ler_q(client, ep, query=QR_UTM):
    r = client.get(f"/q/{ep}?{query}", follow_redirects=False)
    assert r.status_code == 307
    return r.headers["location"]


def texto_do_link(location):
    return parse_qs(urlsplit(location).query)["text"][0]


def com_texto(texto, numero="5521977776666", wamid="wamid.P1"):
    return wa("C2b_whatsapp_direto", contact={"wa_id": numero},
              message={"id": wamid, "from": numero, "text": {"body": texto}})


def test_q_mensagem_com_protocolo_herda_a_campanha(client):
    location = ler_q(client, "qr-cps-recepcao-01")
    texto = texto_do_link(location)
    assert location.startswith("https://wa.me/")
    assert re.fullmatch(r"Olá! Quero informações \(protocolo [2-9A-HJKMNP-Z]{5}\)", texto)
    sessao = dict(client.app.state.conn.execute("SELECT * FROM click_session").fetchone())
    assert (sessao["entry_point"], sessao["utm_campaign"]) == ("qr-cps-recepcao-01", "cps-paciente_modelo-paciente")
    r = client.post("/events/whatsapp", json=com_texto(texto)).json()
    assert (r["origin_type"], r["source_channel"], r["queue"]) == ("observada", "offline/qr", "agenda-cps")
    t = client.get(f"/opportunities/{r['opportunity_id']}").json()["primeiro_toque"]
    assert (t["entry_point"], t["utm_campaign"], t["evidence_level"]) == (
        "qr-cps-recepcao-01", "cps-paciente_modelo-paciente", "campanha")
    sem = client.post("/events/whatsapp", json=com_texto("oi", numero="5521900001111", wamid="wamid.P2")).json()
    assert (sem["origin_type"], sem["queue"]) == ("desconhecida", "triagem-bot")  # sem protocolo, sem origem


def test_q_protocolo_vencido_ou_inexistente(client):
    texto = texto_do_link(ler_q(client, "qr-cps-recepcao-01"))
    client.app.state.conn.execute("UPDATE click_session SET created_at = '2026-01-01T00:00:00+00:00'")  # meses atrás
    vencido = client.post("/events/whatsapp", json=com_texto(texto)).json()
    inexistente = client.post("/events/whatsapp", json=com_texto("protocolo QQQQQ", "5521900001111", "wamid.P2")).json()
    assert [(r["origin_type"], r["queue"]) for r in (vencido, inexistente)] == [("desconhecida", "triagem-bot")] * 2
    issues = client.app.state.conn.execute("SELECT kind, entry_point FROM tracking_issue ORDER BY id")
    assert [tuple(i) for i in issues] == [("protocolo_invalido", "qr-cps-recepcao-01"), ("protocolo_invalido", None)]


def test_q_taxa_de_chegada(client):
    texto = texto_do_link(ler_q(client, "qr-cps-recepcao-01"))
    ler_q(client, "qr-cps-recepcao-01")  # leu e não escreveu
    client.post("/events/whatsapp", json=com_texto(texto))
    client.post("/events/whatsapp", json=com_texto(texto, wamid="wamid.P2"))  # 2ª mensagem: mesma chegada
    query = "utm_source=ig&utm_medium=paid_social&utm_campaign=sp-micropigmentacao-captacao"
    assert ler_q(client, "lp-sp-micro-01", query) == f"https://clinic.exemplo/lp/micro-sp?{query}"
    assert client.get("/q/ctwa-rj-harmo-01", follow_redirects=False).status_code == 404  # ponto sem /q/
    pontos = {p["entry_point"]: p for p in client.get("/quality/report").json()["pontos_de_entrada"]}
    qr, lp = pontos["qr-cps-recepcao-01"], pontos["lp-sp-micro-01"]
    assert (qr["total"], qr["leituras"], qr["taxa_chegada"]) == (1, 2, 0.5)
    # lida e sem nenhum contato ainda aparece: é aí que o vazamento fica visível
    # na LP a chegada é o formulário, que a taxa não vê: só as leituras aparecem
    assert (lp["total"], lp["leituras"], "taxa_chegada" in lp, lp["status"]) == (0, 1, False, "amostra_insuficiente")


def atendimento(client, **changes):
    return client.post("/events/atendimento", json=ev("atendimento_em_negociacao", **changes)).json()


def test_etiqueta_do_atendimento_muda_o_estagio(client):
    carla = form(client, "declarada_form_1004")
    r = atendimento(client)
    assert (r["status"], r["opportunity_id"]) == ("processado", carla["opportunity_id"])
    opp = client.get(f"/opportunities/{carla['opportunity_id']}").json()
    assert (opp["status"], opp["stage"]) == ("aberta", "em_negociacao")
    assert atendimento(client)["status"] == "duplicado"
    assert atendimento(client, event_id="cw-evt-0002", label="perdida")["status"] == "processado"
    assert client.get(f"/opportunities/{carla['opportunity_id']}").json()["status"] == "perdida"
    perdida = "SELECT COUNT(*) FROM audit_log WHERE action = 'opportunity.perdida'"
    assert client.app.state.conn.execute(perdida).fetchone()[0] == 1


def test_etiqueta_gravada_pelo_nucleo_e_eco(client):
    carla = form(client, "declarada_form_1004")
    eco = atendimento(client, origin_system="nucleo")  # anti-loop, com recibo
    assert (eco["status"], count(client, "inbound_event")) == ("ignorado", 2)
    assert client.get(f"/opportunities/{carla['opportunity_id']}").json()["stage"] is None
    assert atendimento(client, event_id="cw-evt-0004")["status"] == "processado"
    # o eco sem origin_system: a etiqueta já é o estágio que o núcleo gravou
    assert atendimento(client, event_id="cw-evt-0005", origin_system=None)["status"] == "ignorado"
    gravado = "SELECT COUNT(*) FROM audit_log WHERE action = 'opportunity.em_negociacao'"
    assert client.app.state.conn.execute(gravado).fetchone()[0] == 1
    sem_pessoa = atendimento(client, event_id="cw-evt-0003", phone="+5521900009999")
    assert (sem_pessoa["status"], sem_pessoa["motivo"]) == ("quarentena", "etiqueta_sem_oportunidade")


def test_timestamp_do_whatsapp_no_futuro_vira_hora_de_recebimento(client):
    ana = form(client, "C1_form_1001")
    futuro = com_texto("oi", numero="5511987654321", wamid="wamid.FUT")
    futuro["entry"][0]["changes"][0]["value"]["messages"][0]["timestamp"] = 9999999998
    r = client.post("/events/whatsapp", json=futuro).json()
    assert r["opportunity_id"] == ana["opportunity_id"]  # com o ano 2286, a da Ana expirava
    assert client.get(f"/opportunities/{ana['opportunity_id']}").json()["status"] == "aberta"
    detail = client.app.state.conn.execute("SELECT detail FROM tracking_issue WHERE kind = 'payload_invalido'").fetchone()
    assert json.loads(detail[0]) == {"campos": ["timestamp"]}


def test_quarentena_que_muda_de_motivo_resolve_a_pendencia_antiga(client):
    bruna = whatsapp(client, "C2a_whatsapp_qr_cps")
    client.post("/events/erp/sale", json=ev("venda_orfa", erp_sale_id="E-A"))  # oportunidade 9999
    client.post("/events/erp/sale", json=ev("venda_divergente", erp_sale_id="E-A", crm_opportunity_id=bruna["opportunity_id"]))
    issues = client.app.state.conn.execute("SELECT kind, status FROM tracking_issue ORDER BY id")
    assert [tuple(i) for i in issues] == [("venda_sem_oportunidade", "resolvida"), ("venda_divergente", "aberta")]


def test_chave_de_idempotencia_normalizada(client):
    rs = [form(client, "falha_form_1003_sem_utm", submission_id=sid) for sid in (1001, 1001.0, " 1001")]
    assert [r["status"] for r in rs] == ["processado", "duplicado", "duplicado"]
    assert len({r["event_id"] for r in rs}) == 1


def test_item_invalido_no_lote_nao_derruba_o_resto(client):
    lote = ev("C2b_whatsapp_direto")
    lote["entry"][0]["changes"][0]["value"]["messages"].append("lixo")
    lote["entry"][0]["changes"][0]["value"]["contacts"].append("lixo")
    r = client.post("/events/whatsapp", json=lote)
    assert r.status_code == 200
    assert [m["status"] for m in r.json()["resultados"]] == ["processado", "ignorado"]
    issue = client.app.state.conn.execute("SELECT kind, event_id, detail FROM tracking_issue").fetchone()
    assert (issue["kind"], issue["event_id"], json.loads(issue["detail"])) == ("payload_invalido", None,
                                                                               {"campos": ["messages"]})


def test_relatorio_usa_indice_no_primeiro_toque(client):
    # sem índice, cada busca do 1º toque varre touchpoint inteira e o relatório (que segura o LOCK) fica quadrático
    # (ordenar os poucos toques de uma oportunidade é barato; varrer a tabela, não)
    for sql in ("SELECT * FROM touchpoint WHERE opportunity_id = 1 ORDER BY origin_type <> 'observada', occurred_at, id LIMIT 1",
                "SELECT id FROM touchpoint WHERE opportunity_id = 1 AND entry_point = 'x' ORDER BY occurred_at, id LIMIT 1"):
        plan = " ".join(r[3] for r in client.app.state.conn.execute(f"EXPLAIN QUERY PLAN {sql}"))
        assert "SEARCH touchpoint USING" in plan and "INDEX" in plan, plan


def test_pagina_de_outro_dominio_nao_e_ponto_de_entrada(client):
    r = form(client, "C1_form_1001", page_url="https://evil.exemplo/lp/micro-sp?utm_source=ig&utm_medium=paid_social&utm_campaign=x")
    t = client.get(f"/opportunities/{r['opportunity_id']}").json()["primeiro_toque"]
    assert t["entry_point"] is None  # o path é o da LP, mas a página não é do site
    issue = client.app.state.conn.execute("SELECT detail FROM tracking_issue WHERE kind = 'ep_desconhecido'").fetchone()
    assert json.loads(issue[0]) == {"host": "evil.exemplo", "path": "/lp/micro-sp"}


def test_email_compartilhado_nao_funde_pessoas(client):
    ana = form(client, "C1_form_1001", email="familia@exemplo.com")
    irmao = form(client, "declarada_form_1004", email="familia@exemplo.com")  # outro telefone, mesmo e-mail
    assert irmao["person_id"] != ana["person_id"] and count(client, "person") == 2
    assert client.get("/quality/report").json()["issues_abertas"] == {"identidade_conflitante": 1}
    so_email = form(client, "declarada_form_1004", submission_id="form-1060", phone=None, email="novo@exemplo.com")
    junta = form(client, "declarada_form_1004", submission_id="form-1061", phone="(21) 91234-0000",
                 email="novo@exemplo.com")
    assert junta["person_id"] == so_email["person_id"]  # quem só tinha e-mail ganha o telefone: não é conflito


def test_toda_escrita_tem_auditoria(client):
    ana = form(client, "C1_form_1001")
    client.post("/events/erp/sale", json=ev("venda_c1", crm_opportunity_id=ana["opportunity_id"]))
    db.dispatch_handoffs(client.app.state.conn, lambda h: None)
    conn = client.app.state.conn
    for table in ("person", "person_identifier", "opportunity", "touchpoint", "consent", "handoff", "erp_sale",
                  "platform_conversion"):
        audited = conn.execute("SELECT COUNT(DISTINCT entity_id) FROM audit_log WHERE entity = ?", (table,)).fetchone()[0]
        assert audited == count(client, table) > 0, table
    handoff = conn.execute("SELECT action FROM audit_log WHERE entity = 'handoff' ORDER BY id")
    assert [a for (a,) in handoff] == ["handoff.criado", "handoff.enviando", "handoff.enviado"]


def test_etiqueta_com_duas_abertas_exige_a_oportunidade(client):
    lp = form(client, "C1_form_1001")
    ctwa = whatsapp(client, "C3_ana_volta_por_anuncio_ctwa")  # Ana com duas oportunidades abertas
    ana = {"phone": "+5511987654321", "label": "perdida"}
    r = atendimento(client, **ana)
    assert (r["status"], r["motivo"]) == ("quarentena", "etiqueta_ambigua")
    # o núcleo grava o id da oportunidade na conversa; com ele, fecha a certa
    r = atendimento(client, event_id="cw-evt-0002", crm_opportunity_id=lp["opportunity_id"], **ana)
    assert r["opportunity_id"] == lp["opportunity_id"]
    assert [client.get(f"/opportunities/{o['opportunity_id']}").json()["status"] for o in (lp, ctwa)] == [
        "perdida", "aberta"]


@pytest.mark.parametrize("campo, valor", [("confirmed_at", "0001-01-02T00:00:00Z"), ("crm_opportunity_id", True)],
                         ids=["data_nula_do_erp", "booleano_como_id"])
def test_venda_com_campo_implausivel_quarentena(client, campo, valor):
    ana = form(client, "C1_form_1001")  # oportunidade 1, com fbclid
    r = client.post("/events/erp/sale", json=ev("venda_c1", crm_opportunity_id=ana["opportunity_id"]) | {campo: valor})
    assert (r.json()["status"], r.json()["motivo"]) == ("quarentena", "payload_invalido")  # nunca 500 nem liga
    assert client.get(f"/opportunities/{ana['opportunity_id']}").json()["status"] == "aberta"


def test_lead_de_teste_fica_fora_do_relatorio_e_das_conversoes(client):
    ana = form(client, "C1_form_1001")
    client.post("/events/erp/sale", json=ev("venda_c1", crm_opportunity_id=ana["opportunity_id"]))
    antes = client.get("/quality/report").json()
    form(client, "falha_form_1003_sem_utm", is_test=True)  # LP paga sem UTM: bloquearia a LP
    qa = form(client, "consentimento_form_1005", consent_ads=True,
              page_url="https://clinic.exemplo/contato?teste=1&gclid=QA1")
    client.post("/events/erp/sale", json=ev("venda_sem_consentimento", crm_opportunity_id=qa["opportunity_id"]))
    depois = client.get("/quality/report").json()

    def metricas(report):
        return {k: v for k, v in report.items() if k not in ("eventos", "issues_abertas")}

    assert metricas(depois) == metricas(antes)  # contagens, liberação e receita
    assert [c["erp_sale_id"] for c in conversoes(client)] == ["ERP-2026-5001"]  # o gclid de QA não sai
    assert [r[0] for r in client.app.state.conn.execute("SELECT is_test FROM touchpoint ORDER BY id")] == [0, 1, 1]


def test_q_chegada_baixa(client):
    def qr():
        return next(p for p in client.get("/quality/report").json()["pontos_de_entrada"]
                    if p["entry_point"] == "qr-cps-recepcao-01")

    textos = [texto_do_link(ler_q(client, "qr-cps-recepcao-01")) for _ in range(19)]
    assert "alerta" not in qr()  # 19 leituras: pouca amostra
    assert qr()["status"] == "amostra_insuficiente"
    textos.append(texto_do_link(ler_q(client, "qr-cps-recepcao-01")))
    # o QR leva a um WhatsApp onde a pessoa desiste ou apaga o protocolo: alerta para o dono conferir. Não bloqueia
    # sozinho, porque robô que se passa por navegador também lê
    assert (qr()["leituras"], qr()["taxa_chegada"], qr()["alerta"], qr()["status"]) == (20, 0.0, "chegada_baixa",
                                                                                      "amostra_insuficiente")
    for i, texto in enumerate(textos[:12]):
        client.post("/events/whatsapp", json=com_texto(texto, numero=f"552190000{i:04d}", wamid=f"wamid.C{i}"))
    assert (qr()["taxa_chegada"], "alerta" in qr(), qr()["status"]) == (0.6, False, "amostra_insuficiente")
    for _ in range(20):
        ler_q(client, "lp-sp-micro-01")
    lp = next(p for p in client.get("/quality/report").json()["pontos_de_entrada"] if p["entry_point"] == "lp-sp-micro-01")
    assert ("taxa_chegada" in lp, "alerta" in lp) == (False, False)  # na LP a chegada é o formulário, que a taxa não vê


def test_q_protocolo_vence_referral_de_post(client):
    msg = com_texto(texto_do_link(ler_q(client, "qr-cps-recepcao-01")))
    msg["entry"][0]["changes"][0]["value"]["messages"][0]["referral"] = {"source_id": "post-77", "source_type": "post"}
    r = client.post("/events/whatsapp", json=msg).json()
    assert (r["origin_type"], r["source_channel"], r["queue"]) == ("observada", "offline/qr", "agenda-cps")
    t = client.get(f"/opportunities/{r['opportunity_id']}").json()["primeiro_toque"]
    assert (t["entry_point"], t["utm_campaign"]) == ("qr-cps-recepcao-01", "cps-paciente_modelo-paciente")


def test_q_head_e_previa_de_link_nao_gravam_leitura(client):
    locations = []
    for ep in ("qr-cps-recepcao-01", "lp-sp-micro-01"):
        r = client.head(f"/q/{ep}?{QR_UTM}", follow_redirects=False)
        assert (r.status_code, r.content) == (307, b"")
        locations.append(r.headers["location"])
    assert locations == ["https://wa.me/5511940000000", f"https://clinic.exemplo/lp/micro-sp?{QR_UTM}"]
    # o app que monta o cartão do link colado numa conversa faz GET: também não é leitura
    for robo in ("facebookexternalhit/1.1", "WhatsApp/2.23.20.0 A", "Twitterbot/1.0", "Slackbot-LinkExpanding 1.0",
                 "TelegramBot (like TwitterBot)"):
        r = client.get(f"/q/qr-cps-recepcao-01?{QR_UTM}", headers={"User-Agent": robo}, follow_redirects=False)
        assert (r.status_code, r.headers["location"]) == (307, "https://wa.me/5511940000000"), robo
    assert count(client, "click_session") == 0  # verificador de link e prévia não são leitura


def test_q_nao_repassa_dado_pessoal(client):
    query = "utm_source=ig&utm_medium=paid_social&utm_campaign=sp-micropigmentacao-captacao&fbclid=F1"
    location = ler_q(client, "lp-sp-micro-01", f"email=ana%40exemplo.com&{query}&nome=Ana&gclid=G1")
    # só utm_* e click ids seguem para a LP: e-mail no link não vai parar na URL do site (nem no log dele)
    assert location == f"https://clinic.exemplo/lp/micro-sp?{query}&gclid=G1"


def chatwoot(client, **changes):
    return client.post("/events/chatwoot", json=ev("chatwoot_ana_ctwa", **changes)).json()


def test_chatwoot_com_referral_herda_o_anuncio(client):
    r = chatwoot(client)  # o message_created que o Chatwoot repassa da mensagem wamid.CTWA001
    assert (r["status"], r["origin_type"], r["source_channel"], r["queue"]) == (
        "processado", "observada", "meta_ctwa", "comercial-rj")
    t = client.get(f"/opportunities/{r['opportunity_id']}").json()["primeiro_toque"]
    assert (t["ad_id"], t["click_id"], t["entry_point"]) == ("120210000000001", "ARAkLk9", "ctwa-rj-harmo-01")
    assert client.get(f"/people/{r['person_id']}/journey").json()["nome"] == "Ana S."


def test_mesma_mensagem_pela_meta_e_pelo_chatwoot_e_duplicado(client):
    meta = whatsapp(client, "C3_ana_volta_por_anuncio_ctwa")
    # o created_at é a hora do Chatwoot, segundos depois do timestamp da Meta: o hash não usa a hora
    assert chatwoot(client) == {"status": "duplicado", "event_id": meta["event_id"]}
    assert count(client, "touchpoint") == 1


def test_chatwoot_so_mensagem_recebida_vira_contato(client):
    for change in ({"message_type": "outgoing"}, {"event": "conversation_status_changed"}):
        assert chatwoot(client, **change) == {"status": "ignorado"}  # resposta da atendente, outros eventos
    assert count(client, "inbound_event") == 0


def test_id_gigante_na_url_e_422_nao_500(client):
    assert client.get("/people/99999999999999999999/journey").status_code == 422
    assert client.get("/opportunities/9223372036854775808").status_code == 422


def test_q_nao_repassa_utm_com_email(client):
    r = client.get("/q/lp-sp-micro-01?utm_campaign=a%40b.com&utm_source=ig", follow_redirects=False)
    assert r.status_code == 307 and "%40" not in r.headers["location"] and "utm_source=ig" in r.headers["location"]


def test_lp_com_www_e_a_mesma_lp(client):
    # www. não pode desligar a falha escolhida: a LP sem UTM continua identificada, com a pendência
    r = form(client, "falha_form_1003_sem_utm", page_url="https://www.clinic.exemplo/lp/micro-sp")
    assert client.get(f"/opportunities/{r['opportunity_id']}").json()["primeiro_toque"]["entry_point"] == "lp-sp-micro-01"
    kinds = [k for (k,) in client.app.state.conn.execute("SELECT kind FROM tracking_issue")]
    assert kinds == ["parametros_perdidos"]


def test_formulario_com_produto_sem_unidade_entra_na_aberta(client):
    ana = form(client, "C1_form_1001")  # micropigmentacao/sp, com a vendedora de SP
    contato = form(client, "C1_form_1001", submission_id="form-1040", product="micropigmentacao", unit=None,
                   page_url="https://clinic.exemplo/contato")  # o /contato não tem unidade
    assert (contato["opportunity_id"], contato["queue"]) == (ana["opportunity_id"], "comercial-sp")
    assert [q for (q,) in client.app.state.conn.execute("SELECT queue FROM handoff")] == ["comercial-sp"]


def test_q_protocolo_reutilizado_por_outra_pessoa(client):
    texto = texto_do_link(ler_q(client, "qr-cps-recepcao-01"))
    dona = client.post("/events/whatsapp", json=com_texto(texto)).json()
    de_novo = client.post("/events/whatsapp", json=com_texto(texto, wamid="wamid.P3")).json()
    assert dona["origin_type"] == de_novo["origin_type"] == "observada"  # a mesma pessoa pode mandar de novo
    repassado = client.post("/events/whatsapp", json=com_texto(texto, "5521900001111", "wamid.P2")).json()
    assert repassado["origin_type"] == "desconhecida"  # print ou mensagem repassada não prova a leitura
    issue = client.app.state.conn.execute("SELECT detail FROM tracking_issue WHERE kind = 'protocolo_invalido'").fetchone()
    assert json.loads(issue[0])["motivo"] == "reutilizado"


def test_oportunidade_em_negociacao_nao_expira_sozinha(client):
    carla = form(client, "declarada_form_1004", submitted_at="2026-07-01T10:00:00-03:00")
    atendimento(client)  # a vendedora marcou em_negociacao
    volta = form(client, "declarada_form_1004", submission_id="form-1041", submitted_at="2026-10-20T10:00:00-03:00")
    assert volta["opportunity_id"] == carla["opportunity_id"]  # 111 dias depois, segue a mesma
    assert client.get(f"/opportunities/{carla['opportunity_id']}").json()["status"] == "aberta"


def test_lote_com_mensagem_sem_wamid_grava_as_outras(client):
    lote = ev("C2b_whatsapp_direto")
    mensagens = lote["entry"][0]["changes"][0]["value"]["messages"]
    mensagens.append({k: v for k, v in mensagens[0].items() if k != "id"})
    r = client.post("/events/whatsapp", json=lote).json()
    assert [m["status"] for m in r["resultados"]] == ["processado", "ignorado"]
    issue = client.app.state.conn.execute("SELECT detail FROM tracking_issue").fetchone()
    assert json.loads(issue[0]) == {"campos": ["id"]}


def test_lead_de_teste_vai_para_a_fila_de_teste(client):
    r = form(client, "C1_form_1001", is_test=True)
    assert r["queue"] == "teste"
    assert [q for (q,) in client.app.state.conn.execute("SELECT queue FROM handoff")] == ["teste"]


def test_click_id_com_email_nao_e_gravado(client):
    ler_q(client, "lp-sp-micro-01", "utm_source=ig&fbclid=ana%40exemplo.com")
    assert client.app.state.conn.execute("SELECT click_id_type, click_id FROM click_session").fetchone()[:] == (None, None)


def test_oportunidade_mostra_o_toque_atribuido(client):
    # "oi" direto e depois o formulário com gclid: o primeiro toque é o "oi", a origem atribuída é o Google
    client.post("/events/whatsapp", json=wa("C2b_whatsapp_direto", contact={"wa_id": "5521977776666"},
                                            message={"from": "5521977776666"}))
    r = form(client, "consentimento_form_1005", phone="(21) 97777-6666")
    opp = client.get(f"/opportunities/{r['opportunity_id']}").json()
    assert (opp["primeiro_toque"]["origin_type"], opp["toque_atribuido"]["source_channel"]) == ("desconhecida", "google")


def test_lead_real_nao_cai_na_oportunidade_de_teste(client):
    qa = form(client, "C1_form_1001", is_test=True)  # QA usou o telefone da Ana
    ana = form(client, "C1_form_1001", submission_id="form-1042")
    assert ana["opportunity_id"] != qa["opportunity_id"] and ana["queue"] == "comercial-sp"
    assert [q for (q,) in client.app.state.conn.execute("SELECT queue FROM handoff ORDER BY id")] == ["teste", "comercial-sp"]
    client.post("/events/erp/sale", json=ev("venda_c1", crm_opportunity_id=ana["opportunity_id"]))
    assert client.get("/quality/report").json()["vendas"]["total"] == 1  # a venda real não some


def test_whatsapp_so_com_bsuid(client):
    # quem adotou nome de usuário chega sem o telefone (from/wa_id), só com o BSUID
    def sem_telefone(wamid):
        payload = wa("C2b_whatsapp_direto", message={"id": wamid, "from_user_id": "BR.1234567890"},
                     contact={"user_id": "BR.1234567890"})
        del payload["entry"][0]["changes"][0]["value"]["messages"][0]["from"]
        del payload["entry"][0]["changes"][0]["value"]["contacts"][0]["wa_id"]
        return client.post("/events/whatsapp", json=payload).json()
    primeira, segunda = sem_telefone("wamid.U1"), sem_telefone("wamid.U2")
    assert (primeira["status"], segunda["person_id"]) == ("processado", primeira["person_id"])
    ids = client.app.state.conn.execute("SELECT kind, value FROM person_identifier").fetchall()
    assert [tuple(i) for i in ids] == [("bsuid", "BR.1234567890")]


def test_retorno_direto_a_lp_paga_tem_outra_pendencia(client):
    form(client, "falha_form_1003_sem_utm", referrer=None)  # favorito ou link digitado: sem referrer
    kinds = [k for (k,) in client.app.state.conn.execute("SELECT kind FROM tracking_issue")]
    assert kinds == ["retorno_sem_parametro"]  # origem perdida, mas o remédio é guardar o clique, não o link
    lp = client.get("/quality/report").json()["pontos_de_entrada"][0]
    assert (lp["entry_point"], lp["com_problema"]) == ("lp-sp-micro-01", 1)  # conta contra a cobertura do mesmo jeito


def test_venda_com_id_da_oportunidade_em_texto(client):
    ana = form(client, "C1_form_1001")
    r = client.post("/events/erp/sale", json=ev("venda_c1", crm_opportunity_id=str(ana["opportunity_id"]))).json()
    assert (r["status"], r["opportunity_id"]) == ("processado", ana["opportunity_id"])
    torta = client.post("/events/erp/sale", json=ev("venda_orfa", crm_opportunity_id="7a")).json()
    assert torta["status"] == "quarentena"


def test_so_venda_de_ponto_liberado_entra_no_custo_por_canal(client):
    ana = form(client, "C1_form_1001")  # LP com 1 lead: ainda não liberada
    sinteticos = [lead_sintetico(client, i) for i in range(30)]  # /contato: 30 leads com origem, liberado
    for erp_id, lead in (("ERP-L1", ana), ("ERP-L2", sinteticos[0])):
        opp = client.get(f"/opportunities/{lead['opportunity_id']}").json()
        r = client.post("/events/erp/sale", json=ev("venda_c1", erp_sale_id=erp_id, crm_opportunity_id=opp["id"],
                                                    product=opp["product"], unit=opp["unit"])).json()
        assert r["status"] == "processado"
    vendas = client.get("/quality/report").json()["vendas"]
    assert (vendas["valor_cents"], vendas["valor_em_pontos_liberados_cents"]) == (2 * 349000, 349000)


def test_lead_de_teste_nao_mexe_na_pessoa_real(client):
    ana = form(client, "C1_form_1001")  # aceitou anúncios
    form(client, "C1_form_1001", submission_id="form-qa", is_test=True, consent_ads=False, email="qa@clinic.exemplo")
    assert "qa@clinic.exemplo" not in [v for (v,) in client.app.state.conn.execute("SELECT value FROM person_identifier")]
    client.post("/events/erp/sale", json=ev("venda_c1", crm_opportunity_id=ana["opportunity_id"]))
    assert [c["status"] for c in conversoes(client)] == ["pendente"]  # o "não" da QA não é da Ana


def test_lead_de_teste_nao_expira_a_oportunidade_real(client):
    ana = form(client, "C1_form_1001", submitted_at="2026-06-01T10:00:00-03:00")
    form(client, "C1_form_1001", submission_id="form-qa", is_test=True,
         submitted_at="2026-10-21T10:00:00-03:00")  # QA com o telefone da Ana, 142 dias depois
    status = client.app.state.conn.execute("SELECT status FROM opportunity WHERE id = ?", (ana["opportunity_id"],))
    assert status.fetchone()[0] == "aberta"


def test_etiqueta_com_id_da_oportunidade_dispensa_telefone(client):
    carla = form(client, "declarada_form_1004")
    r = atendimento(client, phone=None, crm_opportunity_id=carla["opportunity_id"])  # contato só com BSUID
    assert (r["status"], r["opportunity_id"]) == ("processado", carla["opportunity_id"])


def test_formulario_de_aluna_sem_produto_e_interesse_novo(client):
    ana = form(client, "C1_form_1001")
    client.post("/events/erp/sale", json=ev("venda_c1", crm_opportunity_id=ana["opportunity_id"]))
    volta = form(client, "C1_form_1001", submission_id="form-1043", product=None, unit=None, how_heard="amigo",
                 page_url="https://clinic.exemplo/contato")
    assert volta["opportunity_id"] != ana["opportunity_id"] and volta["queue"] != "atendimento-aluna"


def test_lead_de_teste_nao_trava_a_etiqueta_da_vendedora(client):
    carla = form(client, "declarada_form_1004")
    form(client, "declarada_form_1004", submission_id="form-qa2", is_test=True, product="harmonizacao", unit="rj")
    r = atendimento(client)  # a conversa sem o id: a única aberta real é a da Carla
    assert (r["status"], r["opportunity_id"]) == ("processado", carla["opportunity_id"])


def test_paciente_modelo_fica_fora_dos_numeros_de_curso(client):
    form(client, "C1_form_1001")
    whatsapp(client, "C2a_whatsapp_qr_cps")  # QR de paciente modelo em Campinas
    report = client.get("/quality/report").json()
    assert report["origem_por_canal"] == {"observada:ig/paid_social": 1}
    assert report["paciente_modelo"]["origem_por_canal"] == {"observada:offline/qr": 1}
