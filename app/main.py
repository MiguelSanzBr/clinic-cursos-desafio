"""API da demo. Rotas finas: validam a entrada, aplicam as regras de domain e gravam via db."""
import json
import os
import secrets
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import parse_qsl, quote, urlencode, urlsplit

from fastapi import FastAPI, HTTPException, Request
from fastapi import Path as PathParam
from fastapi.responses import RedirectResponse
from pydantic import (AfterValidator, AwareDatetime, BaseModel, BeforeValidator, ConfigDict, Field, StrictInt,
                      ValidationError, field_validator)

from app import db, domain

ROOT = Path(__file__).resolve().parents[1]


def idempotency_key(value):
    """1001, 1001.0 e " 1001" são a mesma chave (o ERP pode mandar número): sem isso o mesmo evento vira três."""
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    if isinstance(value, int | float) and not isinstance(value, bool):
        return str(value)
    return value.strip() if isinstance(value, str) else value


OLDEST = datetime(2000, 1, 1, tzinfo=UTC)


def plausible(value):
    """Data (ou segundos Unix) mais de 1 dia à frente do recebimento é relógio errado: pela expiração de 90 dias,
    fecharia como perdida a oportunidade aberta. Antes de 2000 é data nula ("0001-01-01" de ERP), e a conta de datas
    estoura."""
    moment = datetime.fromtimestamp(value, UTC) if isinstance(value, int) else value
    if moment is not None and not OLDEST <= moment <= datetime.now(UTC) + timedelta(days=1):
        raise ValueError("data implausível")
    return value


Id = Annotated[str, BeforeValidator(idempotency_key), Field(min_length=1)]
# o ERP costuma mandar o id como texto: "7" é a oportunidade 7; "7a", true e 7.5 seguem inválidos
OpportunityId = Annotated[Annotated[StrictInt, Field(lt=2**63)] | None,
                          BeforeValidator(lambda v: int(v) if isinstance(v, str) and v.isascii() and v.isdigit() else v)]
SQLITE_MAX = 2**63 - 1  # maior INTEGER do SQLite: id acima disso é 422, nunca 500


class Inbound(BaseModel):
    model_config = ConfigDict(extra="allow")  # o recibo guarda o payload inteiro, inclusive campos que a demo não usa


class FormEvent(Inbound):
    submission_id: Id
    submitted_at: Annotated[AwareDatetime | None, AfterValidator(plausible)] = None
    name: str | None = None
    email: str | None = None
    phone: str | None = Field(None, coerce_numbers_to_str=True)  # 11955550000 sem aspas: sem isso o lead perde o telefone
    product: str | None = None
    unit: str | None = None
    page_url: str | None = None
    referrer: str | None = None
    how_heard: Literal["instagram", "google", "indicacao", "amigo", "outro", "nao_perguntei"] | None = None
    consent_marketing: bool | None = None  # mensagens; ausente não vira "não consentiu"
    consent_ads: bool | None = None  # envio de dados às plataformas de anúncio (outbox de conversões)
    is_test: bool | None = None  # lead de QA; teste=1 na page_url também marca

    @field_validator("how_heard", mode="before")
    @classmethod
    def lowercase(cls, value):
        return value.strip().lower() if isinstance(value, str) else value

    @field_validator("page_url", "referrer")
    @classmethod
    def parseable(cls, value):
        urlsplit(value or "")  # "http://[::1" levanta ValueError: vira campo inválido aqui, não 500 em domain
        return value


class WaText(Inbound):
    body: str | None = None


class WaReferral(Inbound):
    source_type: str | None = None
    source_id: str | None = Field(None, coerce_numbers_to_str=True)
    ctwa_clid: str | None = None


class WaMessage(Inbound):
    id: Id
    from_: str | None = Field(None, alias="from")
    from_user_id: str | None = None  # BSUID: quem adotou nome de usuário pode chegar sem o telefone
    timestamp: Annotated[int | None, AfterValidator(plausible)] = Field(None, ge=0, lt=10**10)  # segundos Unix
    text: WaText | None = None
    referral: WaReferral | None = None


