"""Telas do fluxo do case: a API real (app.main) com as telas estáticas em /telas e um log das requisições.

Rodar: uv run uvicorn --app-dir telas servidor:app --port 8010   e abrir http://localhost:8010/telas/
Cada subida começa com o banco vazio (build/telas.db). As telas são de exemplo; regras e dados são os da API.
"""
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "build" / "telas.db"
DB.parent.mkdir(exist_ok=True)
for f in DB.parent.glob("telas.db*"):
    f.unlink()
os.environ["CLINIC_DB"] = str(DB)  # antes do import: app.main abre o banco ao ser importado
sys.path.insert(0, str(ROOT))

from fastapi.responses import FileResponse, JSONResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402

from app.main import app  # noqa: E402

LOG = []


@app.middleware("http")
async def registra(request, call_next):
    response = await call_next(request)
    if not request.url.path.startswith("/telas"):
        query = f"?{request.url.query}" if request.url.query else ""
        LOG.append({"hora": time.strftime("%H:%M:%S"), "metodo": request.method,
                    "caminho": request.url.path + query, "status": response.status_code})
        # o celular simulado não pode seguir o 307 até o wa.me: devolve o destino que a rota real gerou
        if request.headers.get("x-telas") and response.status_code == 307:
            return JSONResponse({"location": response.headers["location"]})
    return response


@app.get("/telas/log")
def log(depois: int = 0):
    return LOG[depois:]


@app.get("/telas/pessoas")
def pessoas():  # a API não lista pessoas; as telas precisam da lista para o atendimento e a jornada
    return [r[0] for r in app.state.conn.execute("SELECT id FROM person ORDER BY id")]


@app.get("/telas/eventos.json")
def eventos():
    return FileResponse(ROOT / "data" / "eventos.json")


app.mount("/telas", StaticFiles(directory=Path(__file__).parent, html=True), name="telas")
