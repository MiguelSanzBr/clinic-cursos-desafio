import copy
import json
from datetime import UTC, datetime, timedelta
from math import comb
from pathlib import Path

import pytest

from app import domain

ROOT = Path(__file__).resolve().parents[1]
CATALOG = json.loads((ROOT / "data" / "catalog.json").read_text())
EVENTOS = json.loads((ROOT / "data" / "eventos.json").read_text())


@pytest.mark.parametrize("raw, expected", [
    ("(11) 98765-4321", "+5511987654321"),
    ("+55 11 98765-4321", "+5511987654321"),
    ("5511987654321", "+5511987654321"),
    ("551187654321", "+5511987654321"),  # wa_id sem o nono dígito
    ("(011) 98765-4321", "+5511987654321"),  # 0 de discagem antes do DDD
    ("(11) 3456-7890", "+551134567890"),  # fixo: não ganha nono dígito
    ("+1 415 555 1234", None),  # outro país no formulário: sem identificador, não vira +55
    ("123", None),
    (None, None),
])
def test_telefone_vira_e164(raw, expected):
    assert domain.normalize_phone(raw) == expected


def test_wa_id_aceita_numero_de_fora_do_brasil():
    assert domain.normalize_phone("351912345678", wa_id=True) == "+351912345678"  # o wa_id já traz o país
    assert domain.normalize_phone("551187654321", wa_id=True) == "+5511987654321"
    assert domain.normalize_phone("351912345678") is None  # no formulário, só Brasil
    assert domain.normalize_phone("14155551234", wa_id=True) == "+14155551234"


@pytest.mark.parametrize("raw, expected", [
    (" Ana.Souza@Exemplo.com ", "ana.souza@exemplo.com"),
    ("ana.souza@gmail.com", "ana.souza@gmail.com"),  # não mexe nos pontos do Gmail
    ("sem-arroba", None),
    ("", None),
    (None, None),
])
def test_email_normalizado(raw, expected):
    assert domain.normalize_email(raw) == expected


@pytest.mark.parametrize("touch, expected", [
    ({"utm_source": "ig", "utm_medium": "paid_social", "utm_campaign": "x"}, ("observada", "ig/paid_social")),
    ({"utm_source": "meta", "utm_campaign": "x", "click_id_type": "fbclid", "click_id": "a"}, ("observada", "meta")),
    ({"utm_campaign": "x"}, ("desconhecida", None)),  # UTM incompleta não é evidência
    ({"utm_campaign": "x", "declared": "instagram"}, ("declarada", None)),
    ({"click_id_type": "gclid", "click_id": "a"}, ("observada", "google")),
    ({"click_id_type": "fbclid", "click_id": "a"}, ("observada", "meta")),
    ({"ad_id": "1", "click_id_type": "ctwa_clid", "click_id": "a"}, ("observada", "meta_ctwa")),
    ({"entry_point": "qr-cps-recepcao-01", "qr": True}, ("observada", "offline/qr")),
    ({"entry_point": "lp-sp-micro-01"}, ("desconhecida", None)),  # ponto de entrada de LP não é origem
    ({"declared": "instagram"}, ("declarada", None)),
    ({}, ("desconhecida", None)),
], ids=["utm", "utm_incompleta_com_click", "utm_incompleta", "utm_incompleta_declarada", "gclid", "fbclid", "ctwa", "qr", "lp_sem_parametro", "declarada", "nada"])
def test_classificacao_de_origem(touch, expected):
    assert domain.classify(touch) == expected


def test_form_touch_guarda_so_parametros_de_rastreio():
    payload = EVENTOS["C1_form_1001"] | {
        "page_url": "https://clinic.exemplo/contato?email=ana@exemplo.com&utm_source=google&utm_medium=cpc"
                    "&utm_campaign=sp-micropigmentacao-captacao&gclid=G1"}
    touch, issues = domain.form_touch(payload, CATALOG)
    assert (touch["utm_source"], touch["click_id_type"], touch["entry_point"]) == ("google", "gclid", "site-online-contato-01")
    assert "ana@" not in json.dumps(touch)  # e-mail que vazou na URL não entra no toque
    assert issues == []


