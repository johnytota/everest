import json
import requests
from bs4 import BeautifulSoup

cookies = json.load(open("cookies.json"))
s = requests.Session()
for k, v in cookies.items():
    s.cookies.set(k, v, domain="carmarket.ayvens.com")

headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept-Language": "pt-PT,pt;q=0.9",
}
resp = s.get("https://carmarket.ayvens.com/pt-pt/", headers=headers, timeout=15)

soup = BeautifulSoup(resp.text, "html.parser")
print("Autenticado:", '"IsAuthenticated":true' in resp.text)
print("URL final:", resp.url)

containers = soup.select("div.sale-container")
print("div.sale-container:", len(containers))

sales = soup.find_all(attrs={"data-saleid": True})
print("Elementos com data-saleId:", len(sales))
for el in sales[:5]:
    print(f"  tag={el.name} | classes={el.get('class')} | sale_id={el.get('data-saleid')}")

# Procurar pela flag PRT
prts = soup.find_all("use")
prt_flags = [u for u in prts if "PRT" in str(u.get("xlink:href", "") or u.get("href", ""))]
print("Flags PRT encontradas:", len(prt_flags))
