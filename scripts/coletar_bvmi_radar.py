import csv
import os
import re
import unicodedata
from bs4 import BeautifulSoup
import duckdb
import requests

BASE_DIR = r"C:\Users\kbadmin\Documents\Projetos\01_Ecossistema_WiNS\Engenharia"
MAIN_DB = os.path.join(BASE_DIR, "Banco_Dados", "wins_engenharia.duckdb")
OUT_RADAR_CSV = os.path.join(BASE_DIR, "Arquivos_Tratados", "bvmi_radar_2026.csv")
OUT_MATCH_CSV = os.path.join(BASE_DIR, "Arquivos_Tratados", "bvmi_cross_match_wins.csv")

API_URL = "https://bvmi.com.br/wp-json/wp/v2/posts"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Accept": "application/json,text/html",
}

UF_BY_NAME = {
    "acre": "AC", "alagoas": "AL", "amapa": "AP", "amazonas": "AM", "bahia": "BA",
    "ceara": "CE", "distrito federal": "DF", "espirito santo": "ES", "goias": "GO",
    "maranhao": "MA", "mato grosso": "MT", "mato grosso do sul": "MS", "minas gerais": "MG",
    "para": "PA", "paraiba": "PB", "parana": "PR", "pernambuco": "PE", "piaui": "PI",
    "rio de janeiro": "RJ", "rio grande do norte": "RN", "rio grande do sul": "RS",
    "rondonia": "RO", "roraima": "RR", "santa catarina": "SC", "sao paulo": "SP",
    "sergipe": "SE", "tocantins": "TO",
}


def strip_acc(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s or "") if not unicodedata.combining(c))


def parse_capex(text: str) -> float | None:
    m = re.search(r"R\$\s*([\d.,]+)\s*(bilh[aã]o|bilh[oõ]es|milh[aã]o|milh[oõ]es|mil)\b", text, re.I)
    if not m:
        return None
    try:
        val = float(m.group(1).replace(".", "").replace(",", "."))
    except ValueError:
        return None
    u = strip_acc(m.group(2).lower())
    if u.startswith("bilh"):
        return val * 1_000_000_000.0
    if u.startswith("milh"):
        return val * 1_000_000.0
    if u == "mil":
        return val * 1_000.0
    return val


def detect_uf(text: str) -> str | None:
    m = re.search(r"\(([A-Z]{2})\)", text[:1500])
    if m and m.group(1) in UF_BY_NAME.values():
        return m.group(1)
    tn = strip_acc(text[:1500].lower())
    for name, uf in UF_BY_NAME.items():
        if re.search(rf"\b{name}\b", tn):
            return uf
    return None


def classify_macro(text: str) -> str:
    t = strip_acc(text[:1000].lower())
    if any(k in t for k in ("celulose", "papel", "fabrica", "industrial", "automotiva", "bebidas", "alimentos", "quimic", "etanol", "usina", "mineracao", "siderurgia", "retrofit")):
        return "INDUSTRIA_E_FABRICAS"
    if any(k in t for k in ("energia", "solar", "eolica", "termel", "saneamento", "subestacao")):
        return "ENERGIA_E_SANEAMENTO"
    if any(k in t for k in ("rodovia", "porto", "ferrovia", "ponte", "infraestrutura", "aeroporto")):
        return "INFRAESTRUTURA_E_OBRAS_CIVIS"
    return "INDUSTRIA_E_FABRICAS"


def fetch_bvmi_2026() -> list[dict]:
    posts = []
    page = 1
    while True:
        r = requests.get(
            API_URL,
            params={"per_page": 100, "page": page, "after": "2026-01-01T00:00:00"},
            headers=HEADERS,
            timeout=25,
        )
        if r.status_code != 200:
            break
        batch = r.json()
        if not isinstance(batch, list) or not batch:
            break
        posts.extend(batch)
        if page >= int(r.headers.get("X-WP-TotalPages", "1")):
            break
        page += 1
    return posts


