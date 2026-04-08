"""
Módulo de scraping do Ayvens Carmarket.
- Extrai leilões PT ativos da homepage
- Extrai todos os veículos de um leilão
"""

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

BASE_URL  = "https://carmarket.ayvens.com"
HOME_URL  = f"{BASE_URL}/pt-pt/"
SALE_URL  = f"{BASE_URL}/pt-pt/sales/{{sale_id}}/"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "pt-PT,pt;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Referer": "https://carmarket.ayvens.com/pt-pt/",
}


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class Leilao:
    sale_id:      str
    nome:         str
    descricao:    str
    sale_type:    str   # Auction, Tender, FlashSale
    data_inicio:  str
    data_fim:     str
    closing_date: str
    estado:       int   # 2=published, 3=opened
    is_extended:  bool
    num_veiculos: int
    scrape_ts:    datetime = field(default_factory=datetime.utcnow)


@dataclass
class Veiculo:
    lot_id:        str
    sale_id:       str
    numero_lote:   str
    marca_modelo:  str
    versao:        str
    matricula:     str
    km:            str
    data_registo:  str
    combustivel:   str
    caixa:         str
    localizacao:   str
    fornecedor:    str
    chassis:       str
    bid_amount:    float | None
    offers_count:  int
    is_sold:       bool
    is_withdrawn:  bool
    imagem_url:    str
    # Detalhes expandíveis
    carrocaria:       str = ""
    portas:           str = ""
    lugares:          str = ""
    categoria:        str = ""
    cor_exterior:     str = ""
    ano_construcao:   str = ""
    potencia_cv:      str = ""
    cilindrada:       str = ""
    eurotax_venda:    str = ""
    eurotax_compra:   str = ""
    doc_manutencao:   str = ""
    doc_peritagem:    str = ""
    scrape_ts:     datetime = field(default_factory=datetime.utcnow)


# ---------------------------------------------------------------------------
# Homepage — lista de leilões PT
# ---------------------------------------------------------------------------

def get_leiloes_pt(session: requests.Session) -> list[Leilao]:
    """
    Extrai os leilões PT ativos da homepage.
    Os leilões PT aparecem na secção 'Convites VIP' do HTML.
    """
    try:
        resp = session.get(HOME_URL, headers=HEADERS, timeout=15)
        resp.raise_for_status()
    except requests.RequestException as e:
        logger.error("Erro ao obter homepage: %s", e)
        return []

    soup = BeautifulSoup(resp.text, "html.parser")
    leiloes = []

    # Todos os sale-containers da homepage
    for container in soup.select("div.sale-container"):
        sale_id   = container.get("data-saleid", "")
        sale_type = container.get("data-sale-type", "")

        # Filtrar apenas Portugal — flag PRT no SVG dentro do container
        if not container.select_one('use[xlink\\:href="#icon-round-PRT"]'):
            continue

        # Dados de tempo do bloco realtime-section
        status_el = container.select_one("h3.sale-status")
        data_inicio  = status_el.get("data-salestart", "")   if status_el else ""
        data_fim     = status_el.get("data-saleend", "")     if status_el else ""
        closing_date = status_el.get("data-closingdate", "") if status_el else ""
        estado       = int(status_el.get("data-salestatus", 0)) if status_el else 0
        is_extended  = status_el.get("data-isextended", "false").lower() == "true" if status_el else False

        # Nome do leilão
        nome_el = container.select_one("h2.card-subtitle a")
        nome = nome_el.get_text(strip=True) if nome_el else ""

        # Descrição do leilão
        desc_el = container.select_one("p.sales-description")
        descricao = desc_el.get_text(strip=True) if desc_el else ""

        # Número de veículos
        num_el = container.select_one("div.sale-remaining-container span.align-middle")
        num_veiculos = int(num_el.get_text(strip=True)) if num_el else 0

        leilao = Leilao(
            sale_id=sale_id,
            nome=nome,
            descricao=descricao,
            sale_type=sale_type,
            data_inicio=data_inicio,
            data_fim=data_fim,
            closing_date=closing_date,
            estado=estado,
            is_extended=is_extended,
            num_veiculos=num_veiculos,
        )
        leiloes.append(leilao)
        logger.info("Leilão PT encontrado: %s (%s) — %d veículos", sale_id, nome, num_veiculos)

    logger.info("Total de leilões PT: %d", len(leiloes))
    return leiloes


# ---------------------------------------------------------------------------
# Página do leilão — lista de veículos
# ---------------------------------------------------------------------------

def _parse_bid_area(data_str: str) -> tuple[float | None, int]:
    """
    Extrai BidAmount e OffersCount do atributo data-bid-area-information.
    Retorna (bid_amount, offers_count).
    """
    if not data_str:
        return None, 0
    try:
        data = json.loads(data_str)
        offer = data.get("CurrentOfferModel", {})
        bid_amount   = offer.get("BidAmount")
        offers_count = offer.get("OffersCount", 0)
        return (float(bid_amount) if bid_amount else None), int(offers_count)
    except (json.JSONDecodeError, TypeError, ValueError) as e:
        logger.warning("Erro ao parsear bid-area: %s", e)
        return None, 0


