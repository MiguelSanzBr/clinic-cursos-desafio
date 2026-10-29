"""Regras puras: normalização, origem e fila. Sem banco e sem HTTP."""
import hashlib
import json
import re
from datetime import UTC, datetime, timedelta
from fnmatch import fnmatch
from urllib.parse import parse_qs, urlsplit

UTM_KEYS = ("utm_source", "utm_medium", "utm_campaign", "utm_id", "utm_content")
UTM_REQUIRED = ("utm_source", "utm_medium", "utm_campaign")  # só os três juntos são evidência
UNKNOWN = ("a_definir", "desconhecida")  # produto/unidade de oportunidade ainda não qualificada
CLICK_KEYS = ("gclid", "gbraid", "wbraid", "fbclid")
CAMPAIGN_CLICKS = ("gclid", "gbraid", "wbraid")  # o Google resolve esses ids até a campanha; o fbclid só diz "Meta"
PLATFORM = {"gclid": "google", "gbraid": "google", "wbraid": "google", "fbclid": "meta", "ctwa_clid": "meta"}
CLICK_CHANNEL = {"gclid": "google", "gbraid": "google", "wbraid": "google",
                 "fbclid": "meta", "ctwa_clid": "meta_ctwa"}  # fbclid indica Meta, não prova mídia paga
EP_CODE = re.compile(r"\[([a-z]+-[a-z]+-[a-z0-9-]+)\]", re.IGNORECASE)
PROTOCOL_ALPHABET = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"  # sem 0/O, 1/I/L: a pessoa digita o que leu
PROTOCOL = re.compile(r"protocolo\s+([A-Z0-9]{5})\b", re.IGNORECASE)
PROTOCOL_TEXT = "Olá! Quero informações (protocolo {})"
SESSION_KEYS = (*UTM_KEYS, "click_id_type", "click_id", "entry_point")


def normalize_phone(raw, wa_id=False):
    """E.164. O wa_id do WhatsApp já vem com o código do país; o telefone do formulário é lido como do Brasil."""
    # shortcut: no formulário, só números do Brasil (10-11 dígitos são DDD + número). Aceitar código de outro país
    # quando houver lead do exterior pelo site.
    digits = re.sub(r"\D", "", raw or "")
    if not wa_id and "+" in (raw or "") and not digits.startswith("55"):
        return None  # "+1 415 555 1234" viraria +55 14...: identidade de outra pessoa
    if not wa_id and len(digits) in (11, 12) and digits.startswith("0"):
        digits = digits[1:]  # 0 de discagem antes do DDD: (011) 98765-4321
    if not wa_id and len(digits) in (10, 11):
        digits = "55" + digits
    # hipótese a confirmar: wa_id de celular antigo pode chegar sem o nono dígito (55 + DDD + 8 dígitos)
    if len(digits) == 12 and digits.startswith("55") and digits[4] in "6789":
        digits = digits[:4] + "9" + digits[4:]
    if digits.startswith("55"):
        return "+" + digits if len(digits) in (12, 13) else None
    return "+" + digits if wa_id and 8 <= len(digits) <= 15 else None  # E.164 tem no máximo 15 dígitos


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
    if all(touch.get(k) for k in UTM_REQUIRED):
        return "observada", f"{touch['utm_source']}/{touch['utm_medium']}"
    if touch.get("ad_id"):
        return "observada", "meta_ctwa"
    if touch.get("click_id_type") in CLICK_CHANNEL:
        return "observada", CLICK_CHANNEL[touch["click_id_type"]]
    if touch.get("qr"):  # ponto de entrada com tipo qr no catálogo
        return "observada", "offline/qr"  # mesmo canal que o /q/ grava (utm_source=offline, utm_medium=qr)
    if touch.get("organic_referral"):
        return "observada", "meta/organic_social"
    if touch.get("organic_search"):
        return "observada", f"{touch['organic_search']}/busca"  # o referrer prova o buscador, não que o clique foi orgânico
    # UTM incompleta não é evidência. 'inferida' existe no schema, mas nenhuma regra a produz nesta demo.
    # "nao_perguntei" é a atendente dizendo que não perguntou: fica no toque para medir, mas não é declaração
    return ("declarada" if touch.get("declared") not in (None, "nao_perguntei") else "desconhecida"), None