def main() -> None:
    posts = fetch_bvmi_2026()
    print(f"Posts BVMI 2026 coletados: {len(posts)}")

    rows = []
    for p in posts:
        pid = p.get("id")
        link = (p.get("link") or "").strip()
        dt = (p.get("date") or "")[:10]
        title = BeautifulSoup(p.get("title", {}).get("rendered", ""), "lxml").get_text(" ", strip=True)
        body = BeautifulSoup(p.get("content", {}).get("rendered", ""), "lxml").get_text(" ", strip=True)
        capex = parse_capex(title + " " + body[:1500])
        uf = detect_uf(title + " " + body[:1500])
        cat = classify_macro(title + " " + body[:1000])
        rows.append((
            f"BVMI-{pid}",
            dt,
            title[:240],
            cat,
            uf,
            capex,
            link,
            body[:450],
        ))

    con = duckdb.connect(MAIN_DB)
    con.execute("""
        CREATE OR REPLACE TABLE bvmi_radar_2026 (
            id_bvmi VARCHAR,
            data_publicacao VARCHAR,
            titulo VARCHAR,
            categoria_macro VARCHAR,
            uf VARCHAR,
            capex_estimado DOUBLE,
            url_origem VARCHAR,
            resumo_escopo VARCHAR
        );
    """)
    if rows:
        con.executemany("INSERT INTO bvmi_radar_2026 VALUES (?, ?, ?, ?, ?, ?, ?, ?)", rows)

    # Cruzamento por UF + categoria_macro + faixa de CAPEX (+-40%) com obras nominais existentes
    con.execute("""
        CREATE OR REPLACE TABLE bvmi_match_obras_wins AS
        SELECT
            b.id_bvmi,
            b.data_publicacao,
            b.titulo AS bvmi_titulo,
            b.capex_estimado AS bvmi_capex,
            b.uf AS bvmi_uf,
            b.url_origem AS bvmi_url,
            o.obra_id AS wins_obra_id,
            o.fonte AS wins_fonte,
            o.obra_empresa AS wins_empresa,
            o.obra_cnpj AS wins_cnpj,
            o.obra_nome AS wins_obra_nome,
            o.capex_estimado AS wins_capex,
            o.decisores_acionaveis AS wins_decisores_acionaveis
        FROM bvmi_radar_2026 b
        JOIN todas_obras_consolidadas o
          ON b.categoria_macro = o.categoria_macro
         AND (b.uf IS NULL OR b.uf = o.obra_uf)
         AND b.capex_estimado IS NOT NULL
         AND o.capex_estimado IS NOT NULL
         AND o.capex_estimado BETWEEN b.capex_estimado * 0.6 AND b.capex_estimado * 1.4
        WHERE o.decisores_acionaveis > 0
        ORDER BY b.capex_estimado DESC, o.decisores_acionaveis DESC;
    """)

    tot_radar = con.execute("SELECT COUNT(*) FROM bvmi_radar_2026").fetchone()[0]
    tot_match = con.execute("SELECT COUNT(DISTINCT id_bvmi), COUNT(*) FROM bvmi_match_obras_wins").fetchone()

    con.execute("SELECT * FROM bvmi_radar_2026 ORDER BY data_publicacao DESC, capex_estimado DESC NULLS LAST").fetchdf().to_csv(
        OUT_RADAR_CSV, index=False, encoding="utf-8-sig"
    )
    con.execute("SELECT * FROM bvmi_match_obras_wins").fetchdf().to_csv(
        OUT_MATCH_CSV, index=False, encoding="utf-8-sig"
    )
    con.execute("ANALYZE;")
    con.execute("CHECKPOINT;")
    con.close()

    print(f"bvmi_radar_2026 salvo: {tot_radar} projetos")
    print(f"bvmi_match_obras_wins: {tot_match[0]} alertas BVMI cruzados com {tot_match[1]} pares de obras nominais acionaveis no WiNS")


if __name__ == "__main__":
    main()
