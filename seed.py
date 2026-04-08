"""
Script de seed para popular o MongoDB com dados de teste.
Cria leilões, veículos e histórico de preços simulados.
"""

import os
import random
from datetime import datetime, timedelta

from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv()

MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017/")
MONGO_DB  = os.getenv("MONGO_DB", "ayvens")

client = MongoClient(MONGO_URI)
db     = client[MONGO_DB]

# ---------------------------------------------------------------------------
# Dados de teste
# ---------------------------------------------------------------------------

CARROS = [
    ("VOLKSWAGEN Golf VIII", "1.5 TSI Life", "Gasoline", "Automático", "Hatchback", "5", "5", "Passageiros", "Cinzento Cinzento"),
    ("PEUGEOT 308", "1.5 BlueHDi Active", "Diesel", "Manual", "Hatchback", "5", "5", "Passageiros", "Branco Banquise"),
    ("RENAULT CLIO V", "1.0 TCe Zen", "Gasolina", "Manual", "Hatchback", "5", "5", "Passageiros", "Azul Iron"),
    ("TOYOTA YARIS", "1.0 VVT-i Comfort", "Gasolina", "Manual", "Hatchback", "5", "5", "Passageiros", "Vermelho"),
    ("MERCEDES-BENZ CLASSE A", "200 Style Plus 2.0", "Diesel", "Automático", "Hatchback", "5", "5", "Passageiros", "Preto Cosmos"),
    ("BMW SÉRIE 3", "318d Advantage 2.0", "Diesel", "Automático", "Berlina", "4", "5", "Passageiros", "Branco Alpino"),
    ("AUDI A3", "1.6 TDI Sport", "Diesel", "Manual", "Berlina", "4", "5", "Passageiros", "Cinzento Nardo"),
    ("FORD FOCUS", "1.5 EcoBoost ST-Line", "Gasolina", "Automático", "Carrinha", "5", "5", "Passageiros", "Azul Magnetic"),
    ("SEAT LEON", "1.5 TSI FR", "Gasolina", "Manual", "Hatchback", "5", "5", "Passageiros", "Laranja Valencia"),
    ("SKODA OCTAVIA", "2.0 TDI Style", "Diesel", "Automático", "Carrinha", "5", "5", "Passageiros", "Verde Racing"),
    ("OPEL ASTRA K", "1.5 D Business", "Diesel", "Manual", "Hatchback", "5", "5", "Passageiros", "Preto"),
    ("NISSAN QASHQAI", "1.3 DIG-T Acenta", "Gasolina", "Automático", "SUV", "5", "5", "Passageiros", "Branco Perola"),
    ("CITROËN C3", "1.5 BlueHDi Feel", "Diesel", "Manual", "Hatchback", "5", "5", "Passageiros", "Azul Fogo"),
    ("KIA SPORTAGE", "1.6 CRDI GT-Line", "Diesel", "Automático", "SUV", "5", "5", "Passageiros", "Cinzento Graphite"),
    ("VOLVO V60", "2.0 T6 AWD Inscription", "Híbrido", "Automático", "Carrinha", "5", "5", "Passageiros", "Branco Crystal"),
]

MATRICULAS = [
    "AX-66-LV", "BC-82-OH", "AO-93-HQ", "AT-41-FT", "BE-75-ZP",
    "AV-06-GO", "AQ-99-LF", "AB-12-CD", "EF-34-GH", "IJ-56-KL",
    "MN-78-OP", "QR-90-ST", "UV-11-WX", "YZ-22-AB", "CD-33-EF",
]

LOCALIZACOES = ["Lisboa", "Porto", "Oriente", "Setúbal", "Braga", "Coimbra", "Faro"]
FORNECEDORES = ["LeasePlan", "ALD Automotive", "Arval", "Frota", "Alphabet"]

NOME_LEILAO = "Viaturas usadas para Leilão em Portugal - {ref}"


def make_matricula(idx):
    letras = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    return f"{letras[idx % 26]}{letras[(idx * 3) % 26]}-{idx % 100:02d}-{letras[(idx * 7) % 26]}{letras[(idx * 11) % 26]}"


def rand_date(base: datetime, delta_days: int) -> datetime:
    return base + timedelta(days=delta_days, hours=random.randint(8, 18))


def iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")


# ---------------------------------------------------------------------------
# Leilões — 1 atual + 5 anteriores
# ---------------------------------------------------------------------------

now = datetime.utcnow()

