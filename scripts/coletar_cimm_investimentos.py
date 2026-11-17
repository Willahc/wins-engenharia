import csv
import os
import re
import subprocess
import unicodedata
from concurrent.futures import ThreadPoolExecutor, as_completed
from bs4 import BeautifulSoup
import duckdb
from rapidfuzz import fuzz
import requests

BASE_DIR = r"C:\Users\kbadmin\Documents\Projetos\01_Ecossistema_WiNS\Engenharia"
MAIN_DB = os.path.join(BASE_DIR, "Banco_Dados", "wins_engenharia.duckdb")
OUT_CIMM_CSV = os.path.join(BASE_DIR, "Arquivos_Tratados", "obras_cimm_2026.csv")
OUT_DECISORES_CSV = os.path.join(BASE_DIR, "Arquivos_Tratados", "obras_novas_com_decisores.csv").replace("\\", "/")

BASE_URL = "https://www.cimm.com.br"
TAG_URL = "https://www.cimm.com.br/portal/tag/investimentos"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
}

UF_BY_NAME = {
    "acre": "AC", "alagoas": "AL", "amapá": "AP", "amazonas": "AM", "bahia": "BA",
    "ceará": "CE", "distrito federal": "DF", "espírito santo": "ES", "goiás": "GO",
    "maranhão": "MA", "mato grosso do sul": "MS", "mato grosso": "MT", "minas gerais": "MG",
    "estado do pará": "PA", "no pará": "PA", "paraíba": "PB", "paraná": "PR", "pernambuco": "PE", "piauí": "PI",
    "rio de janeiro": "RJ", "rio grande do norte": "RN", "rio grande do sul": "RS",
    "rondônia": "RO", "roraima": "RR", "santa catarina": "SC", "são paulo": "SP",
    "interior de sp": "SP", "sergipe": "SE", "tocantins": "TO",
}
VALID_UFS = set(UF_BY_NAME.values())

LEGAL_SUFFIX_RE = re.compile(r"\b(ltda|s\.?a\.?|s/a|eireli|me|epp|do\s+brasil|brasil)\b", re.I)
EVENT_NOISE_RE = re.compile(r"\b(fenatran|feira|evento|congresso|podcast|webinar|ranking)\b", re.I)


def strip_acc(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s or "") if not unicodedata.combining(c))