class WaProfile(Inbound):
    name: str | None = None


class WaContact(Inbound):
    profile: WaProfile | None = None


class WaValue(Inbound):
    contacts: list = []
    messages: list = []  # cada mensagem é lida à parte: item ruim num não derruba o lote


class WaChange(Inbound):
    value: WaValue


class WaEntry(Inbound):
    changes: list[WaChange]


class WaWebhook(Inbound):
    entry: list[WaEntry]


class CwSender(Inbound):
    phone_number: str | None = None  # o Chatwoot grava "+" + wa_id
    name: str | None = None


class CwAttributes(Inbound):
    referral: WaReferral | None = None


class CwMessage(Inbound):
    """message_created do Chatwoot (Message#webhook_data). source_id é o wamid da Meta."""
    source_id: Id
    content: str | None = None
    created_at: Annotated[AwareDatetime | None, AfterValidator(plausible)] = None  # hora do Chatwoot, não da Meta
    content_attributes: CwAttributes | None = None
    sender: CwSender | None = None


# booleano não é id nem valor: no int comum, true viraria a oportunidade 1
class ErpSale(Inbound):
    erp_sale_id: Id
    crm_opportunity_id: OpportunityId = None  # ausente ou fora do INTEGER do SQLite: quarentena
    product: str | None = None  # ausente ou fora do catálogo: quarentena
    unit: str | None = None
    amount_cents: StrictInt | None = Field(None, ge=0, lt=2**63)
    confirmed_at: Annotated[AwareDatetime | None, AfterValidator(plausible)] = None


class LabelEvent(Inbound):
    event_id: Id
    phone: str | None = None
    label: Literal["em_negociacao", "perdida"] | None = None
    crm_opportunity_id: OpportunityId = None  # atributo da conversa, gravado pelo núcleo
    origin_system: str | None = None


def lenient(model, raw, key):
    """Lê o evento pelo modelo sem rejeitá-lo: campo inválido é descartado e volta só pelo nome, para virar pendência.
    Só a chave de idempotência dá 422: sem ela não há como gravar o recibo nem deduplicar o reenvio."""
    try:
        return model.model_validate(raw), []
    except ValidationError as e:
        bad = sorted({str(err["loc"][0]) for err in e.errors()})
    if key in bad:
        raise HTTPException(422, f"{key} ausente ou inválido")
    return model.model_validate({k: v for k, v in raw.items() if k not in bad}), bad


def found(result):
    if result is None:
        raise HTTPException(404, "não encontrado")
    return result


