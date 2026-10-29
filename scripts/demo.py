"""Roda os cenários de data/eventos.json contra a API, em ordem, e imprime o resultado. Recria demo.db a cada vez."""
import copy
import json
import random
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
(ROOT / "demo.db").unlink(missing_ok=True)  # antes do import: app.main abre demo.db ao ser importado

from fastapi.testclient import TestClient  # noqa: E402

from app import db  # noqa: E402
from app.main import app  # noqa: E402

EVENTOS = json.loads((ROOT / "data" / "eventos.json").read_text())
client = TestClient(app)
app.state.rng = random.Random(2026)  # protocolo do /q/ com semente: a saída não muda entre execuções


def total(table):
    return app.state.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def step(tag, label, path, payload):
    r = client.post(path, json=payload).json()
    origin = f"{r.get('origin_type')}:{r.get('source_channel')}" if r.get("source_channel") else r.get("origin_type")
    details = [f"origem {origin}"] if origin else []
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
step("C4", "mensagem da Ana repassada pelo Chatwoot (segunda via)", "/events/chatwoot", EVENTOS["chatwoot_ana_ctwa"])
step("C5", "ERP confirma ERP-2026-5001 da oportunidade da Ana", "/events/erp/sale",
     EVENTOS["venda_c1"] | {"crm_opportunity_id": ana["opportunity_id"]})
opp = client.get(f"/opportunities/{ana['opportunity_id']}").json()
t = opp["toque_atribuido"]  # a venda continua ligada à campanha do primeiro toque observado
print(f"[C5] oportunidade {opp['id']} {opp['status']} com {opp['vendas'][0]['erp_sale_id']}; origem atribuída "
      f"{t['origin_type']}:{t['source_channel']}, {t['utm_campaign']}, {t['entry_point']}")
diego = step("FALHA", "form-1003 Diego, LP paga sem UTM (link do anúncio sem parâmetros)", "/events/form", EVENTOS["falha_form_1003_sem_utm"])
step("DECLARADA", "form-1004 Carla, /contato com 'como conheceu'", "/events/form", EVENTOS["declarada_form_1004"])
step("ORFA", "ERP-2026-5002 para oportunidade 9999", "/events/erp/sale", EVENTOS["venda_orfa"])
step("ORFA", "ERP reenvia ERP-2026-5002 com a oportunidade do Diego", "/events/erp/sale",
     EVENTOS["venda_orfa"] | {"crm_opportunity_id": diego["opportunity_id"]})
step("DIVERGENTE", "ERP-2026-5003 harmonizacao/rj na oportunidade da Bruna (paciente_modelo/cps)", "/events/erp/sale",
     EVENTOS["venda_divergente"] | {"crm_opportunity_id": bruna["opportunity_id"]})
eduardo = step("CONSENTIMENTO", "form-1005 Eduardo, /contato com gclid, aceita mensagens mas não anúncios", "/events/form",
               EVENTOS["consentimento_form_1005"])
step("CONSENTIMENTO", "ERP confirma ERP-2026-5004 da oportunidade do Eduardo", "/events/erp/sale",
     EVENTOS["venda_sem_consentimento"] | {"crm_opportunity_id": eduardo["opportunity_id"]})
leitura = client.get("/q/qr-cps-recepcao-01?utm_source=offline&utm_medium=qr&utm_campaign=cps-paciente_modelo-paciente",
                     follow_redirects=False)
texto = parse_qs(urlsplit(leitura.headers["location"]).query)["text"][0]
print(f"[Q] leitura de /q/qr-cps-recepcao-01 com UTM -> {leitura.status_code} wa.me, texto \"{texto}\"")
mensagem = copy.deepcopy(EVENTOS["Q1_whatsapp_protocolo"])
mensagem["entry"][0]["changes"][0]["value"]["messages"][0]["text"]["body"] = texto  # a pessoa envia o texto pronto
fernanda = step("Q", "WhatsApp da Fernanda com o protocolo da leitura", "/events/whatsapp", mensagem)
etiqueta = client.post("/events/atendimento", json=EVENTOS["atendimento_em_negociacao"]).json()
estagio = client.get(f"/opportunities/{etiqueta['opportunity_id']}").json()["stage"]
print(f"[ATENDIMENTO] etiqueta em_negociacao na conversa da Carla -> {etiqueta['status']}"
      f" (oportunidade {etiqueta['opportunity_id']}, estágio {estagio})")
eco = client.post("/events/atendimento", json=EVENTOS["atendimento_em_negociacao"] | {"event_id": "cw-evt-0002",
                                                                                     "origin_system": "nucleo"}).json()
print(f"[ATENDIMENTO] a mesma etiqueta gravada pelo núcleo volta (eco) -> {eco['status']}")

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
          f" ({(c['click_id_type'] + '=' + c['click_id']) if c['click_id'] else 'click id não copiado'}, event_id={c['event_id']})")
