"""
Módulo de autenticação para o Ayvens Carmarket.

Fluxo:
1. Tenta carregar cookies guardados em ficheiro
2. Valida se a sessão ainda é válida (request à homepage)
3. Se inválida, usa Playwright (browser real headless) para fazer login
4. Extrai os cookies do browser e guarda em ficheiro
5. Devolve requests.Session pronta a usar
"""

import json
import logging
import time
from pathlib import Path

import requests
from playwright.sync_api import sync_playwright

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

REQUIRED_COOKIES = {".ASPXAUTHCARMARKETV2", ".Carmarket.Cookie"}


def _save_cookies(cookies: dict) -> None:
    COOKIES_FILE.write_text(json.dumps(cookies, indent=2))
    logger.info("Cookies guardados em %s", COOKIES_FILE)


def _load_cookies(session: requests.Session) -> bool:
    """Carrega cookies do ficheiro. Retorna True se válidos e não expirados."""
    if not COOKIES_FILE.exists():
        logger.info("Ficheiro de cookies não encontrado.")
        return False

    try:
        cookies_dict = json.loads(COOKIES_FILE.read_text())
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("Erro ao ler cookies: %s", e)
        return False

    if not REQUIRED_COOKIES.issubset(cookies_dict.keys()):
        logger.info("Cookies incompletos — faltam cookies de autenticação.")
        return False

    expiration_ms = cookies_dict.get("CarmarketV2SessionExpirationTime")
    if expiration_ms:
        if time.time() > int(expiration_ms) / 1000:
            logger.info("Cookie de sessão expirado.")
            return False

    for name, value in cookies_dict.items():
        session.cookies.set(name, value, domain="carmarket.ayvens.com")

    logger.info("Cookies carregados do ficheiro.")
    return True


def is_session_valid(session: requests.Session) -> bool:
    """Valida a sessão fazendo um pedido à homepage."""
    try:
        resp = session.get(HOME_URL, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        if '"IsAuthenticated":true' in resp.text:
            logger.info("Sessão válida confirmada.")
            return True
        logger.info("Sessão inválida.")
        return False
    except requests.RequestException as e:
        logger.error("Erro ao validar sessão: %s", e)
        return False


def _login_playwright(username: str, password: str) -> dict | None:
    """
    Usa Playwright (browser headless) para fazer login no Ayvens Carmarket.
    Devolve dicionário de cookies ou None em caso de falha.
    """
    logger.info("A iniciar login via Playwright...")

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=False,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
            ],
        )
        context = browser.new_context(
            user_agent=HEADERS["User-Agent"],
            locale="pt-PT",
            viewport={"width": 1280, "height": 800},
        )
        # Ocultar WebDriver flag
        context.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")

        # Carregar cookies guardados no contexto Playwright (inclui consentimento GDPR)
        # Os cookies de autenticação NÃO são pré-carregados para garantir que o check
        # de login só passa quando cookies frescos são recebidos do servidor.
        if COOKIES_FILE.exists():
            try:
                saved = json.loads(COOKIES_FILE.read_text())
                pw_cookies = [
                    {"name": k, "value": v, "domain": ".carmarket.ayvens.com", "path": "/"}
                    for k, v in saved.items()
                    if k not in REQUIRED_COOKIES
                ]
                context.add_cookies(pw_cookies)
                logger.info("Playwright — %d cookies pré-carregados no contexto.", len(pw_cookies))
            except Exception as e:
                logger.warning("Playwright — erro ao pré-carregar cookies: %s", e)

        page = context.new_page()

        try:
            # Visitar homepage e aguardar que o JS inicialize completamente
            logger.info("Playwright — a carregar homepage...")
            page.goto(HOME_URL, wait_until="networkidle", timeout=30000)

            # Aceitar banner de cookies GDPR se aparecer (não bloqueante)
            try:
                page.wait_for_selector("button#onetrust-accept-btn-handler", timeout=10000, state="visible")
                logger.info("Playwright — a aceitar banner de cookies GDPR...")
                page.click("button#onetrust-accept-btn-handler")
                page.wait_for_timeout(1000)
                logger.info("Playwright — cookies GDPR aceites.")
            except Exception:
                logger.info("Playwright — banner de cookies não apareceu, a continuar...")

            # Fechar popup promocional se aparecer
            try:
                page.wait_for_selector("button.ab_widget_container_popin-image_close_button", timeout=5000, state="visible")
                close_btn = page.query_selector("button.ab_widget_container_popin-image_close_button")
                if close_btn and close_btn.is_visible():
                    logger.info("Playwright — a fechar popup promocional...")
                    close_btn.click()
                    page.wait_for_timeout(800)
                    logger.info("Playwright — popup AB Tasty fechado.")
            except Exception:
                logger.info("Playwright — popup promocional não apareceu, a continuar...")

            page.wait_for_timeout(2000)

            logger.info("Playwright — URL atual: %s", page.url)

            # Tentar clicar no botão de login
            login_found = False
            for selector in [
                "#btn_login",
                "#BtnHeader_login",
                "a#BtnHeader_login",
                "#btn_signIn",
                "button#btn_signIn",
                "carmarket-button[buttonid='btn_signIn'] button",
                "button.secondary:has-text('Login')",
                "button:has-text('Login')",
            ]:
                try:
                    el = page.query_selector(selector)
                    if el and el.is_visible():
                        logger.info("Playwright — a clicar botão login (%s)...", selector)
                        el.click()
                        login_found = True
                        break
                except Exception as e:
                    logger.warning("Playwright — erro ao clicar %s: %s", selector, e)

            if not login_found:
                logger.error("Botão de login não encontrado.")
                browser.close()
                return None

            # Aguardar modal de login abrir
            logger.info("Playwright — a aguardar modal de login...")
            page.wait_for_timeout(1500)
            page.wait_for_selector("#userName, input[name='userName']", state="visible", timeout=10000)

            # Preencher formulário do modal — tenta por ID, fallback por name
            if page.query_selector("#userName"):
                logger.info("Playwright — a preencher credenciais (por ID)...")
                page.fill("#userName", username)
                page.fill("#password", password)
            else:
                logger.info("Playwright — a preencher credenciais (por name)...")
                page.fill("input[name='userName']", username)
                page.fill("input[name='password']", password)

            # Dispensar banner de cookies se estiver ativo
            for cookie_sel in [
                "#onetrust-accept-btn-handler",
                "button#accept-cookies",
                "button.cookie-accept",
                "button:has-text('Aceitar')",
                "button:has-text('Accept')",
            ]:
                try:
                    el = page.query_selector(cookie_sel)
                    if el and el.is_visible():
                        logger.info("Playwright — a dispensar banner de cookies (%s)...", cookie_sel)
                        el.click()
                        page.wait_for_timeout(500)
                        break
                except Exception:
                    pass

            # Submeter
            submit_found = False
            for submit_sel in [
                "button#btn_login",
                "carmarket-button[buttonid='btn_login'] button",
                "button.signin-btn",
                "button[type='submit']",
            ]:
                try:
                    el = page.query_selector(submit_sel)
                    if el and el.is_visible():
                        logger.info("Playwright — a submeter login (%s)...", submit_sel)
                        el.click()
                        submit_found = True
                        break
                except Exception as e:
                    logger.warning("Playwright — erro ao submeter %s: %s", submit_sel, e)
            if not submit_found:
                logger.error("Botão de submissão do login não encontrado.")
                browser.close()
                return None

            # Aguardar fecho do modal ou navegação
            page.wait_for_load_state("networkidle", timeout=30000)

            # Aguardar que os cookies de autenticação apareçam
            logger.info("Playwright — a verificar autenticação...")
            for _ in range(10):
                pw_cookies = context.cookies()
                cookies_dict = {c["name"]: c["value"] for c in pw_cookies}
                if REQUIRED_COOKIES.issubset(cookies_dict.keys()):
                    break
                page.wait_for_timeout(1000)
            else:
                logger.error("Login falhado — cookies de autenticação não recebidos após submissão.")
                browser.close()
                return None

            # Extrair cookies
            pw_cookies = context.cookies()
            cookies_dict = {c["name"]: c["value"] for c in pw_cookies}

            # Remover CarmarketV2SessionExpirationTime se já estiver expirado.
            # O site não o atualiza durante o login, ficando o valor antigo nos cookies
            # pré-carregados — o que causaria um loop imediato na thread de renovação.
            exp = cookies_dict.get("CarmarketV2SessionExpirationTime")
            if exp and int(exp) / 1000 <= time.time():
                del cookies_dict["CarmarketV2SessionExpirationTime"]
                logger.info("Playwright — cookie de expiração já expirado, removido.")

            if not REQUIRED_COOKIES.issubset(cookies_dict.keys()):
                logger.error("Login falhado — cookies de autenticação não recebidos.")
                logger.debug("Cookies recebidos: %s", list(cookies_dict.keys()))
                browser.close()
                return None

            logger.info("Login via Playwright bem sucedido.")
            browser.close()
            return cookies_dict

        except Exception as e:
            logger.error("Erro durante login Playwright: %s", e, exc_info=True)
            browser.close()
            return None