def evidence_level(touch):
    """Até onde a evidência observada chega: 'canal', 'campanha' ou 'anuncio'. None quando não é observada."""
    if classify(touch)[0] != "observada":
        return None
    if touch.get("ad_id"):
        return "anuncio"
    if (all(touch.get(k) for k in UTM_REQUIRED) or touch.get("utm_id")
            or touch.get("click_id_type") in CAMPAIGN_CLICKS):
        return "campanha"
    return "canal"  # só o fbclid, post orgânico, QR, busca orgânica


def url_tracking(query):
    """utm_* e click id de uma query string. Valor com "@" (e-mail vazado) é descartado e volta em leaked."""
    params = {k: v[0] for k, v in parse_qs(query).items()}
    leaked = [k for k in (*UTM_KEYS, *CLICK_KEYS) if "@" in params.get(k, "")]
    click = next((k for k in CLICK_KEYS if k in params and k not in leaked), None)
    tracking = {k: None if k in leaked else params.get(k) for k in UTM_KEYS}
    return tracking | {"click_id_type": click, "click_id": params.get(click)}, leaked


def form_touch(payload, catalog, invalid=()):
    """Toque de formulário. Da page_url só saem utm_* e click ids: o resto (onde pode vazar e-mail) não entra.
    invalid: campos que não deu para ler; viram uma pendência payload_invalido, só com os nomes."""
    url = urlsplit(payload.get("page_url") or "")
    tracking, wrong = url_tracking(url.query)
    click = tracking["click_id_type"]
    entry_points = catalog["entry_points"]
    # o path só identifica o ponto numa página do próprio site (com ou sem www.): evil.exemplo/lp/micro-sp não é a LP
    code = next((c for c, ep in entry_points.items() if ep.get("path") == url.path.rstrip("/")
                 and (url.hostname or "").removeprefix("www.") in catalog["dominios"]), None)
    ep = entry_points.get(code, {})
    off_catalog = [k for k, values in (("unit", catalog["units"]), ("product", catalog["products"]))
                   if payload.get(k) and payload[k] not in values]
    utms = {k: tracking[k] for k in UTM_KEYS}
    allowed = {"utm_source": catalog["utm_sources"], "utm_medium": catalog["utm_mediums"]}
    wrong += [k for k, values in allowed.items() if utms[k] and utms[k] not in values]
    # {unidade}-{produto}-{objetivo}[-livre], o formato do gerador de links: o sufixo separa duas campanhas de mesma
    # base, e o custo se junta pelo utm_id (id da campanha na plataforma), não pelo nome
    bases = [f"{u}-{p}-{o}" for u in catalog["units"] for p in catalog["products"] for o in catalog["objetivos_campanha"]]
    if (campaign := utms["utm_campaign"]) and not any(campaign == b or campaign.startswith(b + "-") for b in bases):
        wrong.append("utm_campaign")
    missing = [k for k in UTM_REQUIRED if not utms[k]] if any(utms.values()) else []
    bare = not (any(utms.values()) or click)
    referrer_host = urlsplit(payload.get("referrer") or "").hostname
    # sem parâmetro, referrer de buscador é busca orgânica (canal). Referrer de app (l.instagram.com) não entra: pode
    # ser anúncio que perdeu o parâmetro, como o do Diego
    engine = next((p.split(".")[0] for p in catalog["referrers_busca"]
                   if bare and fnmatch((referrer_host or "").removeprefix("www."), p)), None)
    touch = tracking | {
        "contact_channel": "form",
        "entry_point": code,
        "declared": payload.get("how_heard"),
        # ausente cai no do ponto de entrada; fora do catálogo não herda (ex.: "campinas" numa LP de SP), fica
        # desconhecido e vira pendência
        "unit": None if "unit" in off_catalog else payload.get("unit") or ep.get("unit"),
        "product": None if "product" in off_catalog else payload.get("product") or ep.get("product"),
        "organic_search": engine,
        # QA e homologação marcam o lead: fica fora do relatório e das conversões
        "is_test": bool(payload.get("is_test")) or parse_qs(url.query).get("teste") == ["1"],
    }
    issues = []
    if bad := sorted({*invalid, *off_catalog}):
        issues.append(("payload_invalido", code, {"campos": bad}))
    if wrong or missing:
        # fora da convenção fica como veio (é o que o link trouxe) e vira pendência para corrigir o link
        issues.append(("utm_fora_do_padrao", code, {"campos": sorted(wrong), "faltando": missing}))
    if not code:
        issues.append(("ep_desconhecido", None, {"host": url.hostname, "path": url.path}))
    # olha a falta de parâmetro, não o origin_type: um "como conheceu" preenchido também esconderia a perda. Em ponto
    # pago, só o canal (ex.: só fbclid, ou busca orgânica: LP paga não recebe orgânico de propósito) também é perda
    so_canal = evidence_level(touch) == "canal"
    if ep.get("exige_parametros") and (so_canal or bare):
        # sem referrer é retorno direto (favorito, link digitado): também é origem perdida, mas o remédio é guardar o
        # clique entre visitas, não corrigir o link do anúncio. Por isso a pendência tem outro nome
        kind = "parametros_perdidos" if so_canal or referrer_host else "retorno_sem_parametro"
        issues.append((kind, code, {"referrer_host": referrer_host} | ({"motivo": "so_canal"} if so_canal else {})))
    return touch, issues


