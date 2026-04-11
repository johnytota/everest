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
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from sse_starlette.sse import EventSourceResponse

from database import get_db

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("api")

MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017/")
MONGO_DB  = os.getenv("MONGO_DB", "ayvens")

db = get_db(MONGO_URI, MONGO_DB)

# ---------------------------------------------------------------------------
# Fila de eventos SSE — uma Queue por cliente ligado
# ---------------------------------------------------------------------------

_sse_clients: list[asyncio.Queue] = []


def _broadcast(evento: dict) -> None:
    """Envia um evento para todos os clientes SSE ligados."""
    for q in _sse_clients:
        try:
            q.put_nowait(evento)
        except asyncio.QueueFull:
            pass


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
    """Retorna todos os leilões conhecidos com estatísticas de licitações."""
    leiloes = list(db.leiloes.find({}, {"_id": 0}))

    # Total de veículos por sale_id (via participacoes)
    pipeline_total = [
        {"$group": {"_id": "$sale_id", "total": {"$sum": 1}}}
    ]
    totais = {r["_id"]: r["total"] for r in db.participacoes.aggregate(pipeline_total)}

    # Veículos com pelo menos um bid WS — apenas dos leilões conhecidos
    sale_ids_conhecidos = [l["sale_id"] for l in leiloes]
    pipeline_ws = [
        {"$match": {"sale_id": {"$in": sale_ids_conhecidos}}},
        {"$group": {"_id": {"sale_id": "$sale_id", "lot_id": "$lot_id"}}},
        {"$group": {"_id": "$_id.sale_id", "com_ws": {"$sum": 1}}},
    ]
    ws_stats = {r["_id"]: r["com_ws"] for r in db.licitacoes_websocket_signalr.aggregate(pipeline_ws)}

    for l in leiloes:
        l["stats_total"]     = totais.get(l["sale_id"], 0)
        l["stats_licitados"] = ws_stats.get(l["sale_id"], 0)

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
    """Retorna todos os veículos de um leilão (join participacoes + veiculos)."""
    pipeline = [
        {"$match": {"sale_id": sale_id}},
        {"$lookup": {
            "from": "veiculos",
            "localField": "veiculo_id",
            "foreignField": "_id",
            "as": "v",
        }},
        {"$unwind": "$v"},
        {"$replaceRoot": {"newRoot": {"$mergeObjects": ["$v", "$$ROOT"]}}},
        {"$unset": ["v", "_id"]},
    ]
    return list(db.participacoes.aggregate(pipeline))


@app.get("/api/leiloes/{sale_id}/ws_lots")
def get_ws_lots(sale_id: str):
    """Retorna os lot_ids que têm pelo menos um bid WS neste leilão."""
    # Garantir que só devolvemos lot_ids que pertencem a este leilão
    lot_ids_leilao = db.participacoes.distinct("lot_id", {"sale_id": sale_id})
    lots = db.licitacoes_websocket_signalr.distinct("lot_id", {
        "sale_id": sale_id,
        "lot_id": {"$in": lot_ids_leilao},
    })
    return lots


@app.get("/api/veiculos/id/{veiculo_id}")
def get_veiculo_by_id(veiculo_id: int):
    """Retorna um veículo pelo veiculo_id (ID interno), com a participação ativa ou mais recente."""
    # Preferir participação em leilão ativo (estado=3), senão a mais recente
    leiloes_ativos = {l["sale_id"] for l in db.leiloes.find({"estado": 3}, {"sale_id": 1})}
    participacoes = list(db.participacoes.find({"veiculo_id": veiculo_id}).sort("scrape_ts", -1))
    if not participacoes:
        raise HTTPException(status_code=404, detail="Veículo não encontrado")
    part = next((p for p in participacoes if p.get("sale_id") in leiloes_ativos), participacoes[0])

    veiculo = db.veiculos.find_one({"_id": veiculo_id}, {"_id": 0})
    if not veiculo:
        raise HTTPException(status_code=404, detail="Veículo não encontrado")
    return {**veiculo, **{k: v for k, v in part.items() if k != "_id"}}


