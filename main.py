"""
Script principal do Ayvens Carmarket Scraper.

Ciclo de execução:
1. Autenticar (com cookies guardados ou login)
2. Obter leilões PT ativos da homepage
3. Para cada leilão, obter todos os veículos
4. Guardar leilões e veículos na BD
5. Registar licitações atuais
6. Repetir a cada N segundos (polling)
"""

import logging
import os
import random
import time
from datetime import datetime

from dotenv import load_dotenv

from auth import get_authenticated_session
from database import (
    get_db,
    registar_precos_bulk,
    setup_indexes,
    upsert_leiloes,
    upsert_veiculos,
)
from scraper import get_leiloes_pt, get_veiculos_leilao

# ---------------------------------------------------------------------------
# Configuração de logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("main")

# ---------------------------------------------------------------------------
# Configuração
# ---------------------------------------------------------------------------

load_dotenv()

USERNAME    = os.getenv("AYVENS_USERNAME", "")
PASSWORD    = os.getenv("AYVENS_PASSWORD", "")
MONGO_URI   = os.getenv("MONGO_URI", "mongodb://localhost:27017/")
MONGO_DB    = os.getenv("MONGO_DB", "ayvens")

# Intervalo de polling em segundos (com variação aleatória para não ser detetado)
POLL_INTERVAL_MIN = 25
POLL_INTERVAL_MAX = 40


def run_cycle(session, db) -> None:
    """Executa um ciclo completo de scraping."""
    logger.info("=" * 60)
    logger.info("Início do ciclo — %s", datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC"))

    # 1. Obter leilões PT ativos
    leiloes = get_leiloes_pt(session)
    if not leiloes:
        logger.warning("Nenhum leilão PT encontrado.")
        return

    # 2. Guardar leilões na BD
    upsert_leiloes(db, leiloes)

    # 3. Para cada leilão, obter e guardar veículos
    for leilao in leiloes:
        logger.info("A processar leilão %s — %s", leilao.sale_id, leilao.nome)

        veiculos = get_veiculos_leilao(session, leilao.sale_id)
        if not veiculos:
            logger.warning("Leilão %s — sem veículos.", leilao.sale_id)
            continue

        # Guardar/atualizar veículos
        upsert_veiculos(db, veiculos)

        registar_precos_bulk(db, veiculos)

        # Pequena pausa entre leilões para não sobrecarregar
        time.sleep(random.uniform(1.5, 3.0))

    logger.info("Ciclo concluído.")


def main():
    if not USERNAME or not PASSWORD:
        logger.error("Credenciais não configuradas. Define AYVENS_USERNAME e AYVENS_PASSWORD no .env")
        return

    # Ligação à BD
    db = get_db(MONGO_URI, MONGO_DB)
    setup_indexes(db)
    logger.info("Ligado ao MongoDB: %s / %s", MONGO_URI, MONGO_DB)

    # Sessão autenticada
    session = get_authenticated_session(USERNAME, PASSWORD)
    if not session:
        logger.error("Não foi possível autenticar. A terminar.")
        return

    logger.info("Autenticado com sucesso. A iniciar scraping...")

    # Loop principal
    while True:
        try:
            run_cycle(session, db)
        except Exception as e:
            logger.error("Erro no ciclo: %s", e, exc_info=True)
            # Tentar renovar sessão em caso de erro
            logger.info("A tentar renovar sessão...")
            session = get_authenticated_session(USERNAME, PASSWORD)
            if not session:
                logger.error("Não foi possível renovar sessão. A terminar.")
                break

        # Aguardar próximo ciclo com intervalo aleatório
        intervalo = random.uniform(POLL_INTERVAL_MIN, POLL_INTERVAL_MAX)
        logger.info("Próximo ciclo em %.0f segundos.", intervalo)
        time.sleep(intervalo)


if __name__ == "__main__":
    main()
