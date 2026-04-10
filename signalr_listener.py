"""
SignalR listener para o Ayvens Carmarket.
Recebe eventos de licitação em tempo real via WebSocket Azure SignalR.

Fluxo:
1. POST /signalRProxy/negotiate  (com cookies da sessão) → url + accessToken
2. POST Azure SignalR /negotiate  (com Bearer accessToken) → connectionToken
3. WebSocket wss://...?hub=...&id={connectionToken}&access_token={accessToken}
4. Handshake SignalR JSON + escutar mensagens Notify/lot.bid
"""

import json
from datetime import datetime
import logging
import time
import threading
from typing import Callable

import requests as _requests
import websocket

logger = logging.getLogger(__name__)

PROXY_NEGOTIATE_URL = "https://carmarket.ayvens.com/signalRProxy/negotiate?negotiateVersion=1"
RECORD_SEP = "\x1e"


def _proxy_negotiate(session, sale_id: str | None = None) -> tuple[str, str]:
    """
    Passo 1: negocia com o proxy do Ayvens usando os cookies de sessão.
    O Referer deve ser a página do leilão activo para o backend subscrever
    a ligação ao grupo de eventos desse leilão.
    Devolve (azure_url, access_token).
    """
    referer = (
        f"https://carmarket.ayvens.com/pt-pt/sales/{sale_id}/"
        if sale_id
        else "https://carmarket.ayvens.com/"
    )
    resp = session.post(
        PROXY_NEGOTIATE_URL,
        headers={
            "X-Requested-With": "XMLHttpRequest",
            "Referer": referer,
            "Content-Length": "0",
        },
    )
    resp.raise_for_status()
    data = resp.json()
    return data["url"], data["accessToken"]


def _azure_negotiate(azure_url: str, access_token: str) -> tuple[str, str]:
    """
    Passo 2: negocia com o Azure SignalR Service.
    Devolve (connectionId, connectionToken).
    connectionId  → usado nas URLs de subscrição (/subscribeToLots?connectionId=...)
    connectionToken → usado na URL do WebSocket (&id=...)
    """
    base = azure_url.split("?")[0].rstrip("/")  # remove query string e trailing slash
    negotiate_url = f"{base}/negotiate?hub=carmarketb2b_ald&negotiateVersion=1"
    resp = _requests.post(
        negotiate_url,
        headers={"Authorization": f"Bearer {access_token}"},
    )
    resp.raise_for_status()
    data = resp.json()
    return data["connectionId"], data["connectionToken"]


def _parse_messages(raw) -> list[dict]:
    """Divide mensagens SignalR pelo Record Separator (\\x1e) e faz parse JSON."""
    if isinstance(raw, bytes):
        logger.warning("SignalR — frame binário (%d bytes): %s", len(raw), raw.hex()[:200])
        try:
            raw = raw.decode("utf-8")
        except UnicodeDecodeError as e:
            logger.warning("SignalR — falha a decodificar frame binário: %s", e)
            return []

    result = []
    for part in raw.split(RECORD_SEP):
        part = part.strip()
        if part:
            try:
                result.append(json.loads(part))
            except json.JSONDecodeError as e:
                logger.warning("SignalR — falha JSON parse: %s | raw: %.200s", e, part)
    return result


def _parse_resource(resource: str) -> tuple[str, str]:
    """
    Extrai (sale_id, lot_id) de /saleevents/{sale_id}/lots/{lot_id}.
    Devolve ("", "") se não conseguir fazer parse.
    """
    parts = resource.rstrip("/").split("/")
    # esperado: ["", "saleevents", sale_id, "lots", lot_id]
    if len(parts) >= 5 and parts[-2] == "lots" and parts[-4] == "saleevents":
        return parts[-3], parts[-1]
    return "", ""