def protocol_code(text):
    match = PROTOCOL.search(text or "")
    return match.group(1).upper() if match else None


def new_protocol(rng):
    return "".join(rng.choice(PROTOCOL_ALPHABET) for _ in range(5))


def whatsapp_touch(text, referral, catalog, invalid=(), session=None, at=None):
    """Toque de WhatsApp. Origem só com evidência: referral (anúncio CTWA ou post), protocolo de uma leitura do /q/
    (session, a click_session do protocolo do texto; at, a hora da mensagem) ou código [ep] cadastrado no texto."""
    touch = {"contact_channel": "whatsapp"}
    issues = [("payload_invalido", None, {"campos": sorted(set(invalid))})] if invalid else []
    # sem source_type, o source_id basta para ser anúncio; sem nenhum dos dois o referral não diz nada
    kind = (referral or {}).get("source_type") or ("ad" if (referral or {}).get("source_id") else None)
    if kind and kind != "ad":
        # post não é anúncio: Meta orgânico, sem ad_id nem click id de campanha paga. O protocolo abaixo ainda vale e,
        # válido, vence o post em classify (a sessão traz UTM, click id ou QR)
        touch["organic_referral"] = True
    elif kind:
        ad = catalog["ads"].get(referral.get("source_id"), {})
        if not ad:
            # o ad_id continua sendo evidência (observada), mas sem campanha, unidade nem produto: pendência
            issues.append(("anuncio_desconhecido", None, {"ad_id": referral.get("source_id")}))
        touch |= {
            "ad_id": referral.get("source_id"),
            "click_id_type": "ctwa_clid" if referral.get("ctwa_clid") else None,
            "click_id": referral.get("ctwa_clid"),
            "utm_campaign": ad.get("campaign"),
            "entry_point": ad.get("entry_point"),
            "unit": ad.get("unit"),
            "product": ad.get("product"),
        }
    if kind != "ad" and (code := protocol_code(text)):
        days = timedelta(days=catalog["validade_protocolo_dias"])
        # protocolo já usado por outra pessoa (mensagem repassada, print do link) não prova a leitura de quem mandou
        reused = bool(session and session.get("outra_pessoa"))
        if session and not reused and at <= datetime.fromisoformat(session["created_at"]) + days:
            # a mensagem herda o clique gravado na leitura: o clique da LP ou do QR não se perde no WhatsApp
            ep = catalog["entry_points"].get(session["entry_point"], {})
            touch |= {k: session[k] for k in SESSION_KEYS} | {
                "click_session_id": session["id"], "unit": ep.get("unit"), "product": ep.get("product")}
        else:
            # vencido, inexistente (digitado errado, inventado) ou reutilizado: não vira origem
            issues.append(("protocolo_invalido", session and session["entry_point"],
                           {"protocolo": code} | ({"motivo": "reutilizado"} if reused else {})))
    if match := EP_CODE.search(text or ""):
        code = match.group(1).lower()
        if ep := catalog["entry_points"].get(code):
            touch |= {"entry_point": code, "unit": touch.get("unit") or ep.get("unit"),
                      "product": touch.get("product") or ep.get("product")}
        else:
            # código que ninguém cadastrou não vira origem: vira pendência para achar o material impresso
            issues.append(("ep_desconhecido", code, {}))
    touch["qr"] = catalog["entry_points"].get(touch.get("entry_point"), {}).get("tipo") == "qr"
    return touch, issues