def create_app(db_path):
    conn = db.connect(db_path)
    catalog = json.loads((ROOT / "data" / "catalog.json").read_text())
    app = FastAPI(title="Clinic Cursos: demo de rastreamento")
    app.state.conn = conn
    app.state.rng = secrets.SystemRandom()  # protocolo do /q/; a demo troca por um Random com semente

    validity = catalog["validade_oportunidade_dias"]

    @app.post("/events/form")
    def form_event(body: dict):
        form, invalid = lenient(FormEvent, body, "submission_id")
        ids = domain.identifiers(form.phone, form.email)
        # identificador presente e ilegível é pendência; sem nenhum válido, os dois contam (o recibo vai à quarentena)
        invalid += [k for k in ("phone", "email") if k not in dict(ids) and (getattr(form, k) or not ids)]
        invalid += [] if form.submitted_at else ["submitted_at"]
        touch, issues = domain.form_touch(form.model_dump(), catalog, invalid)
        # shortcut: o payload do formulário (com dado pessoal) expira em 30 dias em produção (não implementado)
        return db.record_contact(conn, "form", form.submission_id, body | {"submission_id": form.submission_id},
                                 ids, form.name, touch,
                                 domain.utc_iso(form.submitted_at or datetime.now(UTC)), issues, validity,
                                 consent={"marketing": form.consent_marketing, "ads": form.consent_ads})

    @app.post("/events/whatsapp")
    def whatsapp_event(body: WaWebhook):
        # shortcut: não confere a assinatura X-Hub-Signature-256 nem responde ao handshake GET da Meta; obrigatório
        # antes de expor a URL para a Meta.
        batch = []
        for entry in body.entry:
            for change in entry.changes:
                for raw in change.value.messages:
                    # item que nem é objeto, ou sem wamid, não tem recibo: vira só pendência e o resto do lote segue.
                    # Um 422 faria a Meta reenviar o lote inteiro para sempre, e a mensagem boa nunca entraria
                    try:
                        batch.append((change.value, *lenient(WaMessage, raw, "id")) if isinstance(raw, dict)
                                     else {"campos": ["messages"]})
                    except HTTPException:
                        batch.append({"campos": ["id"]})
        if not batch:
            return {"status": "ignorado"}  # ex.: status de entrega, sem mensagem de cliente
        # cada mensagem com o seu recibo (wamid): o reenvio do lote pela Meta deduplica uma a uma
        results = [whatsapp_message(*item) if isinstance(item, tuple) else db.record_skipped(conn, "whatsapp", item)
                   for item in batch]
        return results[0] if len(results) == 1 else {"status": "lote", "resultados": results}

    def whatsapp_message(value, msg, invalid):
        phone = domain.normalize_phone(msg.from_, wa_id=True)
        ids = [(kind, value) for kind, value in (("phone", phone), ("bsuid", msg.from_user_id)) if value]
        contact = next((c for c in value.contacts if isinstance(c, dict) and (
            (msg.from_ and c.get("wa_id") == msg.from_) or (msg.from_user_id and c.get("user_id") == msg.from_user_id))), {})
        contact, bad = lenient(WaContact, contact, None)
        name = contact.profile.name if contact.profile else None
        text = msg.text.body if msg.text else None
        referral = msg.referral.model_dump(exclude_unset=True) if msg.referral else None  # o que veio, já tipado
        moment = datetime.fromtimestamp(msg.timestamp, UTC) if msg.timestamp is not None else datetime.now(UTC)
        with db.LOCK:  # protocolo lido e toque gravado sob a mesma trava: duas pessoas não herdam o mesmo clique
            return whatsapp_record(msg, name, text, referral, moment, ids, invalid + bad + ([] if ids else ["from"]))

    def whatsapp_record(msg, name, text, referral, moment, ids, invalid):
        session = db.click_session(conn, domain.protocol_code(text), ids)
        touch, issues = domain.whatsapp_touch(text, referral, catalog, invalid, session, moment)
        # hash sobre o conteúdo, não sobre o envelope: a mesma mensagem com outro nome de perfil, ou repassada pelo
        # Chatwoot (com a hora dele), é duplicada e não conflito. O recibo não guarda o texto nem o nome do perfil.
        content = {"wamid": msg.id, "from": msg.from_, "text": text, "referral": referral}
        stored = {"wamid": msg.id, "from": msg.from_, "timestamp": msg.timestamp, "referral": referral,
                  "entry_point": touch.get("entry_point")}
        return db.record_contact(conn, "whatsapp", msg.id, content, ids, name, touch,
                                 domain.utc_iso(moment), issues, validity, stored=stored)

    @app.post("/events/chatwoot")
    def chatwoot_event(body: dict):
        # o Chatwoot repassa a mensagem que recebeu da Meta: mesmo fluxo e mesmo recibo (wamid) do WhatsApp, então a
        # mesma mensagem pelas duas rotas é duplicada (segunda via quando um dos webhooks falha)
        # shortcut: aceita qualquer remetente; antes de expor, restringir à rede do Chatwoot ou exigir segredo na URL
        if (body.get("event"), body.get("message_type")) != ("message_created", "incoming"):
            return {"status": "ignorado"}  # resposta da atendente, nota, outros eventos: não é contato
        cw, invalid = lenient(CwMessage, body, "source_id")
        sender = cw.sender or CwSender()
        wa_id = sender.phone_number.lstrip("+") if sender.phone_number else None
        msg, bad = lenient(WaMessage, {
            "id": cw.source_id, "from": wa_id, "text": {"body": cw.content},
            "timestamp": int(cw.created_at.timestamp()) if cw.created_at else None,
            "referral": cw.content_attributes and cw.content_attributes.referral}, "id")
        value = WaValue(contacts=[{"wa_id": wa_id, "profile": {"name": sender.name}}])
        return whatsapp_message(value, msg, invalid + bad)

    @app.post("/events/erp/sale")
    def erp_sale(body: dict):
        sale, invalid = lenient(ErpSale, body, "erp_sale_id")
        invalid = sorted({*invalid, *(k for k in ("amount_cents", "confirmed_at") if getattr(sale, k) is None)})
        return db.record_sale(conn, body | {"erp_sale_id": sale.erp_sale_id}, sale.model_dump(), invalid, catalog)

    @app.post("/events/atendimento")
    def atendimento_event(body: dict):
        # o atendimento (Chatwoot, simulado) avisa a etiqueta da conversa: o segundo sentido, atendimento -> CRM
        event, invalid = lenient(LabelEvent, body, "event_id")
        phone = domain.normalize_phone(event.phone, wa_id=True)  # o Chatwoot guarda o telefone com o país
        # o telefone só é obrigatório sem o id da oportunidade: quem só tem BSUID chega sem ele
        invalid += [k for k, v in (("phone", phone or event.crm_opportunity_id), ("label", event.label)) if not v]
        return db.record_label(conn, body | {"event_id": event.event_id}, event.event_id, phone, event.label,
                               event.crm_opportunity_id, event.origin_system == "nucleo", sorted(set(invalid)))

    @app.api_route("/q/{entry_point}", methods=["GET", "HEAD"])
    def redirect(entry_point: str, request: Request):
        # QR e links apontam para cá: a leitura grava o clique com um protocolo, que segue no texto do WhatsApp
        ep = catalog["entry_points"].get(entry_point, {})
        if "q" not in ep:
            raise HTTPException(404, "ponto de entrada sem /q/")
        query = request.url.query
        # HEAD (verificador de link) e o GET do robô que monta a prévia do link numa conversa não são leitura: sem sessão
        # nem protocolo, para não inflar as leituras
        # shortcut: robô reconhecido só pelo User-Agent da lista; o que se passa por navegador conta leitura
        agent = request.headers.get("user-agent", "").lower()
        preview = request.method == "HEAD" or any(bot.lower() in agent for bot in catalog["robos_previa"])
        protocol = None if preview else db.record_click(conn, entry_point, domain.url_tracking(query)[0], app.state.rng)
        if ep["q"] == "whatsapp":
            text = f"?text={quote(domain.PROTOCOL_TEXT.format(protocol))}" if protocol else ""
            return RedirectResponse(f"https://wa.me/{catalog['whatsapp']}{text}", 307)
        # só os parâmetros de rastreio seguem: email= ou nome= no link não vão parar na URL da LP (nem no log do site)
        kept = urlencode([(k, v) for k, v in parse_qsl(query) if k in (*domain.UTM_KEYS, *domain.CLICK_KEYS) and "@" not in v])
        return RedirectResponse(catalog["site"] + ep["path"] + (f"?{kept}" if kept else ""), 307)

    # shortcut: as leituras também passam pelo LOCK da conexão compartilhada; com Postgres, conexão por requisição
    @app.get("/people/{person_id}/journey")
    def person_journey(person_id: Annotated[int, PathParam(le=SQLITE_MAX)]):
        with db.LOCK:
            return found(db.journey(conn, person_id))

    @app.get("/opportunities/{opportunity_id}")
    def get_opportunity(opportunity_id: Annotated[int, PathParam(le=SQLITE_MAX)]):
        with db.LOCK:
            return found(db.opportunity(conn, opportunity_id))

    @app.get("/quality/report")
    def quality_report():
        with db.LOCK:
            return db.quality_report(conn, catalog)

    return app


# para `fastapi dev app/main.py`; o pytest troca por :memory: (tests/conftest.py) para não criar demo.db
app = create_app(os.environ.get("CLINIC_DB", ROOT / "demo.db"))
