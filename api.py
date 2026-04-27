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


@app.get("/api/pesquisa/sugestoes")
def pesquisa_sugestoes(q: str = ""):
    """Pesquisa veículos por marca/modelo (parcial, case-insensitive). Devolve até 20 resultados com estatísticas."""
    if not q or len(q) < 2:
        return []
    docs = list(
        db.veiculos.find(
            {"marca_modelo": {"$regex": q, "$options": "i"}},
            {"_id": 1, "marca_modelo": 1, "matricula": 1, "imagem_url": 1, "ano_construcao": 1, "km": 1, "combustivel": 1},
        ).sort("_id", -1).limit(20)
    )

    resultado = []
    for v in docs:
        veiculo_id = v["_id"]

        # Todas as participações deste veículo
        participacoes = list(db.participacoes.find({"veiculo_id": veiculo_id}, {"lot_id": 1, "sale_id": 1, "_id": 0}))
        num_leiloes = len(participacoes)
        lot_ids = [p["lot_id"] for p in participacoes]

        # Último leilão — o mais recente por data_inicio
        num_bids      = 0
        preco_inicial = None
        preco_final   = None
        if participacoes:
            sale_ids = [p["sale_id"] for p in participacoes]
            leiloes_v = list(db.leiloes.find({"sale_id": {"$in": sale_ids}}, {"sale_id": 1, "data_inicio": 1, "_id": 0}))
            leiloes_v.sort(key=lambda l: l.get("data_inicio") or "", reverse=True)
            if leiloes_v:
                ultimo_sale_id = leiloes_v[0]["sale_id"]
                ultimo_lot_id  = next((p["lot_id"] for p in participacoes if p["sale_id"] == ultimo_sale_id), None)
                if ultimo_lot_id:
                    num_bids = db.licitacoes_websocket_signalr.count_documents({"lot_id": ultimo_lot_id})
                    historico = list(
                        db.historico_precos.find({"lot_id": ultimo_lot_id}, {"valor": 1, "_id": 0}).sort("timestamp", 1)
                    )
                    if historico:
                        preco_inicial = historico[0]["valor"]
                        preco_final   = historico[-1]["valor"]

        resultado.append({
            "veiculo_id":     veiculo_id,
            "marca_modelo":   v.get("marca_modelo", ""),
            "matricula":      v.get("matricula", ""),
            "imagem_url":     v.get("imagem_url", ""),
            "ano_construcao": v.get("ano_construcao", ""),
            "km":             v.get("km", ""),
            "combustivel":    v.get("combustivel", ""),
            "num_leiloes":    num_leiloes,
            "num_bids":       num_bids,
            "preco_inicial":  preco_inicial,
            "preco_final":    preco_final,
        })

    return resultado


@app.get("/api/analises/multi-leiloes")
def analises_multi_leiloes():
    """
    Veículos em múltiplos leilões (2º, 3º, 4º, 5+) sem licitações no último leilão.
    Retorna grupos separados para o dashboard.
    """
    # Contar participações por veículo
    pipeline = [
        {"$group": {"_id": "$veiculo_id", "num_leiloes": {"$sum": 1}}},
        {"$match": {"num_leiloes": {"$gte": 2}}},
    ]
    contagens = {r["_id"]: r["num_leiloes"] for r in db.participacoes.aggregate(pipeline)}

    veiculo_ids = list(contagens.keys())
    veiculos_docs = {
        v["_id"]: v
        for v in db.veiculos.find(
            {"_id": {"$in": veiculo_ids}},
            {"_id": 1, "marca_modelo": 1, "matricula": 1, "imagem_url": 1, "ano_construcao": 1, "km": 1},
        )
    }

    grupos = {2: [], 3: [], 4: [], 5: []}

    for veiculo_id, num_leiloes in contagens.items():
        v = veiculos_docs.get(veiculo_id)
        if not v:
            continue

        # Descobrir o lot_id do último leilão
        participacoes = list(db.participacoes.find({"veiculo_id": veiculo_id}, {"lot_id": 1, "sale_id": 1, "_id": 0}))
        sale_ids = [p["sale_id"] for p in participacoes]
        leiloes_v = list(db.leiloes.find({"sale_id": {"$in": sale_ids}}, {"sale_id": 1, "data_inicio": 1, "_id": 0}))
        leiloes_v.sort(key=lambda l: l.get("data_inicio") or "", reverse=True)
        if not leiloes_v:
            continue
        ultimo_sale_id = leiloes_v[0]["sale_id"]
        ultimo_lot_id  = next((p["lot_id"] for p in participacoes if p["sale_id"] == ultimo_sale_id), None)
        if not ultimo_lot_id:
            continue

        # Excluir se tiver licitações no último leilão
        num_bids = db.licitacoes_websocket_signalr.count_documents({"lot_id": ultimo_lot_id})
        if num_bids > 0:
            continue

        entry = {
            "veiculo_id":     veiculo_id,
            "marca_modelo":   v.get("marca_modelo", ""),
            "matricula":      v.get("matricula", ""),
            "imagem_url":     v.get("imagem_url", ""),
            "ano_construcao": v.get("ano_construcao", ""),
            "km":             v.get("km", ""),
            "num_leiloes":    num_leiloes,
        }

        chave = num_leiloes if num_leiloes <= 4 else 5
        grupos[chave].append(entry)

    # Ordenar cada grupo por veiculo_id desc (mais recentes primeiro)
    for g in grupos.values():
        g.sort(key=lambda x: x["veiculo_id"], reverse=True)

    return {
        "segundo":  grupos[2],
        "terceiro": grupos[3],
        "quarto":   grupos[4],
        "quinto_mais": grupos[5],
    }


