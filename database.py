"""
Módulo de base de dados MongoDB para o Ayvens Carmarket Scraper.
Coleções: leiloes, veiculos, historico_precos
"""

import logging
import requests as _requests
from dataclasses import asdict
from datetime import datetime

from pymongo import MongoClient, UpdateOne
from pymongo.database import Database

from scraper import Leilao, Veiculo

API_NOTIFY_URL = "http://127.0.0.1:8000/api/interno/novo_preco"


def _notify_sse(evento: dict) -> None:
    """Notifica a API de um novo evento para broadcast SSE."""
    try:
        _requests.post(API_NOTIFY_URL, json=evento, timeout=2)
    except Exception:
        pass  # API pode não estar a correr — não bloquear o scraper

logger = logging.getLogger(__name__)


def get_db(mongo_uri: str = "mongodb://localhost:27017/", db_name: str = "ayvens") -> Database:
    """Retorna a ligação à base de dados MongoDB."""
    client = MongoClient(mongo_uri)
    return client[db_name]


def setup_indexes(db: Database) -> None:
    """Cria índices nas coleções para melhor performance."""
    db.leiloes.create_index("sale_id", unique=True)
    db.veiculos.create_index("lot_id", unique=True)
    db.veiculos.create_index("sale_id")
    db.historico_precos.create_index([("lot_id", 1), ("timestamp", -1)])
    db.historico_precos.create_index("lot_id")
    db.licitacoes_websocket_signalr.create_index([("lot_id", 1), ("timestamp_ayvens", -1)])
    logger.info("Índices criados/confirmados.")


