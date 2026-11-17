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
    "acre": "AC", "alagoas": "AL", "amapá": "AP", "amazonas": "AM", "bahia": "BA",
    "ceará": "CE", "distrito federal": "DF", "espírito santo": "ES", "goiás": "GO",
    "maranhão": "MA", "mato grosso": "MT", "mato grosso do sul": "MS", "minas gerais": "MG",
    "estado do pará": "PA", "no pará": "PA", "paraíba": "PB", "paraná": "PR", "pernambuco": "PE", "piauí": "PI",
    "rio de janeiro": "RJ", "rio grande do norte": "RN", "rio grande do sul": "RS",
    "rondônia": "RO", "roraima": "RR", "santa catarina": "SC", "são paulo": "SP",
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
    if m and m.group(1) in set(UF_BY_NAME.values()):
        return m.group(1)
    tl = text[:1500].lower()
    for name, uf in UF_BY_NAME.items():
        if re.search(rf"\b{name}\b", tl):
            return uf
    return None


def classify_subsetor(text: str) -> str:
    t = strip_acc(text.lower())
    if re.search(r"\b(celulose|papel|kraft)\b", t):
        return "CELULOSE_PAPEL"
    if re.search(r"\b(alimentos?|bebidas?|frigorific[oa]s?|proteina|leite|laticinios?|nutricao animal|graos)\b", t):
        return "ALIMENTOS_BEBIDAS"
    if re.search(r"\b(farmaceutic[oa]s?|medicamentos?|quimic[oa]s?|petroquimic[oa]s?|biorrefinaria|refinaria|fertilizantes?|argamassas?)\b", t):
        return "QUIMICO_FARMACEUTICO"
    if re.search(r"\b(automotiv[oa]s?|veiculos?|maquinas?|eletrodomesticos?|linha branca|pneus?)\b", t):
        return "AUTOMOTIVO_MAQUINAS"
    if re.search(r"\b(etanol|bioenergia|biogas|biometano|biodiesel|sucroalcooleir[oa]|usina de cana|milho)\b", t):
        return "ETANOL_BIOENERGIA"
    if re.search(r"\b(mineracao|mineradora|siderurgia|siderurgica|aco|pelotizacao)\b", t):
        return "MINERACAO_SIDERURGIA"
    if re.search(r"\b(energia|solar|eolica|termeletrica|subestacao|saneamento|setor eletrico)\b", t):
        return "ENERGIA_SANEAMENTO"
    return "INDUSTRIA_GERAL"


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
        cat = classify_macro(title + " " + body[:500])
        sub = classify_subsetor(title)
        if sub == "INDUSTRIA_GERAL":
            sub = classify_subsetor(body[:350])
        rows.append((
            f"BVMI-{pid}",
            dt,
            title[:240],
            cat,
            sub,
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
            subsetor_bvmi VARCHAR,
            uf VARCHAR,
            capex_estimado DOUBLE,
            url_origem VARCHAR,
            resumo_escopo VARCHAR
        );
    """)
    if rows:
        con.executemany("INSERT INTO bvmi_radar_2026 VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)

    # Cruzamento preciso por subsetor tematico + UF + faixa de CAPEX (+-45%)
    con.execute("""
        CREATE OR REPLACE TABLE bvmi_match_obras_wins AS
        WITH wins_tag AS (
            SELECT
                obra_id, fonte, obra_empresa, obra_cnpj, obra_nome, obra_uf,
                capex_estimado, decisores_acionaveis,
                CASE
                    WHEN REGEXP_MATCHES(LOWER(CONCAT(obra_nome, ' ', obra_empresa)), '(celulose|papel|arauco|suzano|klabin|sylvamo|eldorado|melhoramentos)') THEN 'CELULOSE_PAPEL'
                    WHEN REGEXP_MATCHES(LOWER(CONCAT(obra_nome, ' ', obra_empresa)), '(etanol|biodiesel|biogas|biometano|bioenergia|sucro|acucar|milho|inpasa|raizen|cerradinho|vaccaro|biomil)') THEN 'ETANOL_BIOENERGIA'
                    WHEN REGEXP_MATCHES(LOWER(CONCAT(obra_nome, ' ', obra_empresa)), '(aliment|bebida|leite|laticin|frigorific|agroindustrial|cooperativa|nestle|agraria|castrolanda|ambev|heineken|coamo|trigo)') THEN 'ALIMENTOS_BEBIDAS'
                    WHEN REGEXP_MATCHES(LOWER(CONCAT(obra_nome, ' ', obra_empresa)), '(miner|siderurg|vale |gerdau|csn|itaminas)') THEN 'MINERACAO_SIDERURGIA'
                    WHEN REGEXP_MATCHES(LOWER(CONCAT(obra_nome, ' ', obra_empresa)), '(quimic|farmac|biorrefinaria|refinaria|petroquim|acelen|mapei|fertiliz)') THEN 'QUIMICO_FARMACEUTICO'
                    WHEN REGEXP_MATCHES(LOWER(CONCAT(obra_nome, ' ', obra_empresa)), '(automot|veicul|maquina|electrolux|marcopolo|volvo|stellantis)') THEN 'AUTOMOTIVO_MAQUINAS'
                    ELSE 'OUTRO'
                END AS wins_subsetor
            FROM todas_obras_consolidadas
            WHERE decisores_acionaveis > 0 AND capex_estimado IS NOT NULL
        )
        SELECT
            b.id_bvmi,
            b.data_publicacao,
            b.subsetor_bvmi,
            b.titulo AS bvmi_titulo,
            b.capex_estimado AS bvmi_capex,
            b.uf AS bvmi_uf,
            b.url_origem AS bvmi_url,
            o.obra_id AS wins_obra_id,
            o.fonte AS wins_fonte,
            o.obra_empresa AS wins_empresa,
            o.obra_cnpj AS wins_cnpj,
            o.obra_nome AS wins_obra_nome,
            o.obra_uf AS wins_uf,
            o.capex_estimado AS wins_capex,
            o.decisores_acionaveis AS wins_decisores_acionaveis
        FROM bvmi_radar_2026 b
        JOIN wins_tag o
          ON b.subsetor_bvmi = o.wins_subsetor
         AND b.subsetor_bvmi != 'INDUSTRIA_GERAL'
         AND (b.uf IS NULL OR b.uf = o.obra_uf)
         AND b.capex_estimado IS NOT NULL
         AND o.capex_estimado BETWEEN b.capex_estimado * 0.55 AND b.capex_estimado * 1.45
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