@app.get("/api/analises/preco-descendente")
def analises_preco_descendente():
    """
    Viaturas cujo preço inicial está a descer entre leilões consecutivos.
    Compara o preço base do leilão mais recente com o anterior.
    """
    pipeline = [
        {"$group": {"_id": "$veiculo_id", "num_leiloes": {"$sum": 1}}},
        {"$match": {"num_leiloes": {"$gte": 2}}},
    ]
    veiculo_ids = [r["_id"] for r in db.participacoes.aggregate(pipeline)]

    veiculos_docs = {
        v["_id"]: v
        for v in db.veiculos.find(
            {"_id": {"$in": veiculo_ids}},
            {"_id": 1, "marca_modelo": 1, "matricula": 1, "imagem_url": 1, "ano_construcao": 1, "km": 1},
        )
    }

    resultado = []

    for veiculo_id in veiculo_ids:
        v = veiculos_docs.get(veiculo_id)
        if not v:
            continue

        participacoes = list(db.participacoes.find({"veiculo_id": veiculo_id}, {"lot_id": 1, "sale_id": 1, "_id": 0}))
        sale_ids = [p["sale_id"] for p in participacoes]
        leiloes_v = list(db.leiloes.find({"sale_id": {"$in": sale_ids}}, {"sale_id": 1, "data_inicio": 1, "_id": 0}))
        leiloes_v.sort(key=lambda l: l.get("data_inicio") or "")

        if len(leiloes_v) < 2:
            continue

        # Obter preço inicial de cada leilão (ordenado do mais antigo para o mais recente)
        precos = []
        for leilao in leiloes_v:
            lot_id = next((p["lot_id"] for p in participacoes if p["sale_id"] == leilao["sale_id"]), None)
            if not lot_id:
                continue
            primeiro = db.historico_precos.find_one({"lot_id": lot_id}, {"valor": 1, "_id": 0}, sort=[("timestamp", 1)])
            precos.append({"sale_id": leilao["sale_id"], "data_inicio": leilao.get("data_inicio"), "preco_base": primeiro["valor"] if primeiro else None})

        precos = [p for p in precos if p["preco_base"] is not None]
        if len(precos) < 2:
            continue

        # Verificar se existe algum par consecutivo com descida de preço
        descida_max = 0
        tem_descida = False
        for i in range(len(precos) - 1, 0, -1):
            diff = precos[i - 1]["preco_base"] - precos[i]["preco_base"]
            if diff > 0:
                tem_descida = True
                descida_max = max(descida_max, diff)
        if not tem_descida:
            continue

        # Filtrar: sem licitações no último leilão OU leilão ativo
        ultimo_sale_id = precos[-1]["sale_id"]
        ultimo_lot_id  = next((p["lot_id"] for p in participacoes if p["sale_id"] == ultimo_sale_id), None)
        leilao_atual   = db.leiloes.find_one({"sale_id": ultimo_sale_id}, {"estado": 1, "_id": 0})
        leilao_ativo   = leilao_atual and leilao_atual.get("estado") == 3
        num_bids       = db.licitacoes_websocket_signalr.count_documents({"lot_id": ultimo_lot_id}) if ultimo_lot_id else 0
        if num_bids > 0 and not leilao_ativo:
            continue

        resultado.append({
            "veiculo_id":     veiculo_id,
            "marca_modelo":   v.get("marca_modelo", ""),
            "matricula":      v.get("matricula", ""),
            "imagem_url":     v.get("imagem_url", ""),
            "ano_construcao": v.get("ano_construcao", ""),
            "km":             v.get("km", ""),
            "num_leiloes":    len(precos),
            "precos":         [p["preco_base"] for p in precos],
            "descida":        descida_max,
            "leilao_ativo":   leilao_ativo,
        })

    resultado.sort(key=lambda x: (0 if x["leilao_ativo"] else 1, -x["descida"]))
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
