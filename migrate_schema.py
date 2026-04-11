"""
Migração: veiculos (legacy) → veiculos (novo) + participacoes

Executa com o main.py e api.py PARADOS.
É idempotente — pode ser re-executado sem duplicar dados.

Passos:
1. Renomeia veiculos → veiculos_legacy (se ainda não renomeada)
2. Cria counter para IDs incrementais
3. Para cada doc em veiculos_legacy:
   - Cria/atualiza registo em veiculos (lookup por matrícula/chassis)
   - Cria/atualiza registo em participacoes (upsert por lot_id)
"""

import os
import logging
from datetime import datetime

from dotenv import load_dotenv
from pymongo import MongoClient, UpdateOne

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("migrate")

MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017/")
MONGO_DB  = os.getenv("MONGO_DB", "ayvens")

client = MongoClient(MONGO_URI)
db = client[MONGO_DB]


def _next_id() -> int:
    doc = db.counters.find_one_and_update(
        {"_id": "veiculos"},
        {"$inc": {"seq": 1}},
        upsert=True,
        return_document=True,
    )
    return doc["seq"]


CAMPOS_VEICULO = {
    "lot_id", "marca_modelo", "versao", "matricula", "km", "data_registo",
    "combustivel", "caixa", "localizacao", "fornecedor", "chassis",
    "imagem_url", "carrocaria", "portas", "lugares", "categoria",
    "cor_exterior", "ano_construcao", "potencia_cv", "cilindrada",
    "eurotax_venda", "eurotax_compra", "doc_manutencao", "doc_peritagem",
    "scrape_ts",
}

CAMPOS_PARTICIPACAO = {
    "lot_id", "sale_id", "numero_lote", "bid_amount", "offers_count",
    "is_sold", "is_withdrawn", "has_offer", "base_licitacao", "scrape_ts",
}

CAMPOS_ATUALIZAVEIS_VEICULO = {
    "imagem_url", "eurotax_venda", "eurotax_compra",
    "localizacao", "doc_manutencao", "doc_peritagem", "km", "data_registo",
}


def main():
    cols = db.list_collection_names()

    # Passo 1 — renomear veiculos → veiculos_legacy
    if "veiculos_legacy" not in cols:
        if "veiculos" in cols:
            db.veiculos.rename("veiculos_legacy")
            logger.info("veiculos renomeada para veiculos_legacy")
        else:
            logger.warning("Colecao veiculos nao encontrada — nada a migrar")
            return
    else:
        logger.info("veiculos_legacy ja existe — a continuar migracao")

    # Passo 2 — garantir counter
    db.counters.update_one(
        {"_id": "veiculos"},
        {"$setOnInsert": {"seq": 0}},
        upsert=True,
    )

    # Passo 3 — migrar documentos
    total = db.veiculos_legacy.count_documents({})
    logger.info("A migrar %d documentos...", total)

    novos_veiculos = 0
    novos_part = 0
    part_ops = []

    for doc in db.veiculos_legacy.find({}):
        matricula = doc.get("matricula", "")
        chassis   = doc.get("chassis", "")

        # --- Veiculo ---
        existente = None
        if matricula:
            existente = db.veiculos.find_one({"matricula": matricula}, {"_id": 1, "scrape_ts": 1})
        if not existente and chassis:
            existente = db.veiculos.find_one({"chassis": chassis}, {"_id": 1, "scrape_ts": 1})

        if existente:
            veiculo_id = existente["_id"]
            # Atualizar só se este doc for mais recente
            doc_ts = doc.get("scrape_ts")
            exist_ts = existente.get("scrape_ts")
            if doc_ts and exist_ts and doc_ts > exist_ts:
                upd = {k: doc[k] for k in CAMPOS_ATUALIZAVEIS_VEICULO if k in doc}
                if upd:
                    db.veiculos.update_one({"_id": veiculo_id}, {"$set": upd})
        else:
            veiculo_id = _next_id()
            v_doc = {k: doc[k] for k in CAMPOS_VEICULO if k in doc}
            v_doc["_id"] = veiculo_id
            db.veiculos.insert_one(v_doc)
            novos_veiculos += 1

        # --- Participacao ---
        p_doc = {k: doc[k] for k in CAMPOS_PARTICIPACAO if k in doc}
        p_doc["veiculo_id"] = veiculo_id
        lot_id = doc.get("lot_id")

        set_always = {k: v for k, v in p_doc.items() if k not in {"lot_id", "sale_id", "numero_lote", "veiculo_id", "bid_amount"}}
        bid = p_doc.get("bid_amount")
        if bid is not None:
            set_always["bid_amount"] = bid

        part_ops.append(UpdateOne(
            {"lot_id": lot_id},
            {
                "$set": set_always,
                "$setOnInsert": {
                    "lot_id":      lot_id,
                    "sale_id":     p_doc.get("sale_id"),
                    "numero_lote": p_doc.get("numero_lote"),
                    "veiculo_id":  veiculo_id,
                    **({"bid_amount": None} if bid is None else {}),
                },
            },
            upsert=True,
        ))

    if part_ops:
        result = db.participacoes.bulk_write(part_ops)
        novos_part = result.upserted_count
        logger.info("Participacoes — upserted: %d, modified: %d", result.upserted_count, result.modified_count)

    # Passo 4 — índices
    db.veiculos.create_index("matricula")
    db.veiculos.create_index("chassis")
    db.participacoes.create_index("lot_id", unique=True)
    db.participacoes.create_index("sale_id")
    db.participacoes.create_index("veiculo_id")

    logger.info("Migracao concluida — veiculos novos: %d | participacoes novas: %d", novos_veiculos, novos_part)
    logger.info("veiculos_legacy mantida intacta com %d documentos", total)


if __name__ == "__main__":
    main()