def session_expiration_ts(session: requests.Session) -> float | None:
    """Devolve o timestamp de expiração da sessão em segundos Unix, ou None."""
    val = session.cookies.get("CarmarketV2SessionExpirationTime", domain="carmarket.ayvens.com")
    if not val:
        try:
            cookies_dict = json.loads(COOKIES_FILE.read_text())
            val = cookies_dict.get("CarmarketV2SessionExpirationTime")
        except Exception:
            return None
    return int(val) / 1000 if val else None


def renew_session(session: requests.Session, username: str, password: str) -> bool:
    """
    Faz login via Playwright e atualiza os cookies da sessão in-place.
    Devolve True se bem sucedido.
    """
    cookies = _login_playwright(username, password)
    if not cookies:
        return False
    _save_cookies(cookies)
    session.cookies.clear()
    for name, value in cookies.items():
        session.cookies.set(name, value, domain="carmarket.ayvens.com")
    logger.info("Sessão renovada com sucesso.")
    return True


def get_authenticated_session(username: str, password: str) -> requests.Session | None:
    """
    Retorna uma sessão autenticada.

    1. Tenta cookies guardados → valida
    2. Se inválidos, faz login com Playwright → guarda novos cookies
    3. Devolve requests.Session ou None
    """
    session = requests.Session()
    session.headers.update(HEADERS)

    if _load_cookies(session):
        if is_session_valid(session):
            return session
        logger.info("Cookies carregados mas sessão inválida — a renovar login.")
        session.cookies.clear()

    # Login via Playwright
    cookies = _login_playwright(username, password)
    if not cookies:
        logger.error("Não foi possível autenticar.")
        return None

    _save_cookies(cookies)
    for name, value in cookies.items():
        session.cookies.set(name, value, domain="carmarket.ayvens.com")

    return session
