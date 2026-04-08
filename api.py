"""
API FastAPI para o Ayvens Carmarket Scraper.
Serve dados de leilões, veículos e histórico de preços.
Emite eventos SSE quando um novo preço é registado.
"""

import asyncio
import json
import logging
import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sse_starlette.sse import EventSourceResponse

from database import get_db

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("api")

MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017/")
MONGO_DB  = os.getenv("MONGO_DB", "ayvens")

db = get_db(MONGO_URI, MONGO_DB)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("API iniciada — MongoDB: %s / %s", MONGO_URI, MONGO_DB)
    yield


app = FastAPI(title="Ayvens Carmarket API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _clean(doc: dict) -> dict:
    """Remove _id do MongoDB para serialização JSON."""
    doc.pop("_id", None)
    return doc


# ---------------------------------------------------------------------------
# Leilões
# ---------------------------------------------------------------------------

@app.get("/api/leiloes")
def get_leiloes():
    """Retorna todos os leilões conhecidos."""
    leiloes = list(db.leiloes.find({}, {"_id": 0}))
    return leiloes


@app.get("/api/leiloes/{sale_id}")
def get_leilao(sale_id: str):
    """Retorna um leilão pelo sale_id."""
    leilao = db.leiloes.find_one({"sale_id": sale_id}, {"_id": 0})
    if not leilao:
        raise HTTPException(status_code=404, detail="Leilão não encontrado")
    return leilao


# ---------------------------------------------------------------------------
# Veículos
# ---------------------------------------------------------------------------

@app.get("/api/leiloes/{sale_id}/veiculos")
def get_veiculos(sale_id: str):
    """Retorna todos os veículos de um leilão."""
    veiculos = list(db.veiculos.find({"sale_id": sale_id}, {"_id": 0}))
    return veiculos


@app.get("/api/veiculos/{lot_id}")
def get_veiculo(lot_id: str):
    """Retorna um veículo pelo lot_id."""
    veiculo = db.veiculos.find_one({"lot_id": lot_id}, {"_id": 0})
    if not veiculo:
        raise HTTPException(status_code=404, detail="Veículo não encontrado")
    return veiculo


@app.get("/api/pesquisa")
def pesquisa(matricula: str = "", lot_id: str = ""):
    """
    Pesquisa um veículo por matrícula ou lot_id.
    Retorna todos os leilões em que esteve e o histórico de preços em cada um.
    """
    if lot_id:
        veiculos = list(db.veiculos.find({"lot_id": lot_id}, {"_id": 0}))
    elif matricula:
        veiculos = list(db.veiculos.find(
            {"matricula": {"$regex": f"^{matricula}$", "$options": "i"}},
            {"_id": 0},
        ))
    else:
        return []
    if not veiculos:
        return []

    resultado = []
    for v in veiculos:
        leilao = db.leiloes.find_one({"sale_id": v["sale_id"]}, {"_id": 0})
        historico = list(
            db.historico_precos.find({"lot_id": v["lot_id"]}, {"_id": 0})
            .sort("timestamp", 1)
        )
        resultado.append({
            "veiculo":  v,
            "leilao":   leilao,
            "historico": historico,
        })

    # Ordenar por data de início do leilão (mais recente primeiro)
    resultado.sort(key=lambda x: x["leilao"].get("data_inicio", "") if x["leilao"] else "", reverse=True)
    return resultado


@app.get("/api/veiculos/{lot_id}/historico")
def get_historico(lot_id: str):
    """Retorna o histórico de preços de um veículo."""
    historico = list(
        db.historico_precos.find({"lot_id": lot_id}, {"_id": 0})
        .sort("timestamp", 1)
    )
    return historico


# ---------------------------------------------------------------------------
# SSE — eventos em tempo real
# ---------------------------------------------------------------------------

@app.get("/api/events")
async def sse_events():
    """
    Stream SSE. Emite um evento 'novo_preco' sempre que
    um novo registo é inserido em historico_precos.
    """
    async def generator():
        # Keep-alive inicial
        yield {"event": "ping", "data": "connected"}

        loop = asyncio.get_event_loop()

        with db.historico_precos.watch([
            {"$match": {"operationType": "insert"}}
        ]) as stream:
            while True:
                # Verificar novo evento sem bloquear o event loop
                change = await loop.run_in_executor(None, _next_change, stream)
                if change:
                    doc = change["fullDocument"]
                    doc.pop("_id", None)
                    # Enriquecer com marca/matrícula
                    veiculo = db.veiculos.find_one(
                        {"lot_id": doc["lot_id"]},
                        {"marca_modelo": 1, "matricula": 1, "sale_id": 1, "offers_count": 1, "is_sold": 1, "is_withdrawn": 1, "_id": 0},
                    )
                    if veiculo:
                        doc.update(veiculo)
                    yield {"event": "novo_preco", "data": json.dumps(doc, default=str)}
                else:
                    # Keep-alive a cada 15s
                    yield {"event": "ping", "data": "alive"}

    return EventSourceResponse(generator())


def _next_change(stream, timeout_ms: int = 15000):
    """Aguarda o próximo change stream event com timeout."""
    return stream.try_next() or stream.next_after_timeout(timeout_ms)
