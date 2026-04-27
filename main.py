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
import logging.handlers
import os
import random
import threading
import time
from datetime import datetime

from dotenv import load_dotenv

from auth import get_authenticated_session, renew_session, session_expiration_ts
from database import (
    get_db,
    registar_licitacao_ws,
    registar_preco,
    registar_precos_bulk,
    setup_indexes,
    upsert_leiloes,
    upsert_veiculo,
    upsert_participacoes_bulk,
)
from scraper import get_leiloes_pt, get_veiculos_leilao
import signalr_listener

# ---------------------------------------------------------------------------
# Configuração de logging
# ---------------------------------------------------------------------------

LOG_FORMAT    = "%(asctime)s [%(levelname)s] %(name)s — %(message)s"
LOG_DATEFMT   = "%Y-%m-%d %H:%M:%S"
LOG_FILE      = "everest.log"
LOG_HOURS     = int(os.getenv("LOG_HOURS", 240))
LOG_TRIM_HOUR = int(os.getenv("LOG_TRIM_HOUR", 23))

logging.basicConfig(
    level=logging.INFO,
    format=LOG_FORMAT,
    datefmt=LOG_DATEFMT,
)

_file_handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
_file_handler.setFormatter(logging.Formatter(LOG_FORMAT, datefmt=LOG_DATEFMT))
logging.getLogger().addHandler(_file_handler)

logger = logging.getLogger("main")


def _trim_log(path: str = LOG_FILE, hours: int = LOG_HOURS) -> None:
    """Remove do ficheiro de log as linhas com mais de `hours` horas."""
    if not os.path.exists(path):
        return
    cutoff = datetime.utcnow().timestamp() - hours * 3600
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
        kept = []
        for line in lines:
            try:
                ts = datetime.strptime(line[:19], "%Y-%m-%d %H:%M:%S").timestamp()
                if ts >= cutoff:
                    kept.append(line)
            except ValueError:
                kept.append(line)  # linhas sem timestamp (stack traces)
        with open(path, "w", encoding="utf-8") as f:
            f.writelines(kept)
        logger.info("Log trimmed — %d linhas removidas, %d mantidas.", len(lines) - len(kept), len(kept))
    except Exception as e:
        logger.warning("Erro ao fazer trim do log: %s", e)


def _start_log_trim_thread() -> None:
    """Thread que limpa o log diariamente à hora definida em LOG_TRIM_HOUR."""
    from datetime import timedelta
    def run():
        while True:
            try:
                now = datetime.utcnow()
                target = now.replace(hour=LOG_TRIM_HOUR, minute=0, second=0, microsecond=0)
                if now >= target:
                    target += timedelta(days=1)
                sleep_secs = (target - now).total_seconds()
                time.sleep(sleep_secs)
                _trim_log()
            except Exception as e:
                logger.warning("Erro na thread de trim do log: %s", e)
                time.sleep(3600)
    t = threading.Thread(target=run, name="log-trim", daemon=True)
    t.start()

# ---------------------------------------------------------------------------
# Configuração
# ---------------------------------------------------------------------------

load_dotenv()

USERNAME    = os.getenv("AYVENS_USERNAME", "")
PASSWORD    = os.getenv("AYVENS_PASSWORD", "")
MONGO_URI   = os.getenv("MONGO_URI", "mongodb://localhost:27017/")
MONGO_DB    = os.getenv("MONGO_DB", "ayvens")

# Blocos de horário — definidos no .env
# Cada bloco: INICIO, FIM (hora inteira), MIN e MAX em segundos
# MIN=MAX=0 significa parado nesse bloco
BLOCOS = [
    {
        "inicio": int(os.getenv("BLOCO1_INICIO", 8)),
        "fim":    int(os.getenv("BLOCO1_FIM",    14)),
        "min":    int(os.getenv("BLOCO1_MIN",    3000)),
        "max":    int(os.getenv("BLOCO1_MAX",    5400)),
    },
    {
        "inicio": int(os.getenv("BLOCO2_INICIO", 14)),
        "fim":    int(os.getenv("BLOCO2_FIM",    17)),
        "min":    int(os.getenv("BLOCO2_MIN",    120)),
        "max":    int(os.getenv("BLOCO2_MAX",    240)),
    },
    {
        "inicio": int(os.getenv("BLOCO3_INICIO", 17)),
        "fim":    int(os.getenv("BLOCO3_FIM",    23)),
        "min":    int(os.getenv("BLOCO3_MIN",    3000)),
        "max":    int(os.getenv("BLOCO3_MAX",    5400)),
    },
]


def get_intervalo() -> float:
    """Retorna o intervalo em segundos conforme o bloco horário actual."""
    hora = datetime.now().hour
    for b in BLOCOS:
        if b["inicio"] <= hora < b["fim"]:
            return random.uniform(b["min"], b["max"])
    # Fora de todos os blocos — intervalo longo (não devia acontecer, o cron para o container)
    return 3600


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

    # 2b. Marcar como encerrados os leilões que já não aparecem na homepage
    sale_ids_ativos = {l.sale_id for l in leiloes}
    resultado = db.leiloes.update_many(
        {"estado": 3, "fonte": {"$exists": False}, "sale_id": {"$nin": list(sale_ids_ativos)}},
        {"$set": {"estado": 4}},
    )
    if resultado.modified_count:
        logger.info("Leilões encerrados: %d", resultado.modified_count)

    # 3. Para cada leilão, obter e guardar veículos
    for leilao in leiloes:
        logger.info("A processar leilão %s — %s", leilao.sale_id, leilao.nome)

        pares = get_veiculos_leilao(session, leilao.sale_id)
        if not pares:
            logger.warning("Leilão %s — sem veículos.", leilao.sale_id)
            continue

        # Upsert veículos (por matrícula) e participações (por lot_id)
        pares_com_id = []
        for veiculo, participacao in pares:
            veiculo_id = upsert_veiculo(db, veiculo)
            pares_com_id.append((veiculo_id, participacao))

        upsert_participacoes_bulk(db, pares_com_id)
        registar_precos_bulk(db, pares)

        # Pequena pausa entre leilões para não sobrecarregar
        time.sleep(random.uniform(1.5, 3.0))

    logger.info("Ciclo concluído.")