def clean_core(s: str) -> str:
    s = strip_acc(s or "").upper()
    s = LEGAL_SUFFIX_RE.sub(" ", s)
    s = re.sub(r"[^A-Z0-9\s]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def parse_capex(text: str) -> tuple[float | None, str]:
    m = re.search(r"(R\$|US\$)\s*([\d.,]+)\s*(bilh[aã]o|bilh[oõ]es|milh[aã]o|milh[oõ]es|mil)\b", text, re.I)
    if not m:
        return None, "ESTIMADO_SEM_VALOR"
    cur = m.group(1).upper()
    try:
        val = float(m.group(2).replace(".", "").replace(",", "."))
    except ValueError:
        return None, "ESTIMADO_SEM_VALOR"
    u = strip_acc(m.group(3).lower())
    mult = 1_000_000_000.0 if u.startswith("bilh") else (1_000_000.0 if u.startswith("milh") else 1_000.0)
    total = val * mult
    if cur == "US$":
        return total * 5.5, "CONVERSAO_USD_CIMM"
    return total, "OFICIAL_PORTAL_CIMM"


def detect_uf(text: str) -> str | None:
    m = re.search(r"\b(?:em|no|na|para)\s+([A-Z]{2})\b", text)
    if m and m.group(1) in VALID_UFS:
        return m.group(1)
    m2 = re.search(r"\(([A-Z]{2})\)", text)
    if m2 and m2.group(1) in VALID_UFS:
        return m2.group(1)
    tl = text.lower()
    for name, uf in UF_BY_NAME.items():
        if re.search(rf"\b{name}\b", tl):
            return uf
    return None


def extract_company_from_title(title: str) -> str:
    m = re.match(
        r"^(.{3,55}?)\s+(?:anuncia|investe|planeja|prev[eê]|amplia|inaugura|constr[oó]i|recebe|aporta|destina|abre|firma|fecha|vai investir)\b",
        title,
        re.I,
    )
    if m:
        cand = m.group(1).strip(" :-–")
        if not re.match(r"^(nova|novo|f[áa]brica|ind[úu]stria|multinacional|metal[úu]rgica|grupo|mais de)\b", cand, re.I):
            return cand
    return ""


def fetch_article(href: str) -> dict | None:
    url = BASE_URL + href if href.startswith("/") else href
    try:
        r = requests.get(url, timeout=20, headers=HEADERS)
        if r.status_code != 200:
            return None
        s = BeautifulSoup(r.text, "lxml")
        h1 = s.select_one("h1")
        tm = s.select_one("time")
        art = s.select_one("article")
        title = h1.get_text(" ", strip=True) if h1 else ""
        dt_raw = tm.get_text(" ", strip=True) if tm else ""
        body = art.get_text(" ", strip=True) if art else ""
        if not title:
            return None
        # Data formato dd/mm/yyyy
        dt_iso = None
        m_dt = re.search(r"(\d{2})/(\d{2})/(\d{4})", dt_raw)
        if m_dt:
            dt_iso = f"{m_dt.group(3)}-{m_dt.group(2)}-{m_dt.group(1)}"
        m_id = re.search(r"/exibir_noticia/(\d+)", url)
        nid = m_id.group(1) if m_id else str(abs(hash(url)))
        return {"nid": nid, "url": url, "title": title, "dt_iso": dt_iso, "body": body}
    except Exception:
        return None


def main() -> None:
    links = []
    seen_hrefs = set()
    for page in range(1, 7):
        url = TAG_URL if page == 1 else f"{TAG_URL}?pagina={page}"
        try:
            r = requests.get(url, timeout=25, headers=HEADERS)
            if r.status_code != 200:
                break
            soup = BeautifulSoup(r.text, "lxml")
            new_on_page = 0
            for a in soup.select('a[href*="exibir_noticia"]'):
                href = a.get("href", "").strip()
                txt = a.get_text(" ", strip=True)
                if href and len(txt) > 15 and href not in seen_hrefs:
                    seen_hrefs.add(href)
                    links.append(href)
                    new_on_page += 1
            if new_on_page == 0:
                break
        except Exception:
            break

    print(f"Links coletados na tag investimentos CIMM: {len(links)}")

    articles = []
    with ThreadPoolExecutor(max_workers=5) as ex:
        futs = [ex.submit(fetch_article, h) for h in links]
        for fut in as_completed(futs):
            res = fut.result()
            if res:
                articles.append(res)

    # Filtrar apenas 2026+ e nao-eventos
    valid_2026 = [
        a for a in articles
        if (not a["dt_iso"] or a["dt_iso"] >= "2026-01-01")
        and not EVENT_NOISE_RE.search(a["title"])
    ]
    print(f"Artigos 2026 validos (sem eventos/feiras): {len(valid_2026)}")

    con = duckdb.connect(MAIN_DB)
    dim_emps = con.execute("""
        SELECT DISTINCT obra_cnpj, obra_empresa
        FROM dim_decisores_empresa
        WHERE obra_cnpj IS NOT NULL AND obra_empresa IS NOT NULL
    """).fetchall()
    dim_index = [(c, e, clean_core(e)) for c, e in dim_emps if len(clean_core(e)) >= 4]

    existing_ids = set(r[0] for r in con.execute("SELECT id_externo FROM obras_oficiais_ativas").fetchall())

    csv_rows = []
    inserted = 0
    resolved_cnpj = 0

    for a in valid_2026:
        id_ext = f"CIMM-{a['nid']}"
        capex, cap_tipo = parse_capex(a["title"] + " " + a["body"][:800])
        if capex is not None and capex < 100_000:
            continue
        uf = detect_uf(a["title"] + " " + a["body"][:800])
        emp_raw = extract_company_from_title(a["title"]) or a["title"][:80]

        best_cnpj, best_emp, best_sc = None, emp_raw, 0.0
        core = clean_core(emp_raw)
        if len(core) >= 4 and emp_raw != a["title"][:80]:
            for cnpj, emp_orig, d_core in dim_index:
                sc = fuzz.token_sort_ratio(core, d_core)
                if sc > best_sc:
                    best_cnpj, best_emp, best_sc = cnpj, emp_orig, sc
            if best_sc < 86:
                tok1 = core.split()[0]
                if len(tok1) >= 4:
                    uf_clause = "AND uf = ?" if uf else ""
                    params = [f"{tok1}%"] + ([uf] if uf else [])
                    cands = con.execute(f"""
                        SELECT cnpj, razao_social
                        FROM fornecedores
                        WHERE situacao = '02' AND UPPER(razao_social) LIKE ? {uf_clause}
                        ORDER BY (SUBSTR(cnpj, 9, 4) = '0001') DESC, porte_inferido DESC
                        LIMIT 40
                    """, params).fetchall()
                    best_cnpj, best_emp, best_sc = None, emp_raw, 0.0
                    for cnpj, rz in cands:
                        sc = fuzz.token_sort_ratio(core, clean_core(rz))
                        if sc > best_sc:
                            best_cnpj, best_emp, best_sc = cnpj, rz, sc
            if best_sc < 86:
                best_cnpj, best_emp = None, emp_raw

        if best_cnpj:
            resolved_cnpj += 1

        rec = {
            "id_externo": id_ext,
            "fonte": "cimm_investimentos",
            "obra_nome": a["title"][:220],
            "obra_empresa": best_emp[:180],
            "obra_cnpj": best_cnpj,
            "obra_uf": uf,
            "capex_estimado": capex,
            "capex_tipo": cap_tipo,
            "data_inicio_prevista": a["dt_iso"],
            "url_origem": a["url"],
        }
        csv_rows.append(rec)

        if id_ext not in existing_ids:
            con.execute("""
                INSERT INTO obras_oficiais_ativas (
                    id_externo, fonte, obra_nome, obra_empresa, obra_empresa_norm,
                    obra_cnpj, obra_cnpj_raiz, categoria_macro, obra_uf, obra_municipio,
                    capex_estimado, capex_tipo, data_inicio_prevista, data_fim_prevista,
                    situacao, url_origem, tem_match_fornecedor, cnpj_origem_resolucao
                ) VALUES (?, 'cimm_investimentos', ?, ?, ?, ?, ?, 'INDUSTRIA_E_FABRICAS', ?, NULL, ?, ?, ?, NULL, 'Investimento Industrial Anunciado (CIMM)', ?, ?, ?)
            """, [
                id_ext, rec["obra_nome"], rec["obra_empresa"], clean_core(rec["obra_empresa"]),
                best_cnpj, best_cnpj[:8] if best_cnpj else None, uf,
                capex, cap_tipo, a["dt_iso"], a["url"],
                bool(best_cnpj), "RAPIDFUZZ_FORNECEDORES" if best_cnpj else None,
            ])
            inserted += 1

    # Vincular decisores existentes por CNPJ raiz
    con.execute("""
        INSERT INTO validacao_decisores_obras_novas
        SELECT
            o.id_externo, o.fonte, o.obra_nome, o.obra_empresa, o.obra_cnpj, o.categoria_macro,
            o.obra_uf, o.capex_estimado, o.capex_tipo, o.url_origem,
            CASE WHEN o.obra_cnpj = d.obra_cnpj THEN '1_CNPJ_EXATO' ELSE '2_CNPJ_RAIZ' END AS tipo_match,
            d.decisor_id, d.nome, d.cargo, d.email, d.telefone, d.linkedin_url,
            'CIMM_RAPIDFUZZ' AS qualidade_lead,
            d.is_contato_acionavel,
            CASE
                WHEN LOWER(COALESCE(d.cargo, '')) SIMILAR TO '%(comprador|supriment|procurement|aquisi|cotac)%' THEN '1_COMPRADOR_SUPRIMENTOS'
                WHEN LOWER(COALESCE(d.cargo, '')) SIMILAR TO '%(engenh|obra|projet|implanta|manutenc|epc|planej)%' THEN '2_ENGENHARIA_OBRAS_CAPEX'
                ELSE '3_DIRETORIA_EXECUTIVA'
            END AS perfil_decisor
        FROM obras_oficiais_ativas o
        JOIN dim_decisores_empresa d ON o.obra_cnpj_raiz = d.obra_cnpj_raiz
        WHERE o.fonte = 'cimm_investimentos'
          AND o.obra_cnpj IS NOT NULL
          AND o.id_externo NOT IN (SELECT DISTINCT id_externo FROM validacao_decisores_obras_novas);
    """)

    with open(OUT_CIMM_CSV, "w", newline="", encoding="utf-8-sig") as f:
        if csv_rows:
            w = csv.DictWriter(f, fieldnames=list(csv_rows[0].keys()))
            w.writeheader()
            w.writerows(csv_rows)

    con.execute(f"COPY validacao_decisores_obras_novas TO '{OUT_DECISORES_CSV}' (HEADER, DELIMITER ',');")
    con.execute("ANALYZE;")
    con.execute("CHECKPOINT;")
    con.close()

    print(f"CIMM 2026 inseridas: {inserted} | Com CNPJ resolvido: {resolved_cnpj}")
    subprocess.run(["python", os.path.join(BASE_DIR, "scripts", "sincronizar_todas_obras_consolidadas.py")], check=True)


if __name__ == "__main__":
    main()