leiloes_data = []
for i in range(6):
    dias_atras = i * 30
    inicio = rand_date(now - timedelta(days=dias_atras + 7), 0)
    fim    = inicio + timedelta(days=7)
    estado = 3 if i == 0 else 2  # só o mais recente está aberto

    leiloes_data.append({
        "sale_id":      f"4{1000 + i}",
        "nome":         NOME_LEILAO.format(ref=f"{146000 + i * 100}"),
        "descricao":    "LEILAO SELECAO AYVENS",
        "sale_type":    "Auction",
        "data_inicio":  iso(inicio),
        "data_fim":     iso(fim),
        "closing_date": iso(fim),
        "estado":       estado,
        "is_extended":  False,
        "num_veiculos": 15,
        "scrape_ts":    inicio,
    })

# ---------------------------------------------------------------------------
# Veículos e histórico de preços
# ---------------------------------------------------------------------------

veiculos_docs   = []
historico_docs  = []

lot_counter = 2000900

for sale_idx, leilao in enumerate(leiloes_data):
    sale_id   = leilao["sale_id"]
    data_ini  = datetime.strptime(leilao["data_inicio"], "%Y-%m-%dT%H:%M:%S.000Z")
    is_atual  = sale_idx == 0

    for i, (marca, versao, comb, caixa, carrocaria, portas, lugares, categoria, cor) in enumerate(CARROS):
        lot_id    = str(lot_counter)
        lot_counter += 1
        matricula = MATRICULAS[i % len(MATRICULAS)]

        # Preço base sobe ligeiramente nos leilões mais recentes
        base_price = random.randint(6, 40) * 1000
        km_val     = random.randint(30, 220) * 1000

        veiculo = {
            "lot_id":       lot_id,
            "sale_id":      sale_id,
            "numero_lote":  str(i + 1),
            "marca_modelo": marca,
            "versao":       versao,
            "matricula":    matricula,
            "km":           f"{km_val:,}".replace(",", "\u00a0"),
            "data_registo": f"{random.randint(1, 28):02d}/{random.randint(1, 12):02d}/{random.randint(2018, 2023)}",
            "combustivel":  comb,
            "caixa":        caixa,
            "localizacao":  random.choice(LOCALIZACOES),
            "fornecedor":   random.choice(FORNECEDORES),
            "chassis":      f"WBA{random.randint(1000000, 9999999)}",
            "bid_amount":   float(base_price),
            "offers_count": random.randint(0, 12),
            "is_sold":      not is_atual,
            "is_withdrawn": False,
            "imagem_url":   "",
            "carrocaria":   carrocaria,
            "portas":       portas,
            "lugares":      lugares,
            "categoria":    categoria,
            "cor_exterior": cor,
            "ano_construcao": str(random.randint(2018, 2023)),
            "potencia_cv":  str(random.choice([90, 110, 130, 150, 190, 250])),
            "cilindrada":   str(random.choice([999, 1197, 1499, 1598, 1968, 2993])),
            "eurotax_venda": f"{base_price * random.uniform(1.1, 1.4):,.0f} €".replace(",", "\u00a0"),
            "eurotax_compra": f"{base_price * random.uniform(0.85, 1.0):,.0f} €".replace(",", "\u00a0"),
            "doc_manutencao": "",
            "doc_peritagem":  "",
            "scrape_ts":    data_ini,
        }
        veiculos_docs.append(veiculo)

        # Histórico de preços — 4 a 8 registos por leilão
        preco   = base_price - random.randint(2, 8) * 100
        ts      = data_ini + timedelta(hours=random.randint(1, 12))
        n_steps = random.randint(4, 8)
        for _ in range(n_steps):
            historico_docs.append({
                "lot_id":    lot_id,
                "valor":     float(preco),
                "timestamp": ts,
            })
            preco += 100
            ts    += timedelta(minutes=random.randint(5, 120))

# ---------------------------------------------------------------------------
# Inserir na BD
# ---------------------------------------------------------------------------

# Limpar apenas dados de seed anteriores (sale_ids com prefixo 4100x)
seed_ids = [l["sale_id"] for l in leiloes_data]
db.leiloes.delete_many({"sale_id": {"$in": seed_ids}})
db.veiculos.delete_many({"sale_id": {"$in": seed_ids}})
lot_ids = [v["lot_id"] for v in veiculos_docs]
db.historico_precos.delete_many({"lot_id": {"$in": lot_ids}})

db.leiloes.insert_many(leiloes_data)
db.veiculos.insert_many(veiculos_docs)
db.historico_precos.insert_many(historico_docs)

print(f"OK {len(leiloes_data)} leiloes inseridos")
print(f"OK {len(veiculos_docs)} veiculos inseridos")
print(f"OK {len(historico_docs)} registos de preco inseridos")