def sale_problem(sale, opportunity, catalog):
    """Motivo para estacionar a venda, ou None. Na dúvida não fecha oportunidade nenhuma."""
    if opportunity is None:
        return "venda_sem_oportunidade"
    if opportunity["status"] == "ganha":
        return "venda_em_oportunidade_ganha"  # outra venda na mesma oportunidade dobraria a receita: alguém confere
    if opportunity["status"] == "perdida":
        return "venda_divergente"  # expirou: ganhar a velha devolveria o crédito ao toque antigo; alguém religa
    known = sale["product"] in catalog["products"] and sale["unit"] in catalog["units"]
    # campo da oportunidade ainda a_definir/desconhecida não diverge: é a venda que o qualifica
    if not known or any(opportunity[k] not in UNKNOWN and sale[k] != opportunity[k] for k in ("product", "unit")):
        return "venda_divergente"
    return None


def conversion(click_id_type, click_id, sensitive, consented, expired):
    """Linha da outbox de conversão: a venda volta para a plataforma do clique. Bloqueada não copia o click id."""
    row = {"platform": PLATFORM[click_id_type], "click_id_type": None, "click_id": None}
    if sensitive:
        # produto ligado a saúde nunca vira sinal para plataforma de anúncio, com ou sem consentimento
        return row | {"status": "bloqueado_sensivel"}
    if not consented:
        return row | {"status": "bloqueado_consentimento"}
    if expired:
        return row | {"status": "expirado"}  # click id velho demais para a plataforma atribuir
    row |= {"click_id_type": click_id_type, "click_id": click_id}
    # vale o lead, não o ponto de entrada. Quem casa o clique com o anúncio é a própria plataforma: um fbclid sozinho
    # não prova a campanha para a NOSSA atribuição, mas é o sinal que a Meta usa; segurar o evento só tira sinal
    return row | {"status": "pendente"}


def release_status(leads, rules):
    """Status de liberação de um ponto de entrada: replay dos leads [(occurred_at, com_problema)] em ordem, sem estado
    guardado. Reprovar exige menos evidência que aprovar; liberado só volta a bloquear com evidência forte."""
    window, status = rules["tolerancia"][-1][0], "amostra_insuficiente"  # janela = maior faixa da tabela
    for i in range(1, len(leads) + 1):
        if status == "liberado":
            last = [p for _, p in leads[max(0, i - rules["rebloqueio_janela"]):i]]
            seguidos = rules["rebloqueio_seguidos"]
            if sum(last) >= rules["rebloqueio_problemas"] or (len(last) >= seguidos and all(last[-seguidos:])):
                status = "bloqueado"
            continue
        recent = leads[max(0, i - window):i]
        problems = sum(p for _, p in recent)
        if len(recent) < rules["min_leads"]:
            status = "bloqueado" if problems / len(recent) > rules["max_taxa_problema"] else "amostra_insuficiente"
        # tolerância: maior nº de problemas que ainda garante cobertura real >= 90% com 95% de confiança (Clopper-Pearson)
        elif problems > [k for n, k in rules["tolerancia"] if n <= len(recent)][-1]:
            status = "bloqueado"
        else:
            # passa na tabela, mas só libera com dias suficientes entre o primeiro e o último lead da janela
            days = (datetime.fromisoformat(recent[-1][0]) - datetime.fromisoformat(recent[0][0])).days
            status = "liberado" if days >= rules["min_dias"] else "amostra_insuficiente"
    return status


STUDENT_QUEUE = "atendimento-aluna"  # quem já comprou e fala sem produto: dúvida de aluna, não lead
TEST_QUEUE = "teste"  # lead de QA percorre o fluxo inteiro, mas não chega à vendedora
PATIENT_PRODUCT = "paciente_modelo"  # atendimento de paciente, não venda de curso: outro funil, outra fila


def queue_for(unit, product=None):
    # unidade desconhecida vai para a triagem do bot (IA simulada): pergunta produto, unidade e "como conheceu".
    # A resposta voltaria como toque declarado, nunca como observado.
    if unit in (None, "desconhecida"):
        return "triagem-bot"
    return f"agenda-{unit}" if product == PATIENT_PRODUCT else f"comercial-{unit}"
