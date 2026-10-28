"""Roda os cenários de data/eventos.json contra a API, em ordem, e imprime o resultado. Recria demo.db a cada vez."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
(ROOT / "demo.db").unlink(missing_ok=True)  # antes do import: app.main abre demo.db ao ser importado

from fastapi.testclient import TestClient  # noqa: E402

from app import db  # noqa: E402
from app.main import app  # noqa: E402

EVENTOS = json.loads((ROOT / "data" / "eventos.json").read_text())
client = TestClient(app)


def total(table):
    return app.state.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def step(tag, label, path, payload):
    r = client.post(path, json=payload).json()
    details = [f"origem {r['origin_type']}/{r['source_channel'] or '-'}"] if "origin_type" in r else []
    details += [f"fila {r['queue']}"] if r.get("queue") else []
    details += [f"motivo {r['motivo']}"] if r.get("motivo") else []
    details += [f"pessoas={total('person')}", f"toques={total('touchpoint')}"]
    print(f"[{tag}] {label} -> {r['status']} ({', '.join(details)})")
    return r


ana = step("C1", "form-1001 Ana, LP paga com UTM", "/events/form", EVENTOS["C1_form_1001"])
bruna = step("C2", "WhatsApp Bruna, QR da recepção CPS", "/events/whatsapp", EVENTOS["C2a_whatsapp_qr_cps"])
step("C2", "WhatsApp direto, sem código", "/events/whatsapp", EVENTOS["C2b_whatsapp_direto"])
step("C3", "Ana volta por anúncio Click-to-WhatsApp RJ", "/events/whatsapp", EVENTOS["C3_ana_volta_por_anuncio_ctwa"])
step("C3", "Ana de novo pelo mesmo anúncio", "/events/whatsapp", EVENTOS["C3b_ana_mesmo_anuncio_de_novo"])
step("C4", "reenvio form-1001", "/events/form", EVENTOS["C1_form_1001"])
step("C4", "reenvio wamid.QR001", "/events/whatsapp", EVENTOS["C2a_whatsapp_qr_cps"])
step("C5", "ERP confirma ERP-2026-5001 da oportunidade da Ana", "/events/erp/sale",
     EVENTOS["venda_c1"] | {"crm_opportunity_id": ana["opportunity_id"]})
diego = step("FALHA", "form-1003 Diego, LP paga sem UTM (veio de bit.ly)", "/events/form", EVENTOS["falha_form_1003_sem_utm"])
step("DECLARADA", "form-1004 Carla, /contato com 'como conheceu'", "/events/form", EVENTOS["declarada_form_1004"])
step("ORFA", "ERP-2026-5002 para oportunidade 9999", "/events/erp/sale", EVENTOS["venda_orfa"])
step("ORFA", "ERP reenvia ERP-2026-5002 com a oportunidade do Diego", "/events/erp/sale",
     EVENTOS["venda_orfa"] | {"crm_opportunity_id": diego["opportunity_id"]})
step("DIVERGENTE", "ERP-2026-5003 harmonizacao/rj na oportunidade da Bruna (paciente_modelo/cps)", "/events/erp/sale",
     EVENTOS["venda_divergente"] | {"crm_opportunity_id": bruna["opportunity_id"]})

jornada = client.get(f"/people/{ana['person_id']}/journey").json()
jornada["toques"] = [{k: v for k, v in t.items() if v is not None} for t in jornada["toques"]]  # nulos omitidos
print("\nJornada da Ana (GET /people/1/journey, campos nulos omitidos):")
print(json.dumps(jornada, indent=2, ensure_ascii=False))
print("\nRelatório de qualidade (GET /quality/report):")
print(json.dumps(client.get("/quality/report").json(), indent=2, ensure_ascii=False))
print("\nEncaminhamento (db.dispatch_handoffs, atendimento simulado):")
db.dispatch_handoffs(app.state.conn, lambda h: print(f"[ENCAMINHAMENTO] oportunidade {h['opportunity_id']} -> {h['queue']}"))

print("\nOutbox de conversões para as plataformas (não envia nada):")
for c in app.state.conn.execute("SELECT erp_sale_id, platform, status, click_id_type, click_id, event_id"
                                " FROM platform_conversion ORDER BY id"):
    print(f"[CONVERSAO] {c['erp_sale_id']} -> {c['platform']} {c['status']}"
          f" ({c['click_id_type'] or 'sem click id'}={c['click_id'] or '-'}, event_id={c['event_id']})")