@app.get("/api/veiculos/{lot_id}")
def get_veiculo(lot_id: str):
    """Retorna um veículo pelo lot_id (join participacao + veiculo)."""
    pipeline = [
        {"$match": {"lot_id": lot_id}},
        {"$lookup": {
            "from": "veiculos",
            "localField": "veiculo_id",
            "foreignField": "_id",
            "as": "v",
        }},
        {"$unwind": "$v"},
        {"$replaceRoot": {"newRoot": {"$mergeObjects": ["$v", "$$ROOT"]}}},
        {"$unset": ["v", "_id"]},
    ]
    resultado = list(db.participacoes.aggregate(pipeline))
    if not resultado:
        raise HTTPException(status_code=404, detail="Veículo não encontrado")
    return resultado[0]


@app.get("/api/pesquisa")
def pesquisa(matricula: str = "", lot_id: str = ""):
    """
    Pesquisa um veículo por matrícula ou lot_id.
    Retorna todos os leilões em que esteve e o histórico de preços em cada um.
    """
    if lot_id:
        part = db.participacoes.find_one({"lot_id": lot_id}, {"veiculo_id": 1})
        if not part:
            return []
        veiculo_id = part["veiculo_id"]
    elif matricula:
        v = db.veiculos.find_one(
            {"matricula": {"$regex": f"^{matricula}$", "$options": "i"}},
            {"_id": 1},
        )
        if not v:
            return []
        veiculo_id = v["_id"]
    else:
        return []

    # Todas as participações deste veículo
    participacoes = list(db.participacoes.find({"veiculo_id": veiculo_id}, {"_id": 0}))
    veiculo_doc = db.veiculos.find_one({"_id": veiculo_id}, {"_id": 0})

    resultado = []
    for p in participacoes:
        leilao = db.leiloes.find_one({"sale_id": p["sale_id"]}, {"_id": 0})
        historico = list(
            db.historico_precos.find({"lot_id": p["lot_id"]}, {"_id": 0})
            .sort("timestamp", 1)
        )
        resultado.append({
            "veiculo":   {**veiculo_doc, **p},
            "leilao":    leilao,
            "historico": historico,
        })

    resultado.sort(key=lambda x: x["leilao"].get("data_inicio", "") if x["leilao"] else "", reverse=True)
    return resultado


@app.get("/api/veiculos/{lot_id}/ws_bids")
def get_ws_bids(lot_id: str):
    """Retorna as licitações recebidas via WebSocket SignalR (coleção temporária de validação)."""
    bids = list(
        db.licitacoes_websocket_signalr
        .find({"lot_id": lot_id}, {"_id": 0})
        .sort("timestamp_ayvens", 1)
    )
    return bids


@app.get("/api/veiculos/{lot_id}/historico")
def get_historico(lot_id: str):
    """Retorna o histórico de preços de um veículo."""
    historico = list(
        db.historico_precos.find({"lot_id": lot_id}, {"_id": 0})
        .sort("timestamp", 1)
    )
    return historico


# ---------------------------------------------------------------------------
# Endpoint interno — recebe notificação do main.py e faz broadcast SSE
# ---------------------------------------------------------------------------

@app.post("/api/interno/novo_preco")
async def notify_novo_preco(request: Request):
    """
    Recebe um evento de novo preço do main.py e distribui por todos
    os clientes SSE ligados. Apenas acessível localmente.
    """
    client_host = request.client.host
    if client_host not in ("127.0.0.1", "::1", "localhost"):
        raise HTTPException(status_code=403, detail="Acesso não autorizado")

    evento = await request.json()
    _broadcast(evento)
    logger.info("SSE broadcast — lot: %s | %.0f€ (%d clientes)",
                evento.get("lot_id"), evento.get("valor", 0), len(_sse_clients))
    return {"ok": True}


# ---------------------------------------------------------------------------
# SSE — stream de eventos em tempo real
# ---------------------------------------------------------------------------

@app.get("/api/events")
async def sse_events():
    """Stream SSE. Emite eventos 'novo_preco' em tempo real."""
    queue: asyncio.Queue = asyncio.Queue(maxsize=100)
    _sse_clients.append(queue)
    logger.info("SSE cliente ligado — total: %d", len(_sse_clients))

    async def generator():
        try:
            yield {"event": "ping", "data": "connected"}
            while True:
                try:
                    evento = await asyncio.wait_for(queue.get(), timeout=20)
                    yield {"event": "novo_preco", "data": json.dumps(evento, default=str)}
                except asyncio.TimeoutError:
                    yield {"event": "ping", "data": "alive"}
        finally:
            _sse_clients.remove(queue)
            logger.info("SSE cliente desligado — total: %d", len(_sse_clients))

    return EventSourceResponse(generator())
