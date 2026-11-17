import csv
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urljoin
import requests
from bs4 import BeautifulSoup
import duckdb

BASE_DIR = r"C:\Users\kbadmin\Documents\Projetos\01_Ecossistema_WiNS\Engenharia"
MAIN_DB = os.path.join(BASE_DIR, "Banco_Dados", "wins_engenharia.duckdb")
OUT_CSV = os.path.join(BASE_DIR, "Arquivos_Tratados", "whatsapp_oficial_sites.csv")

WA_URL_RE = re.compile(r"(?:wa\.me/|api\.whatsapp\.com/send\?[^\"'\s]*phone=|whatsapp://send\?[^\"'\s]*phone=)(\+?55)?(\d{10,13})", re.I)
TEL_RE = re.compile(r"tel:(\+?55)?(\d{10,11})", re.I)
WA_TEXT_RE = re.compile(r"whatsapp[^0-9]{0,25}(\+?55\s*)?\(?(\d{2})\)?[\s.\-]*(\d{4,5})[\s.\-]*(\d{4})", re.I)

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) WiNS-Engenharia-Crawler/1.0"}


def normalize_br_phone(raw_digits: str) -> str:
    d = re.sub(r"\D", "", raw_digits or "")
    if d.startswith("55") and len(d) in (12, 13):
        d = d[2:]
    if len(d) in (10, 11) and len(set(d)) > 2:
        return d
    return ""


def crawl_domain(dom: str):
    wa_nums = set()
    tels = set()
    found_url = ""
    status = "ERR"

    for scheme in ("https", "http"):
        base_url = f"{scheme}://{dom}"
        try:
            r = requests.get(base_url, timeout=10, headers=HEADERS, allow_redirects=True)
            if r.status_code >= 400:
                status = f"HTTP_{r.status_code}"
                continue
            status = "OK"
            found_url = r.url
            pages_html = [(r.url, r.text)]

            soup = BeautifulSoup(r.text, "lxml")
            # Buscar tambem pagina de contato se existir
            contact_links = []
            for a in soup.find_all("a", href=True):
                href = a["href"].strip()
                txt = (a.get_text() or "").lower()
                if any(k in href.lower() or k in txt for k in ("contato", "fale-conosco", "contact", "atendimento")):
                    full = urljoin(r.url, href)
                    if dom in full and full not in [p[0] for p in pages_html] and full not in contact_links:
                        contact_links.append(full)
            for cl in contact_links[:2]:
                try:
                    rc = requests.get(cl, timeout=8, headers=HEADERS, allow_redirects=True)
                    if rc.status_code == 200:
                        pages_html.append((rc.url, rc.text))
                except Exception:
                    pass

            for p_url, html in pages_html:
                for m in WA_URL_RE.finditer(html):
                    n = normalize_br_phone(m.group(2))
                    if n:
                        wa_nums.add(n)
                for m in WA_TEXT_RE.finditer(re.sub(r"<[^>]+>", " ", html)):
                    n = normalize_br_phone(m.group(2) + m.group(3) + m.group(4))
                    if n:
                        wa_nums.add(n)
                for m in TEL_RE.finditer(html):
                    n = normalize_br_phone(m.group(2))
                    if n:
                        tels.add(n)
            break
        except Exception:
            continue

    return {
        "dominio": dom,
        "status_http": status,
        "url_final": found_url,
        "whatsapp_oficial": ";".join(sorted(wa_nums)),
        "telefones_site": ";".join(sorted(tels)),
        "tem_whatsapp": "t" if wa_nums else "f",
    }


con = duckdb.connect(MAIN_DB)
domains = [
    r[0] for r in con.execute("""
        SELECT DISTINCT dominio_corporativo
        FROM empresa_dominios_verificados
        WHERE dominio_corporativo IS NOT NULL
          AND dominio_corporativo NOT LIKE '%.gov.br'
          AND dominio_corporativo NOT LIKE '%.leg.br'
          AND dominio_corporativo NOT LIKE '%.jus.br'
        ORDER BY 1
    """).fetchall()
]
print(f"Varrendo {len(domains)} dominios corporativos privados...")

results = []
with ThreadPoolExecutor(max_workers=16) as ex:
    futs = {ex.submit(crawl_domain, d): d for d in domains}
    for i, fut in enumerate(as_completed(futs), 1):
        results.append(fut.result())
        if i % 50 == 0:
            wa_ok = sum(1 for x in results if x["tem_whatsapp"] == "t")
            print(f"  Progresso: {i}/{len(domains)} | Com WhatsApp oficial encontrado: {wa_ok}")

with open(OUT_CSV, "w", encoding="utf-8", newline="") as f:
    w = csv.DictWriter(f, fieldnames=["dominio", "status_http", "url_final", "whatsapp_oficial", "telefones_site", "tem_whatsapp"])
    w.writeheader()
    w.writerows(results)

csv_sql = OUT_CSV.replace("\\", "/")
con.execute(f"""
CREATE OR REPLACE TABLE empresa_whatsapp_oficial AS
SELECT
    dominio,
    status_http,
    NULLIF(url_final, '') AS url_final,
    NULLIF(whatsapp_oficial, '') AS whatsapp_oficial,
    NULLIF(telefones_site, '') AS telefones_site,
    (tem_whatsapp = 't') AS tem_whatsapp
FROM read_csv('{csv_sql}', header=true, all_varchar=true);
""")

# Medir quantas obras sao cobertas pelos WhatsApps encontrados
obras_wa = con.execute("""
SELECT
    COUNT(*) AS dominios_varridos,
    SUM(CASE WHEN status_http = 'OK' THEN 1 ELSE 0 END) AS sites_acessiveis,
    SUM(CASE WHEN tem_whatsapp THEN 1 ELSE 0 END) AS dominios_com_whatsapp,
    SUM(CASE WHEN telefones_site IS NOT NULL THEN 1 ELSE 0 END) AS dominios_com_tel
FROM empresa_whatsapp_oficial;
""").fetchdf()

obras_impacto = con.execute("""
SELECT
    COUNT(DISTINCT t.obra_id) AS obras_com_whatsapp_oficial
FROM todas_obras_consolidadas t
JOIN empresa_whatsapp_oficial w ON t.dominio_corporativo = w.dominio
WHERE w.tem_whatsapp = TRUE;
""").fetchone()[0]

con.execute("ANALYZE;")
con.execute("CHECKPOINT;")
con.close()

print("\n=== RESULTADO VARREDURA DE WHATSAPP NOS SITES OFICIAIS ===")
print(obras_wa.to_string(index=False))
print(f"Obras validadas cobertas com WhatsApp oficial do site: {obras_impacto}")
