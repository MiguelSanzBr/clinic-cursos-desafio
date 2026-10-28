"""Regras puras: normalização, origem e fila. Sem banco e sem HTTP."""
import hashlib
import json
import re
from datetime import UTC
from urllib.parse import parse_qs, urlsplit

UTM_KEYS = ("utm_source", "utm_medium", "utm_campaign", "utm_content")
CLICK_KEYS = ("gclid", "gbraid", "wbraid", "fbclid")
CLICK_CHANNEL = {"gclid": "google", "gbraid": "google", "wbraid": "google",
                 "fbclid": "meta"}  # fbclid indica Meta, não prova mídia paga
EP_CODE = re.compile(r"\[([a-z]+-[a-z]+-[a-z0-9-]+)\]", re.IGNORECASE)


def normalize_phone(raw):
    # shortcut: só números do Brasil; wa_id estrangeiro com 10-11 dígitos seria lido como DDD. Tratar quando houver lead do exterior.
    digits = re.sub(r"\D", "", raw or "")
    if len(digits) in (10, 11):
        digits = "55" + digits
    # hipótese a confirmar: wa_id de celular antigo pode chegar sem o nono dígito (55 + DDD + 8 dígitos)
    if len(digits) == 12 and digits.startswith("55") and digits[4] in "6789":
        digits = digits[:4] + "9" + digits[4:]
    return "+" + digits if len(digits) in (12, 13) and digits.startswith("55") else None


def normalize_email(raw):
    email = (raw or "").strip().lower()
    return email if re.fullmatch(r"[^@\s]+@[^@\s]+", email) else None


def identifiers(phone, email):
    """Identificadores válidos, telefone primeiro (é o que desempata conflito de identidade)."""
    pairs = [("phone", normalize_phone(phone)), ("email", normalize_email(email))]
    return [(kind, value) for kind, value in pairs if value]


def payload_hash(payload):
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def utc_iso(moment):
    return moment.astimezone(UTC).isoformat()


def classify(touch):
    """(origin_type, source_channel). Só é 'observada' com evidência no próprio evento; canal nunca é inventado."""
    qr = (touch.get("entry_point") or "").startswith("qr-")
    evidence = any(touch.get(k) for k in UTM_KEYS) or touch.get("click_id") or touch.get("ad_id") or qr
    if not evidence:
        # 'inferida' existe no schema, mas nenhuma regra a produz nesta demo
        return ("declarada" if touch.get("declared") else "desconhecida"), None
    if touch.get("utm_source"):
        return "observada", touch["utm_source"]
    if touch.get("ad_id"):
        return "observada", "meta_ctwa"
    if touch.get("click_id_type") in CLICK_CHANNEL:
        return "observada", CLICK_CHANNEL[touch["click_id_type"]]
    return "observada", "qr_code" if qr else None


def form_touch(payload, catalog):
    """Toque de formulário. Da page_url só saem utm_* e click ids: o resto (onde pode vazar e-mail) não entra."""
    url = urlsplit(payload.get("page_url") or "")
    params = {k: v[0] for k, v in parse_qs(url.query).items()}
    click = next((k for k in CLICK_KEYS if k in params), None)
    entry_points = catalog["entry_points"]
    code = next((c for c, ep in entry_points.items() if ep.get("path") == url.path.rstrip("/")), None)
    ep = entry_points.get(code, {})
    unit, product = payload.get("unit"), payload.get("product")
    utms = {k: params.get(k) for k in UTM_KEYS}
    wrong = [k for k, v in utms.items() if v and "@" in v]  # e-mail vazado na UTM: descartado, nunca gravado
    utms |= dict.fromkeys(wrong)
    allowed = {"utm_source": catalog["utm_sources"], "utm_medium": catalog["utm_mediums"]}
    wrong += [k for k, values in allowed.items() if utms[k] and utms[k] not in values]
    touch = utms | {
        "contact_channel": "form",
        "click_id_type": click,
        "click_id": params.get(click),
        "entry_point": code,
        "declared": payload.get("how_heard"),
        # valor fora do catálogo não é inventado nem rejeita o lead: cai no do ponto de entrada (ou fica desconhecido)
        "unit": unit if unit in catalog["units"] else ep.get("unit"),
        "product": product if product in catalog["products"] else ep.get("product"),
    }
    issues = []
    if wrong:
        # fora da convenção fica como veio (é o que o link trouxe) e vira pendência para corrigir o link
        issues.append(("utm_fora_do_padrao", code, {"campos": sorted(wrong)}))
    if not code:
        issues.append(("ep_desconhecido", None, {"path": url.path}))
    # olha a falta de parâmetro, não o origin_type: um "como conheceu" preenchido também esconderia a perda
    if ep.get("exige_parametros") and not (any(utms.values()) or click):
        referrer_host = urlsplit(payload.get("referrer") or "").hostname
        issues.append(("parametros_perdidos", code, {"referrer_host": referrer_host}))
    return touch, issues


def whatsapp_touch(text, referral, catalog):
    """Toque de WhatsApp. Origem só com evidência: referral de anúncio (CTWA) ou código [ep] cadastrado no texto."""
    touch, issues = {"contact_channel": "whatsapp"}, []
    if referral:
        ad = catalog["ads"].get(referral.get("source_id"), {})
        if not ad:
            # o ad_id continua sendo evidência (observada), mas sem campanha, unidade nem produto: pendência
            issues.append(("anuncio_desconhecido", None, {"ad_id": referral.get("source_id")}))
        touch |= {
            "ad_id": referral.get("source_id"),
            "click_id_type": "ctwa_clid" if referral.get("ctwa_clid") else None,
            "click_id": referral.get("ctwa_clid"),
            "utm_campaign": ad.get("campaign"),
            "unit": ad.get("unit"),
            "product": ad.get("product"),
        }
    if match := EP_CODE.search(text or ""):
        code = match.group(1).lower()
        if ep := catalog["entry_points"].get(code):
            touch |= {"entry_point": code, "unit": touch.get("unit") or ep.get("unit"),
                      "product": touch.get("product") or ep.get("product")}
        else:
            # código que ninguém cadastrou não vira origem: vira pendência para achar o material impresso
            issues.append(("ep_desconhecido", code, {}))
    return touch, issues


def sale_problem(sale, opportunity):
    """Motivo para estacionar a venda, ou None. Produto ou unidade diferentes da oportunidade: não fecha a errada."""
    if opportunity is None:
        return "venda_sem_oportunidade"
    if any(sale.get(k) and sale[k] != opportunity[k] for k in ("product", "unit")):
        return "venda_divergente"
    return None


def queue_for(unit):
    # unidade desconhecida vai para a triagem do bot (IA simulada): pergunta produto, unidade e "como conheceu".
    # A resposta voltaria como toque declarado, nunca como observado.
    return "triagem-bot" if unit in (None, "desconhecida") else f"comercial-{unit}"
