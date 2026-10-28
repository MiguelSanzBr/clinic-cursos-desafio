"""API da demo. Rotas finas: validam a entrada, aplicam as regras de domain e gravam via db."""
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Literal

from fastapi import FastAPI, HTTPException
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from app import db, domain

ROOT = Path(__file__).resolve().parents[1]
Id = Annotated[str, Field(min_length=1)]


class Inbound(BaseModel):
    model_config = ConfigDict(extra="allow")  # o recibo guarda o payload inteiro, inclusive campos que a demo não usa


class FormEvent(Inbound):
    submission_id: Id
    submitted_at: AwareDatetime
    name: str | None = None
    email: str | None = None
    phone: str | None = None
    product: str | None = None
    unit: str | None = None
    page_url: str | None = None
    referrer: str | None = None
    how_heard: Literal["instagram", "google", "indicacao", "amigo", "outro"] | None = None
    consent_marketing: bool | None = None  # ausente não vira "não consentiu"


class WaMessage(Inbound):
    id: Id
    from_: str = Field(alias="from")
    timestamp: int
    text: dict | None = None
    referral: dict | None = None


class WaValue(Inbound):
    contacts: list[dict] = []
    messages: list[WaMessage] = []


class WaChange(Inbound):
    value: WaValue


class WaEntry(Inbound):
    changes: list[WaChange]


class WaWebhook(Inbound):
    entry: list[WaEntry]


class ErpSale(Inbound):
    erp_sale_id: Id
    crm_opportunity_id: int | None = None  # ausente vai para quarentena, não 422
    product: str | None = None
    unit: str | None = None
    amount_cents: int = Field(ge=0)
    confirmed_at: AwareDatetime


def found(result):
    if result is None:
        raise HTTPException(404, "não encontrado")
    return result


def create_app(db_path):
    conn = db.connect(db_path)
    catalog = json.loads((ROOT / "data" / "catalog.json").read_text())
    app = FastAPI(title="Clinic Cursos: demo de rastreamento")
    app.state.conn = conn

    @app.post("/events/form")
    def form_event(body: FormEvent):
        ids = domain.identifiers(body.phone, body.email)
        if not ids:
            raise HTTPException(422, "formulário sem telefone nem e-mail válido")
        # shortcut: o payload do formulário (com dado pessoal) expira em 30 dias em produção (não implementado)
        payload = body.model_dump(mode="json")
        touch, issues = domain.form_touch(payload, catalog)
        return db.record_contact(conn, "form", body.submission_id, payload, ids, body.name, touch,
                                 domain.utc_iso(body.submitted_at), issues, consent=body.consent_marketing)

    @app.post("/events/whatsapp")
    def whatsapp_event(body: WaWebhook):
        # shortcut: não confere a assinatura X-Hub-Signature-256 nem responde ao handshake GET da Meta; obrigatório
        # antes de expor a URL para a Meta.
        values = [change.value for entry in body.entry for change in entry.changes if change.value.messages]
        if not values:
            return {"status": "ignorado"}  # ex.: status de entrega, sem mensagem de cliente
        # shortcut: 1 mensagem por webhook; lote volta 422 e a Meta reenvia. Iterar as mensagens antes de ligar
        # num número real.
        if len(values) > 1 or len(values[0].messages) > 1:
            raise HTTPException(422, "lote com mais de uma mensagem: fora do recorte da demo")
        value, msg = values[0], values[0].messages[0]
        ids = domain.identifiers(msg.from_, None)
        if not ids:
            raise HTTPException(422, "telefone do WhatsApp fora do padrão")
        name = next((c.get("profile", {}).get("name") for c in value.contacts), None)
        touch, issues = domain.whatsapp_touch((msg.text or {}).get("body"), msg.referral, catalog)
        occurred_at = domain.utc_iso(datetime.fromtimestamp(msg.timestamp, UTC))
        # o recibo do WhatsApp não guarda o texto da conversa: só o necessário para reprocessar a origem
        stored = {"wamid": msg.id, "from": msg.from_, "timestamp": msg.timestamp, "referral": msg.referral,
                  "entry_point": touch.get("entry_point")}
        return db.record_contact(conn, "whatsapp", msg.id, body.model_dump(mode="json", by_alias=True), ids, name,
                                 touch, occurred_at, issues, stored=stored)

    @app.post("/events/erp/sale")
    def erp_sale(body: ErpSale):
        return db.record_sale(conn, body.model_dump(mode="json"), domain.utc_iso(body.confirmed_at), catalog)

    @app.get("/people/{person_id}/journey")
    def person_journey(person_id: int):
        return found(db.journey(conn, person_id))

    @app.get("/opportunities/{opportunity_id}")
    def get_opportunity(opportunity_id: int):
        return found(db.opportunity(conn, opportunity_id))

    @app.get("/quality/report")
    def quality_report():
        return db.quality_report(conn, catalog["liberacao"])

    return app


app = create_app(ROOT / "demo.db")  # para `fastapi dev app/main.py`