def start_session_renewal_thread(session, stop_event: threading.Event) -> threading.Thread:
    """
    Thread que dorme até 10 minutos antes da sessão expirar, renova, e repete.
    """
    MARGIN = 10 * 60  # acordar 10 minutos antes de expirar

    def run():
        while not stop_event.is_set():
            try:
                ts = session_expiration_ts(session)
                if ts is None:
                    logger.warning("Renovação sessão — sem timestamp de expiração, a tentar em 5 minutos.")
                    stop_event.wait(300)
                    continue

                sleep_seconds = max(0, (ts - time.time()) - MARGIN)
                from datetime import datetime, timezone
                renew_at = datetime.fromtimestamp(ts - MARGIN).strftime("%H:%M:%S")
                logger.info("Sessão expira em %.0f minutos — renovação agendada para as %s.", (ts - time.time()) / 60, renew_at)

                # Dormir até 10 minutos antes de expirar (ou acordar se stop_event for ativado)
                stop_event.wait(sleep_seconds)
                if stop_event.is_set():
                    break

                logger.info("Sessão perto de expirar — a renovar...")
                ok = renew_session(session, USERNAME, PASSWORD)
                if not ok:
                    logger.error("Falha ao renovar sessão — nova tentativa em 2 minutos.")
                    stop_event.wait(120)

            except Exception as e:
                logger.error("Erro na thread de renovação: %s", e)
                stop_event.wait(60)

    t = threading.Thread(target=run, name="session-renewal", daemon=True)
    t.start()
    logger.info("Thread de renovação de sessão iniciada.")
    return t


def start_signalr_thread(session, db) -> threading.Thread:
    """Lança o listener SignalR numa thread de background."""
    stop_event = threading.Event()

    def on_bid(lot_id: str, sale_id: str, highest_bid: float, timestamp_utc: str):
        try:
            registar_licitacao_ws(db, lot_id, sale_id, highest_bid, timestamp_utc)
            db.participacoes.update_one(
                {"lot_id": lot_id},
                {"$set": {"bid_amount": highest_bid}},
            )
            # Notificar SSE para o frontend atualizar em tempo real
            part = db.participacoes.find_one({"lot_id": lot_id}, {"veiculo_id": 1, "sale_id": 1, "offers_count": 1, "is_sold": 1, "is_withdrawn": 1})
            v = db.veiculos.find_one({"_id": part["veiculo_id"]}, {"marca_modelo": 1, "matricula": 1}) if part else None
            from database import _notify_sse
            from datetime import datetime, timezone
            _notify_sse({
                "lot_id":       lot_id,
                "valor":        highest_bid,
                "timestamp":    datetime.now(timezone.utc).isoformat(),
                "marca_modelo": v.get("marca_modelo", "") if v else "",
                "matricula":    v.get("matricula", "") if v else "",
                "fonte":        "ws",
                "sale_id":      part.get("sale_id") if part else None,
                "offers_count": part.get("offers_count") if part else None,
                "is_sold":      part.get("is_sold") if part else None,
                "is_withdrawn": part.get("is_withdrawn") if part else None,
            })
        except Exception as e:
            logger.error("Erro ao registar licitacao WS: %s", e)

    def get_sale_ids() -> list[str]:
        leiloes = db.leiloes.find({"estado": 3, "fonte": {"$exists": False}}, {"sale_id": 1, "_id": 0})
        return [str(l["sale_id"]) for l in leiloes]

    def get_closing_date():
        # Devolve o closing_date mais próximo entre os leilões activos
        from datetime import timezone
        leiloes = list(db.leiloes.find({"estado": 3, "fonte": {"$exists": False}}, {"closing_date": 1, "_id": 0}))
        datas = []
        for l in leiloes:
            raw = l.get("closing_date", "")
            if raw:
                try:
                    datas.append(datetime.fromisoformat(raw.replace("Z", "+00:00")).astimezone(timezone.utc))
                except (ValueError, AttributeError):
                    pass
        return min(datas) if datas else None

    def run():
        signalr_listener.listen(session, on_bid, stop_event, get_sale_ids, get_closing_date)

    t = threading.Thread(target=run, name="signalr-listener", daemon=True)
    t.start()
    logger.info("Thread SignalR iniciada.")
    return t


def main():
    if not USERNAME or not PASSWORD:
        logger.error("Credenciais não configuradas. Define AYVENS_USERNAME e AYVENS_PASSWORD no .env")
        return

    # Thread de limpeza do log (todos os dias às 23:00)
    _start_log_trim_thread()

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

    # Thread de renovação automática de sessão
    stop_event = threading.Event()
    start_session_renewal_thread(session, stop_event)

    # Iniciar listener SignalR em paralelo (fase de validação)
    start_signalr_thread(session, db)

    # Loop principal (polling mantido para comparação)
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

        # Aguardar próximo ciclo conforme bloco horário
        intervalo = get_intervalo()
        logger.info("Próximo ciclo em %.0f segundos.", intervalo)
        time.sleep(intervalo)


if __name__ == "__main__":
    main()
