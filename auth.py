"""
Módulo de autenticação para o Ayvens Carmarket.
- Carrega cookies guardados em ficheiro
- Valida se a sessão ainda é válida
- Faz login automático quando necessário
- Guarda cookies para reutilização
"""

import json
import logging
import os
import time
from pathlib import Path

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

COOKIES_FILE = Path("cookies.json")

LOGIN_URL = "https://carmarket.ayvens.com/Account/Login/"
HOME_URL  = "https://carmarket.ayvens.com/pt-pt/"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "pt-PT,pt;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

# Cookies obrigatórios para uma sessão válida
REQUIRED_COOKIES = {".ASPXAUTHCARMARKETV2", ".Carmarket.Cookie"}


def _save_cookies(session: requests.Session) -> None:
    """Guarda os cookies da sessão em ficheiro JSON."""
    cookies_dict = dict(session.cookies)
    COOKIES_FILE.write_text(json.dumps(cookies_dict, indent=2))
    logger.info("Cookies guardados em %s", COOKIES_FILE)


def _load_cookies(session: requests.Session) -> bool:
    """
    Carrega cookies do ficheiro para a sessão.
    Retorna True se o ficheiro existe e tem os cookies obrigatórios.
    """
    if not COOKIES_FILE.exists():
        logger.info("Ficheiro de cookies não encontrado.")
        return False

    try:
        cookies_dict = json.loads(COOKIES_FILE.read_text())
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("Erro ao ler cookies: %s", e)
        return False

    # Verificar se tem os cookies obrigatórios
    if not REQUIRED_COOKIES.issubset(cookies_dict.keys()):
        logger.info("Cookies incompletos — faltam cookies de autenticação.")
        return False

    # Verificar expiração via CarmarketV2SessionExpirationTime
    expiration_ms = cookies_dict.get("CarmarketV2SessionExpirationTime")
    if expiration_ms:
        expiration_s = int(expiration_ms) / 1000
        if time.time() > expiration_s:
            logger.info("Cookie de sessão expirado.")
            return False

    for name, value in cookies_dict.items():
        session.cookies.set(name, value, domain="carmarket.ayvens.com")

    logger.info("Cookies carregados do ficheiro.")
    return True


def _is_session_valid(session: requests.Session) -> bool:
    """
    Valida a sessão fazendo um pedido à homepage.
    Retorna True se estamos autenticados (IsAuthenticated: true no sessionStorage).
    """
    try:
        resp = session.get(HOME_URL, headers=HEADERS, timeout=15)
        resp.raise_for_status()

        # O site injeta IsAuthenticated no sessionStorage dentro do HTML
        if '"IsAuthenticated":true' in resp.text:
            logger.info("Sessão válida confirmada.")
            return True

        # Se redireccionou para login ou não tem autenticação
        if "Account/Login" in resp.url or '"IsAuthenticated":false' in resp.text:
            logger.info("Sessão inválida — redirecionado para login.")
            return False

        # Verificação extra: se não encontrou o marcador, assumir inválido
        logger.warning("Não foi possível confirmar autenticação — a fazer login.")
        return False

    except requests.RequestException as e:
        logger.error("Erro ao validar sessão: %s", e)
        return False


def _get_login_token(session: requests.Session) -> str | None:
    """
    Obtém o token anti-CSRF da página de login (campo __RequestVerificationToken).
    """
    try:
        resp = session.get(LOGIN_URL, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        token_input = soup.find("input", {"name": "__RequestVerificationToken"})
        if token_input:
            return token_input.get("value")
        logger.warning("Token CSRF não encontrado na página de login.")
        return None
    except requests.RequestException as e:
        logger.error("Erro ao obter página de login: %s", e)
        return None


def _do_login(session: requests.Session, username: str, password: str) -> bool:
    """
    Executa o login com username e password.
    Tenta primeiro com token CSRF; se não encontrar, tenta sem ele.
    Retorna True se o login foi bem sucedido.
    """
    logger.info("A iniciar login...")

    token = _get_login_token(session)

    payload = {
        "Login":    username,
        "Password": password,
        "RememberMe": "false",
    }
    if token:
        payload["__RequestVerificationToken"] = token
    else:
        logger.warning("Token CSRF não encontrado — a tentar login sem token.")

    headers = {
        **HEADERS,
        "Content-Type": "application/x-www-form-urlencoded",
        "Referer": LOGIN_URL,
        "Origin":  "https://carmarket.ayvens.com",
    }

    try:
        resp = session.post(
            LOGIN_URL,
            data=payload,
            headers=headers,
            timeout=15,
            allow_redirects=True,
        )
        resp.raise_for_status()

        # Verificar se o login foi bem sucedido
        if '"IsAuthenticated":true' in resp.text:
            logger.info("Login bem sucedido.")
            _save_cookies(session)
            return True

        # Se ainda está na página de login, as credenciais estão erradas
        if "Account/Login" in resp.url:
            logger.error("Login falhado — credenciais incorretas.")
            return False

        # Sucesso com redirect para outra página — só guarda se tiver cookies de auth
        if resp.status_code == 200 and "carmarket.ayvens.com" in resp.url:
            cookies = dict(session.cookies)
            if REQUIRED_COOKIES.issubset(cookies.keys()):
                logger.info("Login bem sucedido (redirect).")
                _save_cookies(session)
                return True
            logger.error("Login falhado — cookies de autenticação não recebidos.")
            return False

        logger.error("Login falhado — resposta inesperada: %s", resp.url)
        return False

    except requests.RequestException as e:
        logger.error("Erro durante login: %s", e)
        return False


def get_authenticated_session(username: str, password: str) -> requests.Session | None:
    """
    Retorna uma sessão autenticada.
    
    Fluxo:
    1. Tenta carregar cookies guardados
    2. Valida se a sessão ainda é válida
    3. Se inválida, faz login e guarda novos cookies
    4. Retorna a sessão pronta a usar ou None em caso de falha
    """
    session = requests.Session()
    session.headers.update(HEADERS)

    # Tentar usar cookies existentes
    if _load_cookies(session):
        if _is_session_valid(session):
            return session
        else:
            logger.info("Cookies carregados mas sessão inválida — a renovar login.")

    # Fazer login
    if _do_login(session, username, password):
        return session

    logger.error("Não foi possível autenticar.")
    return None