def test_form_touch_lp_paga_sem_parametros_abre_issue():
    touch, issues = domain.form_touch(EVENTOS["falha_form_1003_sem_utm"], CATALOG)
    assert touch["entry_point"] == "lp-sp-micro-01"
    assert issues == [("parametros_perdidos", "lp-sp-micro-01", {"referrer_host": "l.instagram.com"})]


@pytest.mark.parametrize("page, referrer, origem, perdidos", [
    ("/contato", "https://www.google.com.br/", ("observada", "google/busca"), False),
    ("/contato", "https://duckduckgo.com/", ("observada", "duckduckgo/busca"), False),
    ("/lp/micro-sp", "https://www.bing.com/search?q=micro", ("observada", "bing/busca"), True),
    ("/contato", "https://l.instagram.com/", ("desconhecida", None), False),
    ("/contato?gclid=G1", "https://www.google.com/", ("observada", "google"), False),
], ids=["google_br", "duckduckgo", "lp_paga_nao_recebe_organico", "referrer_de_app_nao_e_busca", "click_id_vence"])
def test_busca_organica_pelo_referrer(page, referrer, origem, perdidos):
    payload = EVENTOS["falha_form_1003_sem_utm"] | {"page_url": "https://clinic.exemplo" + page, "referrer": referrer}
    touch, issues = domain.form_touch(payload, CATALOG)
    assert domain.classify(touch) == origem
    assert any(kind == "parametros_perdidos" for kind, _, _ in issues) == perdidos


def test_whatsapp_codigo_nao_cadastrado_nao_vira_origem():
    touch, issues = domain.whatsapp_touch("oi [qr-rj-banner-09]", None, CATALOG)
    assert domain.classify(touch) == ("desconhecida", None)
    assert issues == [("ep_desconhecido", "qr-rj-banner-09", {})]


def test_utm_fora_do_padrao_registrada_e_email_descartado():
    url = "https://clinic.exemplo/lp/micro-sp?utm_source=Facebook&utm_medium=cpc&utm_campaign=ana%40exemplo.com"
    touch, issues = domain.form_touch(EVENTOS["C1_form_1001"] | {"page_url": url}, CATALOG)
    assert (touch["utm_source"], touch["utm_campaign"]) == ("Facebook", None)  # fora da lista fica como veio; com "@" some
    assert domain.classify(touch) == ("desconhecida", None)  # sem a campanha a UTM fica incompleta
    assert issues == [("utm_fora_do_padrao", "lp-sp-micro-01",
                       {"campos": ["utm_campaign", "utm_source"], "faltando": ["utm_campaign"]})]


def test_pagina_fora_do_catalogo_abre_ep_desconhecido():
    payload = EVENTOS["declarada_form_1004"] | {"page_url": "https://clinic.exemplo/blog/post-1"}
    touch, issues = domain.form_touch(payload, CATALOG)
    assert touch["entry_point"] is None
    assert issues == [("ep_desconhecido", None, {"host": "clinic.exemplo", "path": "/blog/post-1"})]


def test_qr_pelo_tipo_do_catalogo_nao_pelo_prefixo():
    catalog = copy.deepcopy(CATALOG)
    catalog["entry_points"] |= {"qr-sp-banner-01": {"tipo": "lp", "unit": "sp", "product": "micropigmentacao"},
                                "placa-cps-porta-01": {"tipo": "qr", "unit": "cps", "product": "paciente_modelo"}}
    assert domain.classify(domain.whatsapp_touch("oi [qr-sp-banner-01]", None, catalog)[0]) == ("desconhecida", None)
    assert domain.classify(domain.whatsapp_touch("oi [placa-cps-porta-01]", None, catalog)[0]) == ("observada", "offline/qr")