def registar_licitacao_ws(
    db: Database,
    lot_id: str,
    sale_id: str,
    highest_bid: float,
    timestamp_utc: str,
) -> None:
    """
    Regista uma licitação recebida via WebSocket SignalR na coleção temporária
    licitacoes_websocket_signalr, para comparação com o polling.
    """
    from datetime import timezone
    try:
        ts_ayvens = datetime.fromisoformat(timestamp_utc.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        ts_ayvens = datetime.now(timezone.utc)

    db.licitacoes_websocket_signalr.insert_one({
        "lot_id":        lot_id,
        "sale_id":       sale_id,
        "valor":         highest_bid,
        "timestamp_ayvens": ts_ayvens,
        "received_at":   datetime.utcnow(),
    })
    logger.debug("WS bid registado — lot: %s | %.0f€", lot_id, highest_bid)


# ---------------------------------------------------------------------------
# Leilões
# ---------------------------------------------------------------------------

def upsert_leilao(db: Database, leilao: Leilao) -> None:
    """Insere ou atualiza um leilão."""
    doc = asdict(leilao)
    scrape_ts = doc.pop("scrape_ts")
    db.leiloes.update_one(
        {"sale_id": leilao.sale_id},
        {"$set": doc, "$setOnInsert": {"scrape_ts": scrape_ts}},
        upsert=True,
    )
    logger.debug("Leilão upserted: %s", leilao.sale_id)


def upsert_leiloes(db: Database, leiloes: list[Leilao]) -> None:
    """Upsert em bulk de uma lista de leilões."""
    if not leiloes:
        return
    ops = []
    for l in leiloes:
        doc = asdict(l)
        scrape_ts = doc.pop("scrape_ts")
        ops.append(UpdateOne(
            {"sale_id": l.sale_id},
            {"$set": doc, "$setOnInsert": {"scrape_ts": scrape_ts}},
            upsert=True,
        ))
    result = db.leiloes.bulk_write(ops)
    logger.info("Leilões — upserted: %d, modified: %d", result.upserted_count, result.modified_count)


def get_leiloes_ativos(db: Database) -> list[dict]:
    """Retorna leilões com estado aberto (estado=3)."""
    return list(db.leiloes.find({"estado": 3}))


# ---------------------------------------------------------------------------
# Veículos
# ---------------------------------------------------------------------------

CAMPOS_DINAMICOS = {"bid_amount", "offers_count", "is_sold", "is_withdrawn", "has_offer"}


def upsert_veiculos(db: Database, veiculos: list[Veiculo]) -> None:
    """
    Upsert em bulk de uma lista de veículos.
    Na inserção guarda todos os campos. Em atualizações só toca em
    bid_amount, offers_count, is_sold e is_withdrawn.
    """
    if not veiculos:
        return
    ops = []
    for v in veiculos:
        doc = asdict(v)
        doc.pop("scrape_ts")
        dinamico = {k: doc[k] for k in CAMPOS_DINAMICOS}
        estatico = {k: v for k, v in doc.items() if k not in CAMPOS_DINAMICOS}
        # Se bid_amount for None, não sobrescrever um valor já existente na BD
        if dinamico["bid_amount"] is None:
            dinamico.pop("bid_amount")
            setOnInsert = {**estatico, "bid_amount": None}
        else:
            setOnInsert = estatico
        ops.append(UpdateOne(
            {"lot_id": v.lot_id},
            {"$set": dinamico, "$setOnInsert": setOnInsert},
            upsert=True,
        ))
    result = db.veiculos.bulk_write(ops)
    logger.info(
        "Veículos — upserted: %d, modified: %d",
        result.upserted_count,
        result.modified_count,
    )


def get_veiculos_por_leilao(db: Database, sale_id: str) -> list[dict]:
    """Retorna todos os veículos de um leilão."""
    return list(db.veiculos.find({"sale_id": sale_id}))


# ---------------------------------------------------------------------------
# Histórico de preços
# ---------------------------------------------------------------------------

def registar_preco(
    db: Database,
    lot_id: str,
    valor: float,
    marca_modelo: str = "",
    matricula: str = "",
    has_offer: bool = False,
) -> bool:
    """
    Regista o preço atual se for diferente do último registado.
    Também regista quando o preço é igual mas passou de sem oferta para com oferta
    (primeira licitação ao preço base).
    Retorna True se foi inserido um novo registo, False se era igual.
    """
    ultimo = db.historico_precos.find_one(
        {"lot_id": lot_id},
        sort=[("timestamp", -1)],
    )

    if ultimo and ultimo.get("valor") == valor:
        # Mesmo preço — só grava se é a primeira licitação real (passou de base para oferta)
        if not (has_offer and not ultimo.get("has_offer", False)):
            return False

    ts = datetime.utcnow()
    db.historico_precos.insert_one({
        "lot_id":     lot_id,
        "valor":      valor,
        "has_offer":  has_offer,
        "timestamp":  ts,
    })
    logger.info(
        "Novo preço — lot: %s | %s (%s) | %s → %.0f€",
        lot_id,
        marca_modelo,
        matricula,
        f"{ultimo['valor']:.0f}€" if ultimo else "inicial",
        valor,
    )

    # Notificar API para broadcast SSE
    veiculo = db.veiculos.find_one(
        {"lot_id": lot_id},
        {"sale_id": 1, "offers_count": 1, "is_sold": 1, "is_withdrawn": 1, "_id": 0},
    )
    evento = {
        "lot_id":        lot_id,
        "valor":         valor,
        "timestamp":     ts.isoformat(),
        "marca_modelo":  marca_modelo,
        "matricula":     matricula,
    }
    if veiculo:
        evento.update({
            "sale_id":       veiculo.get("sale_id"),
            "offers_count":  veiculo.get("offers_count"),
            "is_sold":       veiculo.get("is_sold"),
            "is_withdrawn":  veiculo.get("is_withdrawn"),
        })
    _notify_sse(evento)

    return True


def registar_precos_bulk(db: Database, veiculos: list[Veiculo]) -> int:
    """
    Regista o preço atual de cada veículo se tiver mudado.
    Retorna o número de novos registos inseridos.
    """
    novos = 0
    for v in veiculos:
        if v.bid_amount is None or v.is_withdrawn:
            continue
        if registar_preco(db, v.lot_id, v.bid_amount, v.marca_modelo, v.matricula, v.has_offer):
            novos += 1
    logger.info("Preços registados neste ciclo: %d", novos)
    return novos


def get_historico_precos(db: Database, lot_id: str) -> list[dict]:
    """Retorna o histórico completo de preços de um veículo, ordenado por tempo."""
    return list(db.historico_precos.find({"lot_id": lot_id}, sort=[("timestamp", 1)]))