def _parse_watchlist(data_str: str) -> tuple[bool, bool]:
    """
    Extrai IsSold e IsWithdrawn do atributo data-watchlist-information.
    Retorna (is_sold, is_withdrawn).
    """
    if not data_str:
        return False, False
    try:
        data = json.loads(data_str)
        return bool(data.get("IsSold", False)), bool(data.get("IsWithdrawn", False))
    except (json.JSONDecodeError, TypeError):
        return False, False


def _parse_specs(article) -> dict:
    """
    Extrai especificações do veículo (matrícula, km, combustível, etc.)
    a partir dos elementos vehicle-specifications-text.
    """
    specs = {
        "matricula":   "",
        "km":          "",
        "data_registo": "",
        "combustivel": "",
        "caixa":       "",
        "localizacao": "",
        "fornecedor":  "",
        "chassis":     "",
    }

    spec_items = article.select("div.vehicle-specifications-text")

    for item in spec_items:
        text = item.get_text(strip=True)

        # Matrícula — formato PT: XX-00-XX ou XX-XX-00
        if re.match(r"^[A-Z0-9]{2}-[A-Z0-9]{2}-[A-Z0-9]{2}$", text):
            specs["matricula"] = text

        # Km e data de registo — "240 938 km | 10/02/2023"
        elif "km" in text and "|" in text:
            parts = text.split("|")
            specs["km"]          = parts[0].replace("km", "").replace("\xa0", "").strip()
            specs["data_registo"] = parts[1].strip()

        # Combustível e caixa — "Gasolina | Automático"
        elif "|" in text and "km" not in text and "Localização" not in text:
            parts = text.split("|")
            if len(parts) == 2:
                specs["combustivel"] = parts[0].strip()
                specs["caixa"]       = parts[1].strip()

        # Localização
        elif text.startswith("Localização:"):
            specs["localizacao"] = text.replace("Localização:", "").strip()

        # Fornecedor
        elif text.startswith("Fornecedor:"):
            specs["fornecedor"] = text.replace("Fornecedor:", "").strip()

    return specs


def _parse_details(article) -> dict:
    """
    Extrai os campos do painel de detalhes expandível
    (div#vehicle-{lot_id}-container-details).
    """
    details = {
        "versao_det":    "",
        "carrocaria":    "",
        "portas":        "",
        "lugares":       "",
        "categoria":     "",
        "chassis":       "",
        "cor_exterior":  "",
        "ano_construcao": "",
        "potencia_cv":   "",
        "cilindrada":    "",
        "eurotax_venda": "",
        "eurotax_compra": "",
        "doc_manutencao": "",
        "doc_peritagem":  "",
    }

    # Mapeamento título → chave
    mapa = {
        "Versão":               "versao_det",
        "Carroçaria":           "carrocaria",
        "Portas":               "portas",
        "Lugares":              "lugares",
        "Categoria":            "categoria",
        "Chassis":              "chassis",
        "Cor exterior":         "cor_exterior",
        "Ano de construção":    "ano_construcao",
        "Potência (cv)":        "potencia_cv",
        "Cilindrada":           "cilindrada",
        "Eurotax (venda)":      "eurotax_venda",
        "Eurotax (compra)":     "eurotax_compra",
    }

    for row in article.select("ul.details-row"):
        titulo = row.select_one("li.details-title")
        info   = row.select_one("li.details-info")
        if not titulo or not info:
            continue
        chave = mapa.get(titulo.get_text(strip=True))
        if chave:
            details[chave] = info.get_text(strip=True)

    # Links de documentos
    link_manut = article.select_one("a.js-tracking-maintenance")
    if link_manut:
        details["doc_manutencao"] = link_manut.get("href", "")

    link_perit = article.select_one("a.js-tracking-expertise")
    if link_perit:
        details["doc_peritagem"] = link_perit.get("href", "")

    return details


GETLOTS_URL = f"{BASE_URL}/sale/getlots"


