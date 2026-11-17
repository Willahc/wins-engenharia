import csv
import os
import re
import subprocess
import unicodedata
from bs4 import BeautifulSoup
import duckdb
import requests

BASE_DIR = r"C:\Users\kbadmin\Documents\Projetos\01_Ecossistema_WiNS\Engenharia"
MAIN_DB = os.path.join(BASE_DIR, "Banco_Dados", "wins_engenharia.duckdb")
SUB_DB = os.path.join(BASE_DIR, "Banco_Dados", "obras_civil_industrial_2026_2027_100k.duckdb")
OUT_CONVISAO_CSV = os.path.join(BASE_DIR, "Arquivos_Tratados", "obras_convisao_2026.csv")
OUT_DECISORES_CSV = os.path.join(BASE_DIR, "Arquivos_Tratados", "obras_novas_com_decisores.csv").replace("\\", "/")

API_URL = "https://convisao.com/wp-json/wp/v2/posts"
CATS = "17182009,37322648,77726"  # em-execucao, fase-inicial, industria
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) WiNS-Engenharia/1.0"}

VALID_UFS = {
    "AC", "AL", "AP", "AM", "BA", "CE", "DF", "ES", "GO", "MA", "MT", "MS",
    "MG", "PA", "PB", "PR", "PE", "PI", "RJ", "RN", "RS", "RO", "RR", "SC", "SP", "SE", "TO"
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

NEG_RE = re.compile(r"\b(software|licenca\s+de\s+uso|vigilancia\s+armada|limpeza\s+urbana|merenda\s+escolar|medicamentos|chips\s+de\s+ia)\b", re.I)


def strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s or "") if not unicodedata.combining(c))


