import json
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
    ("(11) 3456-7890", "+551134567890"),  # fixo: não ganha nono dígito
    ("123", None),
    (None, None),
])
def test_telefone_vira_e164(raw, expected):
    assert domain.normalize_phone(raw) == expected


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
    ({"utm_source": "meta", "utm_campaign": "x", "click_id_type": "fbclid", "click_id": "a"}, ("observada", "meta")),
    ({"click_id_type": "gclid", "click_id": "a"}, ("observada", "google")),
    ({"click_id_type": "fbclid", "click_id": "a"}, ("observada", "meta")),
    ({"ad_id": "1", "click_id_type": "ctwa_clid", "click_id": "a"}, ("observada", "meta_ctwa")),
    ({"entry_point": "qr-cps-recepcao-01"}, ("observada", "qr_code")),
    ({"entry_point": "lp-sp-micro-01"}, ("desconhecida", None)),  # ponto de entrada de LP não é origem
    ({"declared": "instagram"}, ("declarada", None)),
    ({}, ("desconhecida", None)),
], ids=["utm", "gclid", "fbclid", "ctwa", "qr", "lp_sem_parametro", "declarada", "nada"])
def test_classificacao_de_origem(touch, expected):
    assert domain.classify(touch) == expected


def test_form_touch_guarda_so_parametros_de_rastreio():
    payload = EVENTOS["C1_form_1001"] | {
        "page_url": "https://clinic.exemplo/contato?email=ana@exemplo.com&utm_source=google&gclid=G1"}
    touch, issues = domain.form_touch(payload, CATALOG)
    assert (touch["utm_source"], touch["click_id_type"], touch["entry_point"]) == ("google", "gclid", "site-online-contato-01")
    assert "ana@" not in json.dumps(touch)  # e-mail que vazou na URL não entra no toque
    assert issues == []


def test_form_touch_lp_paga_sem_parametros_abre_issue():
    touch, issues = domain.form_touch(EVENTOS["falha_form_1003_sem_utm"], CATALOG)
    assert touch["entry_point"] == "lp-sp-micro-01"
    assert issues == [("parametros_perdidos", "lp-sp-micro-01", {"referrer_host": "bit.ly"})]


def test_whatsapp_codigo_nao_cadastrado_nao_vira_origem():
    touch, issues = domain.whatsapp_touch("oi [qr-rj-banner-09]", None, CATALOG)
    assert domain.classify(touch) == ("desconhecida", None)
    assert issues == [("ep_desconhecido", "qr-rj-banner-09", {})]


def test_utm_fora_do_padrao_registrada_e_email_descartado():
    url = "https://clinic.exemplo/lp/micro-sp?utm_source=Facebook&utm_medium=cpc&utm_campaign=ana%40exemplo.com"
    touch, issues = domain.form_touch(EVENTOS["C1_form_1001"] | {"page_url": url}, CATALOG)
    assert (touch["utm_source"], touch["utm_campaign"]) == ("Facebook", None)  # fora da lista fica como veio; com "@" some
    assert domain.classify(touch) == ("observada", "Facebook")
    assert issues == [("utm_fora_do_padrao", "lp-sp-micro-01", {"campos": ["utm_campaign", "utm_source"]})]


def test_pagina_fora_do_catalogo_abre_ep_desconhecido():
    payload = EVENTOS["declarada_form_1004"] | {"page_url": "https://clinic.exemplo/blog/post-1"}
    touch, issues = domain.form_touch(payload, CATALOG)
    assert touch["entry_point"] is None
    assert issues == [("ep_desconhecido", None, {"path": "/blog/post-1"})]


def test_tabela_de_tolerancia_garante_cobertura_de_90():
    # com n leads e até k problemas, P(observar isso | cobertura real 90%) <= 5%; com k+1 já não garante
    def chance(n, k):
        return sum(comb(n, x) * 0.9 ** x * 0.1 ** (n - x) for x in range(n - k, n + 1))

    for n, k in CATALOG["liberacao"]["tolerancia"]:
        assert chance(n, k) <= 0.05 < chance(n, k + 1)