def test_referral_sem_source_type():
    com_id, issues = domain.whatsapp_touch("oi", {"source_id": "120210000000001"}, CATALOG)
    assert domain.classify(com_id) == ("observada", "meta_ctwa") and issues == []  # source_id basta para ser anúncio
    assert domain.classify(domain.whatsapp_touch("oi", {"source_url": "https://fb.me/x"}, CATALOG)[0]) == (
        "desconhecida", None)  # sem source_type nem source_id o referral não diz nada


@pytest.mark.parametrize("flags, status", [
    ({"sensitive": True, "consented": False, "expired": True}, "bloqueado_sensivel"),
    ({"consented": False, "expired": True}, "bloqueado_consentimento"),
    ({"expired": True}, "expirado"),
    ({}, "pendente"),
])
def test_precedencia_da_conversao(flags, status):
    row = domain.conversion("fbclid", "x", **{"sensitive": False, "consented": True, "expired": False}
                            | flags)
    assert row["status"] == status
    assert row["click_id"] == ("x" if status == "pendente" else None)  # bloqueada não copia


@pytest.mark.parametrize("campanha, campos", [
    ("sp-micropigmentacao-captacao", None),
    ("cps-paciente_modelo-paciente", None),
    ("black-friday", ["utm_campaign"]),
    ("campinas-micropigmentacao-captacao", ["utm_campaign"]),  # unidade fora do catálogo
    ("sp-micropigmentacao-venda", ["utm_campaign"]),  # objetivo fora de captacao|paciente|marca
    ("sp-micropigmentacao-captacao-generica", None),  # sufixo livre separa duas campanhas de mesma base
    ("sp-micropigmentacao-captacaox", ["utm_campaign"]),  # sufixo só depois de hífen
], ids=["padrao", "padrao_qr", "texto_livre", "unidade_errada", "objetivo_errado", "sufixo_livre", "sem_hifen"])
def test_formato_de_utm_campaign(campanha, campos):
    url = f"https://clinic.exemplo/lp/micro-sp?utm_source=ig&utm_medium=paid_social&utm_campaign={campanha}"
    touch, issues = domain.form_touch(EVENTOS["C1_form_1001"] | {"page_url": url}, CATALOG)
    assert touch["utm_campaign"] == campanha  # fora do padrão fica como veio: é o que o link trouxe
    assert issues == ([("utm_fora_do_padrao", "lp-sp-micro-01", {"campos": campos, "faltando": []})] if campos else [])


def serie(problemas, horas=6):
    """Leads de um ponto de entrada, um a cada `horas`; '1' é lead com problema."""
    inicio = datetime(2026, 10, 1, tzinfo=UTC)
    return [((inicio + timedelta(hours=i * horas)).isoformat(), c == "1") for i, c in enumerate(problemas)]


@pytest.mark.parametrize("problemas, horas, status", [
    ("0" * 30, 6, "liberado"),
    ("0" * 30, 1.5, "amostra_insuficiente"),
    ("0" * 48 + "11", 6, "liberado"),
    ("0" * 30 + "11111", 6, "bloqueado"),
    ("0" * 30 + "10" * 6 + "1", 6, "bloqueado"),
    ("0" * 30 + "10" * 6, 6, "liberado"),
    ("1" + "0" * 29, 6, "bloqueado"),
], ids=["30_limpos_em_7_dias", "30_em_2_dias_nao_libera", "liberado_com_2_em_50_continua", "5_seguidos_bloqueia",
        "7_em_50_bloqueia", "6_em_50_continua", "1_em_30_nao_libera"])
def test_liberacao_por_replay(problemas, horas, status):
    assert domain.release_status(serie(problemas, horas), CATALOG["liberacao"]) == status


def test_tabela_de_tolerancia_garante_cobertura_de_90():
    # com n leads e até k problemas, P(observar isso | cobertura real 90%) <= 5%; com k+1 já não garante
    def chance(n, k):
        return sum(comb(n, x) * 0.9 ** x * 0.1 ** (n - x) for x in range(n - k, n + 1))

    for n, k in CATALOG["liberacao"]["tolerancia"]:
        assert chance(n, k) <= 0.05 < chance(n, k + 1)