def norm_company(s: str) -> str:
    s = strip_accents(s or "").upper()
    s = re.sub(r"[^A-Z0-9\s]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def parse_capex(text: str) -> tuple[float | None, str]:
    # Ex: R$ 480 milhões / R$480 milhões / R$ 1,2 bilhão / R$ 850 mil
    m = re.search(r"R\$\s*([\d.,]+)\s*(bilh[aã]o|bilh[oõ]es|milh[aã]o|milh[oõ]es|mil)\b", text, re.I)
    if not m:
        return None, "ESTIMADO_SEM_VALOR"
    num_raw = m.group(1).replace(".", "").replace(",", ".")
    try:
        val = float(num_raw)
    except ValueError:
        return None, "ESTIMADO_SEM_VALOR"
    unit = strip_accents(m.group(2).lower())
    if unit.startswith("bilh"):
        return val * 1_000_000_000.0, "OFICIAL_PORTAL_CONVISAO"
    if unit.startswith("milh"):
        return val * 1_000_000.0, "OFICIAL_PORTAL_CONVISAO"
    if unit == "mil":
        return val * 1_000.0, "OFICIAL_PORTAL_CONVISAO"
    return val, "OFICIAL_PORTAL_CONVISAO"


def parse_location(title: str, text: str) -> tuple[str, str]:
    # Padrao comum ConVisao: "Castro – PR |" ou "Jequié – BA |"
    m = re.match(r"^\s*([A-ZÀ-ÿa-z\s'.\-]{2,45}?)\s*[–\-]\s*([A-Z]{2})\s*\|", text)
    if m and m.group(2) in VALID_UFS:
        return m.group(1).strip(), m.group(2)
    m2 = re.search(r"\b([A-ZÀ-ÿ][A-ZÀ-ÿa-z\s'.\-]{2,35})\s*\(([A-Z]{2})\)", text)
    if m2 and m2.group(2) in VALID_UFS:
        return m2.group(1).strip(), m2.group(2)
    t_norm = strip_accents((title + " " + text[:400]).lower())
    for name, uf in UF_BY_NAME.items():
        if re.search(rf"\b{name}\b", t_norm):
            return "", uf
    return "", ""


def extract_company_candidates(title: str, text: str) -> list[str]:
    cands = []
    # Padroes explicitos: "Construtora X", "X Construtora", "X Engenharia", "X Cooperativa", "X S.A.", "X Ltda"
    patterns = [
        r"\b([A-ZÀ-ÿ][A-Za-zÀ-ÿ0-9&.\-]{1,35}(?:\s+[A-ZÀ-ÿ0-9&.\-][A-Za-zÀ-ÿ0-9&.\-]{0,30}){0,5}\s+(?:Construtora|Engenharia|Cooperativa\s+Agroindustrial|Cooperativa|Energia|Bioenergia|Ind[úu]stria|S\.?A\.?|Ltda\.?))\b",
        r"\b((?:Construtora|Grupo|Usina|Cooperativa)\s+[A-ZÀ-ÿ][A-Za-zÀ-ÿ0-9&.\-]+(?:\s+[A-ZÀ-ÿ][A-Za-zÀ-ÿ0-9&.\-]+){0,3})\b",
        r"(?:responsabilidade da|adjudicada [àa]|assinatura da|vence concorr[êe]ncia[^,]*,|investimentos d[ao]|expans[ãa]o d[ao]|unidade d[ao]|planta d[ao])\s+([A-ZÀ-ÿ][A-Za-zÀ-ÿ0-9&.\-]+(?:\s+[A-ZÀ-ÿ][A-Za-zÀ-ÿ0-9&.\-]+){0,4})",
    ]
    combined = f"{title}. {text[:900]}"
    for pat in patterns:
        for m in re.finditer(pat, combined):
            cand = re.sub(r"\s+", " ", m.group(1)).strip(" .,;:|")
            if len(cand) >= 4 and not re.search(r"\b(Sistema de Informa|ConVis|Brasil|Estado|Munic[íi]pio)\b", cand, re.I):
                if cand not in cands:
                    cands.append(cand)
    return cands[:5]


def classify_macro(title: str, text: str) -> str:
    t = strip_accents((title + " " + text[:500]).lower())
    if any(k in t for k in ("usina", "energia", "solar", "eolica", "termel", "saneamento", "agua", "esgoto", "subestacao", "transmissao")):
        return "ENERGIA_E_SANEAMENTO"
    if any(k in t for k in ("industrial", "fabrica", "planta", "bioenergia", "etanol", "celulose", "cooperativa", "silos", "armazenagem", "logistica", "galpao")):
        return "INDUSTRIA_E_FABRICAS"
    if any(k in t for k in ("ponte", "rodovia", "aeroporto", "porto", "ferrovia", "viaduto", "infraestrutura")):
        return "INFRAESTRUTURA_E_OBRAS_CIVIS"
    return "EDIFICACOES_E_COMERCIAL"


def fetch_convisao_2026() -> list[dict]:
    all_posts = []
    page = 1
    while True:
        params = {
            "per_page": 100,
            "page": page,
            "categories": CATS,
            "after": "2026-01-01T00:00:00",
        }
        r = requests.get(API_URL, params=params, headers=HEADERS, timeout=20)
        if r.status_code != 200:
            break
        batch = r.json()
        if not isinstance(batch, list) or not batch:
            break
        all_posts.extend(batch)
        total_pages = int(r.headers.get("X-WP-TotalPages", "1"))
        if page >= total_pages:
            break
        page += 1
    return all_posts


def main() -> None:
    posts = fetch_convisao_2026()
    print(f"Posts 2026 coletados na API ConVisao: {len(posts)}")

    con = duckdb.connect(MAIN_DB)

    # Preparar lookup rapido em fornecedores / decisores para empresas com >= 1 decisor ou razao social ativa
    parsed_records = []
    for p in posts:
        pid = p.get("id")
        link = (p.get("link") or "").strip()
        if "/em-foco/" in link:
            continue
        title = BeautifulSoup(p.get("title", {}).get("rendered", ""), "lxml").get_text(" ", strip=True)
        body = BeautifulSoup(p.get("content", {}).get("rendered", ""), "lxml").get_text(" ", strip=True)
        if not title or NEG_RE.search(title + " " + body[:400]):
            continue

        capex, cap_tipo = parse_capex(title + " " + body[:1000])
        if capex is not None and capex < 100_000:
            continue

        mun, uf = parse_location(title, body)
        cands = extract_company_candidates(title, body)
        emp_raw = cands[0] if cands else ""
        cat = classify_macro(title, body)
        dt_pub = (p.get("date") or "")[:10]
        situacao = "Em Execução (ConVisão)" if "/em-execucao/" in link else "Fase Inicial / Planejamento (ConVisão)"

        # Tentar resolver CNPJ em fornecedores / dim_decisores_empresa
        cnpj_match = None
        razao_match = emp_raw or title[:80]
        for cand in cands:
            cn = norm_company(cand)
            if len(cn) < 5:
                continue
            hit = con.execute("""
                SELECT obra_cnpj, obra_empresa
                FROM dim_decisores_empresa
                WHERE obra_empresa_norm = ?
                LIMIT 1
            """, [cn]).fetchone()
            if not hit and len(cn) >= 7:
                hit = con.execute("""
                    SELECT obra_cnpj, obra_empresa
                    FROM dim_decisores_empresa
                    WHERE obra_empresa_norm LIKE ?
                    LIMIT 1
                """, [f"{cn}%"]).fetchone()
            if not hit:
                hit = con.execute("""
                    SELECT cnpj, razao_social
                    FROM fornecedores
                    WHERE situacao = '02'
                      AND UPPER(razao_social) = ?
                    LIMIT 1
                """, [cn]).fetchone()
            if hit:
                cnpj_match, razao_match = hit[0], hit[1]
                break

        id_ext = f"CONVISAO-{pid}"
        parsed_records.append({
            "id_externo": id_ext,
            "fonte": "convisao_cnc",
            "obra_nome": title[:220],
            "obra_empresa": razao_match[:180],
            "obra_empresa_norm": norm_company(razao_match),
            "obra_cnpj": cnpj_match,
            "obra_cnpj_raiz": cnpj_match[:8] if cnpj_match else None,
            "categoria_macro": cat,
            "obra_uf": uf or None,
            "obra_municipio": mun or None,
            "capex_estimado": capex,
            "capex_tipo": cap_tipo,
            "data_inicio_prevista": dt_pub or None,
            "data_fim_prevista": None,
            "situacao": situacao,
            "url_origem": link,
        })

    # Exportar CSV bruto da coleta ConVisao
    with open(OUT_CONVISAO_CSV, "w", newline="", encoding="utf-8-sig") as f:
        if parsed_records:
            w = csv.DictWriter(f, fieldnames=list(parsed_records[0].keys()))
            w.writeheader()
            w.writerows(parsed_records)

    # Inserir novas obras em obras_oficiais_ativas sem duplicar id_externo
    existing_ids = set(r[0] for r in con.execute("SELECT id_externo FROM obras_oficiais_ativas").fetchall())
    inserted_obras = 0
    matched_cnpj = 0
    for rec in parsed_records:
        if rec["obra_cnpj"]:
            matched_cnpj += 1
        if rec["id_externo"] in existing_ids:
            continue
        con.execute("""
            INSERT INTO obras_oficiais_ativas (
                id_externo, fonte, obra_nome, obra_empresa, obra_empresa_norm,
                obra_cnpj, obra_cnpj_raiz, categoria_macro, obra_uf, obra_municipio,
                capex_estimado, capex_tipo, data_inicio_prevista, data_fim_prevista,
                situacao, url_origem, tem_match_fornecedor, cnpj_origem_resolucao
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, [
            rec["id_externo"], rec["fonte"], rec["obra_nome"], rec["obra_empresa"], rec["obra_empresa_norm"],
            rec["obra_cnpj"], rec["obra_cnpj_raiz"], rec["categoria_macro"], rec["obra_uf"], rec["obra_municipio"],
            rec["capex_estimado"], rec["capex_tipo"], rec["data_inicio_prevista"], rec["data_fim_prevista"],
            rec["situacao"], rec["url_origem"], bool(rec["obra_cnpj"]), "FORNECEDORES_MATCH" if rec["obra_cnpj"] else None
        ])
        inserted_obras += 1

    # Vincular decisores existentes por CNPJ exato para as novas obras ConVisao que ainda nao estao em validacao_decisores_obras_novas
    con.execute("""
        INSERT INTO validacao_decisores_obras_novas
        SELECT
            o.id_externo, o.fonte, o.obra_nome, o.obra_empresa, o.obra_cnpj, o.categoria_macro,
            o.obra_uf, o.capex_estimado, o.capex_tipo, o.url_origem,
            '1_CNPJ_EXATO' AS tipo_match,
            d.decisor_id, d.nome, d.cargo, d.email, d.telefone, d.linkedin_url,
            'CONVISAO_LINK_CNPJ' AS qualidade_lead,
            d.is_contato_acionavel,
            CASE
                WHEN LOWER(COALESCE(d.cargo, '')) SIMILAR TO '%(comprador|supriment|procurement|aquisi|cotac)%' THEN '1_COMPRADOR_SUPRIMENTOS'
                WHEN LOWER(COALESCE(d.cargo, '')) SIMILAR TO '%(engenh|obra|projet|implanta|manutenc|epc|planej)%' THEN '2_ENGENHARIA_OBRAS_CAPEX'
                ELSE '3_DIRETORIA_EXECUTIVA'
            END AS perfil_decisor
        FROM obras_oficiais_ativas o
        JOIN dim_decisores_empresa d ON o.obra_cnpj = d.obra_cnpj
        WHERE o.fonte = 'convisao_cnc'
          AND o.id_externo NOT IN (SELECT DISTINCT id_externo FROM validacao_decisores_obras_novas);
    """)

    novas_com_dec = con.execute("SELECT COUNT(DISTINCT id_externo) FROM validacao_decisores_obras_novas WHERE fonte = 'convisao_cnc'").fetchone()[0]
    total_ativas = con.execute("SELECT COUNT(DISTINCT id_externo) FROM obras_oficiais_ativas").fetchone()[0]

    con.execute(f"COPY validacao_decisores_obras_novas TO '{OUT_DECISORES_CSV}' (HEADER, DELIMITER ',');")
    con.execute("ANALYZE;")
    con.execute("CHECKPOINT;")
    con.close()

    sub = duckdb.connect(SUB_DB)
    main_sql = MAIN_DB.replace("\\", "/")
    sub.execute(f"ATTACH '{main_sql}' AS main_db (READ_ONLY);")
    sub.execute("CREATE OR REPLACE TABLE decisores_obras_novas AS SELECT * FROM main_db.validacao_decisores_obras_novas;")
    sub.execute("CREATE OR REPLACE TABLE obras_ativas AS SELECT * FROM main_db.obras_oficiais_ativas;")
    sub.execute("DETACH main_db;")
    sub.execute("CHECKPOINT;")
    sub.close()

    print(f"ConVisao 2026 validas: {len(parsed_records)} | Inseridas em obras_oficiais_ativas: {inserted_obras} | Com CNPJ resolvido: {matched_cnpj}")
    print(f"Obras ConVisao ja vinculadas a decisores: {novas_com_dec} | Total obras_oficiais_ativas: {total_ativas:,}")

    subprocess.run(["python", os.path.join(BASE_DIR, "scripts", "gerar_dashboard_html.py")], check=True)
    subprocess.run(["python", os.path.join(BASE_DIR, "scripts", "exportar_planilha_prospeccao.py")], check=True)


if __name__ == "__main__":
    main()