def _parse_articles(articles, sale_id: str) -> list[Veiculo]:
    """Converte uma lista de article tags em objetos Veiculo."""
    veiculos = []
    for article in articles:
        lot_id     = article.get("data-lotid", "")
        numero     = article.get("data-lotnumber", "")
        sale_ev_id = article.get("data-saleeventid", sale_id)

        if not lot_id:
            continue

        titulo_el = article.select_one("h2.vehicle-title")
        if titulo_el:
            titulo_text = titulo_el.get_text(separator=" ", strip=True)
            marca_modelo = re.sub(r"^\d+\.\s*", "", titulo_text)
        else:
            marca_modelo = ""

        versao_el = article.select_one("p.vehicle-make")
        versao = versao_el.get_text(strip=True) if versao_el else ""

        img_el = article.select_one("img.img-thumbnail")
        imagem_url = img_el.get("src", "") if img_el else ""

        bid_area_str = article.select_one("div.vehicle-bid-area")
        bid_amount, offers_count = _parse_bid_area(
            bid_area_str.get("data-bid-area-information", "") if bid_area_str else ""
        )

        watchlist_el = article.select_one("div.vehicle-watchlist-ssr")
        is_sold, is_withdrawn = _parse_watchlist(
            watchlist_el.get("data-watchlist-information", "") if watchlist_el else ""
        )

        specs   = _parse_specs(article)
        details = _parse_details(article)

        veiculos.append(Veiculo(
            lot_id=lot_id,
            sale_id=sale_ev_id,
            numero_lote=numero,
            marca_modelo=marca_modelo,
            versao=versao or details["versao_det"],
            matricula=specs["matricula"],
            km=specs["km"],
            data_registo=specs["data_registo"],
            combustivel=specs["combustivel"],
            caixa=specs["caixa"],
            localizacao=specs["localizacao"],
            fornecedor=specs["fornecedor"],
            chassis=details["chassis"] or specs["chassis"],
            bid_amount=bid_amount,
            offers_count=offers_count,
            is_sold=is_sold,
            is_withdrawn=is_withdrawn,
            imagem_url=imagem_url,
            carrocaria=details["carrocaria"],
            portas=details["portas"],
            lugares=details["lugares"],
            categoria=details["categoria"],
            cor_exterior=details["cor_exterior"],
            ano_construcao=details["ano_construcao"],
            potencia_cv=details["potencia_cv"],
            cilindrada=details["cilindrada"],
            eurotax_venda=details["eurotax_venda"],
            eurotax_compra=details["eurotax_compra"],
            doc_manutencao=details["doc_manutencao"],
            doc_peritagem=details["doc_peritagem"],
        ))
    return veiculos


def get_veiculos_leilao(session: requests.Session, sale_id: str) -> list[Veiculo]:
    """
    Extrai todos os veículos de um leilão, paginando via POST /sale/getlots.
    """
    sale_url = SALE_URL.format(sale_id=sale_id)

    # Primeira página — GET normal
    try:
        resp = session.get(sale_url, headers={**HEADERS, "Referer": HOME_URL}, timeout=20)
        resp.raise_for_status()
    except requests.RequestException as e:
        logger.error("Erro ao obter leilão %s: %s", sale_id, e)
        return []

    # Extrair antiForgeryToken da página
    token_match = re.search(r"window\.antiForgeryToken\s*=\s*'([^']+)'", resp.text)
    anti_forgery_token = token_match.group(1) if token_match else ""
    if not anti_forgery_token:
        logger.warning("Leilão %s — antiForgeryToken não encontrado, paginação pode falhar.", sale_id)

    soup = BeautifulSoup(resp.text, "html.parser")
    veiculos = _parse_articles(soup.select("article.card-vehicle"), sale_id)
    logger.info("Leilão %s — página 1: %d veículos", sale_id, len(veiculos))

    # Páginas seguintes — POST /sale/getlots
    page_index = 1
    post_headers = {
        **HEADERS,
        "Content-Type": "application/json",
        "Referer": sale_url,
        "Origin": BASE_URL,
        "X-Requested-With": "XMLHttpRequest",
        "RequestVerificationToken": anti_forgery_token,
    }

    while True:
        excluded = [v.lot_id for v in veiculos]
        payload = {
            "searchCriteria": {
                "Makes": [], "Models": [], "TransmissionTypes": [],
                "FuelTypes": [], "ExcludedLotsIds": excluded,
            },
            "pageIndex": page_index,
            "saleEventId": int(sale_id),
            "orderBy": 0,
            "direction": 1,
        }

        try:
            r = session.post(GETLOTS_URL, json=payload, headers=post_headers, timeout=20)
            r.raise_for_status()
        except requests.RequestException as e:
            logger.error("Leilão %s — erro na paginação (página %d): %s", sale_id, page_index, e)
            break

        articles = BeautifulSoup(r.text, "html.parser").select("article.card-vehicle")
        if not articles:
            break

        novos = _parse_articles(articles, sale_id)
        veiculos.extend(novos)
        logger.info("Leilão %s — página %d: +%d veículos (total: %d)", sale_id, page_index, len(novos), len(veiculos))
        page_index += 1

    logger.info("Leilão %s — %d veículos parseados no total", sale_id, len(veiculos))
    return veiculos


def get_anti_forgery_token(session: requests.Session, sale_id: str) -> str | None:
    """
    Extrai o antiForgeryToken da página do leilão.
    Necessário para o SignalR negotiate (fase 2).
    """
    url = SALE_URL.format(sale_id=sale_id)
    try:
        resp = session.get(url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        match = re.search(r"window\.antiForgeryToken\s*=\s*'([^']+)'", resp.text)
        if match:
            return match.group(1)
    except requests.RequestException as e:
        logger.error("Erro ao obter antiForgeryToken: %s", e)
    return None
