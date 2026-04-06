"""
Módulo de base de dados MongoDB para o Ayvens Carmarket Scraper.
Coleções: leiloes, veiculos, historico_precos
"""

import logging
from dataclasses import asdict
from datetime import datetime

from pymongo import MongoClient, UpdateOne
from pymongo.database import Database

from scraper import Leilao, Veiculo

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
    logger.info("Índices criados/confirmados.")


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

CAMPOS_DINAMICOS = {"bid_amount", "offers_count", "is_sold", "is_withdrawn"}


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
        ops.append(UpdateOne(
            {"lot_id": v.lot_id},
            {"$set": dinamico, "$setOnInsert": estatico},
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
) -> bool:
    """
    Regista o preço atual se for diferente do último registado.
    Retorna True se foi inserido um novo registo, False se era igual.
    """
    ultimo = db.historico_precos.find_one(
        {"lot_id": lot_id},
        sort=[("timestamp", -1)],
    )

    if ultimo and ultimo.get("valor") == valor:
        return False

    db.historico_precos.insert_one({
        "lot_id":    lot_id,
        "valor":     valor,
        "timestamp": datetime.utcnow(),
    })
    logger.info(
        "Novo preço — lot: %s | %s (%s) | %s → %.0f€",
        lot_id,
        marca_modelo,
        matricula,
        f"{ultimo['valor']:.0f}€" if ultimo else "inicial",
        valor,
    )
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
        if registar_preco(db, v.lot_id, v.bid_amount, v.marca_modelo, v.matricula):
            novos += 1
    logger.info("Preços registados neste ciclo: %d", novos)
    return novos


def get_historico_precos(db: Database, lot_id: str) -> list[dict]:
    """Retorna o histórico completo de preços de um veículo, ordenado por tempo."""
    return list(db.historico_precos.find({"lot_id": lot_id}, sort=[("timestamp", 1)]))