def listen(
    session,
    on_bid: Callable[[str, str, float, str], None],
    stop_event: threading.Event | None = None,
    get_sale_ids: Callable[[], list[str]] | None = None,
    get_closing_date: Callable[[], "datetime | None"] | None = None,
) -> None:
    """
    Liga ao SignalR e chama on_bid(lot_id, sale_id, highest_bid, timestamp_utc)
    para cada evento lot.bid recebido.

    Lógica de fecho:
    - Quando closing_date passou E não houve licitações há 2 minutos,
      começa a verificar o estado do leilão a cada ping.
    - Quando estado=4 é detectado, fecha o WS.
    - O polling deteta o novo leilão e start_signalr_thread cria nova ligação.
    """
    while True:
        if stop_event and stop_event.is_set():
            break
        try:
            sale_ids = get_sale_ids() if get_sale_ids else []
            if not sale_ids:
                logger.info("SignalR — sem leilões activos, a aguardar 60s...")
                time.sleep(60)
                continue

            primary = sale_ids[0]
            logger.info("SignalR — a negociar (sales=%s)...", sale_ids)
            azure_url, access_token = _proxy_negotiate(session, primary)
            connection_id, connection_token = _azure_negotiate(azure_url, access_token)

            ws_url = (
                f"{azure_url.replace('https://', 'wss://')}"
                f"&id={connection_token}"
                f"&access_token={access_token}"
            )

            ws = websocket.WebSocket()
            ws.connect(ws_url, header={
                "Origin": "https://carmarket.ayvens.com",
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:150.0) Gecko/20100101 Firefox/150.0",
            })

            handshake = json.dumps({"protocol": "json", "version": 1}) + RECORD_SEP
            ws.send(handshake)
            ws.settimeout(60)

            # Subscrever todos os leilões activos
            for sid in sale_ids:
                sub_headers = {
                    "X-Requested-With": "XMLHttpRequest",
                    "Referer": f"https://carmarket.ayvens.com/pt-pt/sales/{sid}/",
                    "Content-Type": "application/json",
                }
                try:
                    r1 = session.post(
                        f"https://carmarket.ayvens.com/signalRProxy/subscribeToLots?connectionId={connection_id}",
                        json=[f"$saleevent:{sid}"],
                        headers=sub_headers, timeout=10,
                    )
                    r1.raise_for_status()
                    r2 = session.post(
                        f"https://carmarket.ayvens.com/signalRProxy/subscribeToSaleEvents?connectionId={connection_id}",
                        json=[int(sid)],
                        headers=sub_headers, timeout=10,
                    )
                    r2.raise_for_status()
                    logger.info("SignalR — subscrito sale=%s", sid)
                except Exception as e:
                    logger.warning("SignalR — falha na subscrição sale=%s: %s", sid, e)

            closing_dt = get_closing_date() if get_closing_date else None
            logger.info("SignalR — ligado. Sales=%s | fecho=%s", sale_ids, closing_dt)

            last_bid_ts = time.time()   # última licitação recebida
            verificar_estado = False    # só True quando hora passou + 2min sem bids

            while True:
                if stop_event and stop_event.is_set():
                    ws.close()
                    return

                try:
                    raw = ws.recv()
                except websocket.WebSocketTimeoutException:
                    ws.send(json.dumps({"type": 6}) + RECORD_SEP)
                    continue
                except websocket.WebSocketConnectionClosedException:
                    logger.info("SignalR — ligação fechada pelo servidor, a reconectar...")
                    break

                if not raw:
                    logger.info("SignalR — recv vazio, a reconectar...")
                    break

                for msg in _parse_messages(raw):
                    msg_type = msg.get("type")

                    if msg_type == 6:
                        logger.info("SignalR — ping recebido")
                        ws.send(json.dumps({"type": 6}) + RECORD_SEP)

                        # Activar verificação de estado se hora de fecho passou
                        # e não houve licitações há 2 minutos
                        if closing_dt and not verificar_estado:
                            from datetime import timezone
                            now_utc = datetime.now(timezone.utc)
                            if closing_dt.tzinfo is None:
                                closing_dt = closing_dt.replace(tzinfo=timezone.utc)
                            if now_utc > closing_dt:
                                elapsed = time.time() - last_bid_ts
                                logger.info(
                                    "SignalR — hora de fecho passou | sem licitações há %.0fs (aguardar 120s)",
                                    elapsed
                                )
                                if elapsed > 120:
                                    verificar_estado = True
                                    logger.info("SignalR — a entrar em modo de validação de estado a cada ping")

                        # Verificar se leilão passou a estado=4
                        if verificar_estado and get_sale_ids:
                            activos = get_sale_ids()
                            logger.info("SignalR — validação estado | activos=%s | subscritos=%s", activos, sale_ids)
                            if not any(sid in activos for sid in sale_ids):
                                logger.info("SignalR — leilão(ões) %s encerrado(s). A fechar WS...", sale_ids)
                                ws.close()
                                break

                    elif msg.get("target") == "Notify" and msg_type in (1, "Invocation"):
                        for arg in msg.get("arguments", []):
                            if arg.get("type") != "lot.bid":
                                continue

                            bid_sale_id, lot_id = _parse_resource(arg.get("resource", ""))
                            highest_bid = arg.get("resourceData", {}).get("highestBid")
                            timestamp_utc = arg.get("timestampUtc", "")

                            if lot_id and highest_bid is not None:
                                last_bid_ts = time.time()
                                verificar_estado = False  # licitação recebida — resetar
                                logger.info("WS bid — lot: %s | %.0f€", lot_id, highest_bid)
                                on_bid(lot_id, bid_sale_id, float(highest_bid), timestamp_utc)

        except Exception as e:
            logger.error("SignalR — erro: %s. A reconectar em 15s...", e, exc_info=False)
            time.sleep(15)
