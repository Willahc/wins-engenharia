import os
import re
import time
import csv
import requests
import duckdb

BASE_DIR = r"C:\Users\kbadmin\Documents\Projetos\01_Ecossistema_WiNS\Engenharia"
MAIN_DB = os.path.join(BASE_DIR, "Banco_Dados", "wins_engenharia.duckdb")
SUB_DB = os.path.join(BASE_DIR, "Banco_Dados", "obras_civil_industrial_2026_2027_100k.duckdb")
OUT_CONSOLIDADO_CSV = os.path.join(BASE_DIR, "Arquivos_Tratados", "obras_consolidadas_sem_duplicidade.csv")

OBRA_KEYWORDS = re.compile(
    r"\b(obra|obras|constru[cç][aã]o|reforma|amplia[cç][aã]o|pavimenta[cç][aã]o|"
    r"drenagem|saneamento|esgoto|adutora|ponte|viaduto|rodovia|ferrovia|porto|"
    r"subesta[cç][aã]o|usina|f[aá]brica|galp[aã]o|planta\s+industrial|terraplanagem|"
    r"edifica[cç][aã]o|engenharia|infraestrutura|hospital|escola|creche)\b",
    re.I
)
INDUSTRIAL_KEYWORDS = re.compile(
    r"\b(industrial|f[aá]brica|usina|planta|sider[uú]rg|petroqu[ií]m|minera[cç][aã]o|"
    r"subesta[cç][aã]o|caldeira|refinaria|galp[aã]o\s+industrial|data\s*center)\b",
    re.I
)
INACTIVE_STATUS = {"revogada", "anulada", "fracassada", "deserta", "suspensa", "cancelada", "encerrada"}


def classify_obra(text: str) -> str:
    return "INDUSTRIAL" if INDUSTRIAL_KEYWORDS.search(text or "") else "CIVIL"


def get_with_retry(url, params, headers, timeout=30, max_retries=4):
    for attempt in range(max_retries):
        try:
            resp = requests.get(url, params=params, headers=headers, timeout=timeout)
            if resp.status_code == 429:
                wait = 2 ** (attempt + 1)
                print(f"  [429] Rate limit em {url}, aguardando {wait}s...")
                time.sleep(wait)
                continue
            return resp
        except requests.RequestException as e:
            if attempt == max_retries - 1:
                raise
            wait = 2 ** (attempt + 1)
            print(f"  [Retry {attempt+1}] {e}, aguardando {wait}s...")
            time.sleep(wait)
    return None


def build_pncp_url(it: dict) -> str:
    link = (it.get("linkSistemaOrigem") or "").strip()
    if link:
        return link
    org = it.get("orgaoEntidade") or {}
    cnpj = re.sub(r"\D", "", str(org.get("cnpj") or ""))
    ano = it.get("anoCompra")
    seq = it.get("sequencialCompra")
    if cnpj and ano and seq:
        return f"https://pncp.gov.br/app/editais/{cnpj}/{ano}/{seq}"
    return ""


def fetch_pncp(data_ini="20261017", data_fim="20261116", modalidades=(4, 5, 6), max_pages=12):
    url = "https://pncp.gov.br/api/consulta/v1/contratacoes/publicacao"
    headers = {"Accept": "*/*", "User-Agent": "WiNS-Engenharia-Sync/1.0"}
    rows = []
    removed_inactive = 0

    for mod in modalidades:
        for page in range(1, max_pages + 1):
            try:
                resp = get_with_retry(
                    url,
                    params={
                        "dataInicial": data_ini,
                        "dataFinal": data_fim,
                        "codigoModalidadeContratacao": mod,
                        "pagina": page,
                        "tamanhoPagina": 50,
                    },
                    headers=headers,
                    timeout=25,
                )
                if resp is None or resp.status_code != 200:
                    code = resp.status_code if resp else "None"
                    print(f"[PNCP mod={mod}] Parou na pagina {page} (HTTP {code})")
                    break
                items = (resp.json() or {}).get("data") or []
                if not items:
                    break
                for it in items:
                    obj = (it.get("objetoCompra") or "").strip()
                    if not OBRA_KEYWORDS.search(obj):
                        continue
                    try:
                        valor = float(it.get("valorTotalEstimado") or 0)
                    except (TypeError, ValueError):
                        valor = 0.0
                    if valor <= 100000:
                        continue

                    sit = str(it.get("situacaoCompraNome") or "").strip()
                    dt_enc = (it.get("dataEncerramentoProposta") or "")[:10]
                    if sit.lower() in INACTIVE_STATUS or (dt_enc and dt_enc < "2026-11-16"):
                        removed_inactive += 1
                        continue

                    url_origem = build_pncp_url(it)
                    id_ext = str(it.get("numeroControlePNCP") or "").strip()
                    if not id_ext or not url_origem:
                        continue

                    org = it.get("orgaoEntidade") or {}
                    unid = it.get("unidadeOrgao") or {}
                    rows.append({
                        "fonte": f"pncp_mod_{mod}",
                        "id_externo": id_ext,
                        "obra_nome": re.sub(r"\s+", " ", obj)[:500],
                        "obra_empresa": (org.get("razaoSocial") or "")[:250],
                        "obra_cnpj": re.sub(r"\D", "", str(org.get("cnpj") or "")),
                        "categoria_macro": classify_obra(obj),
                        "obra_uf": str(unid.get("ufSigla") or "")[:2].upper(),
                        "capex_estimado": valor,
                        "data_inicio_prevista": (it.get("dataPublicacaoPncp") or "")[:10],
                        "data_fim_prevista": dt_enc,
                        "situacao": sit,
                        "url_origem": url_origem,
                    })
                time.sleep(1.2)
            except Exception as e:
                print(f"[PNCP mod={mod}] Erro na pagina {page}: {e}")
                break
    print(f"[PNCP] Ativas com fonte comprovada: {len(rows)} | Descartadas (encerradas/inativas): {removed_inactive}")
    return rows


def fetch_obrasgov(max_pages=6, page_size=50):
    url = "https://api.obrasgov.gestao.gov.br/obrasgov/api/projeto-investimento"
    headers = {"Accept": "application/json", "User-Agent": "WiNS-Engenharia-Sync/1.0"}
    rows = []
    for page in range(max_pages):
        try:
            resp = get_with_retry(url, {"page": page, "size": page_size}, headers, timeout=45, max_retries=2)
            if resp is None or resp.status_code != 200:
                print(f"[ObrasGov] HTTP {resp.status_code if resp else 'None'} na pagina {page}")
                break
            data = resp.json()
            items = data.get("content", data) if isinstance(data, dict) else data
            if not items:
                break
            for it in items:
                nome = (it.get("nome") or "").strip()
                desc = (it.get("descricao") or "").strip()
                texto = f"{nome} {desc}"
                if not OBRA_KEYWORDS.search(texto):
                    continue
                valor = sum(
                    float(fr.get("valorInvestimentoPrevisto") or 0)
                    for fr in (it.get("fontesDeRecurso") or [])
                    if fr.get("valorInvestimentoPrevisto")
                )
                if valor <= 100000:
                    continue
                dt_ini = (it.get("dataInicialPrevista") or "")[:10]
                dt_fim = (it.get("dataFinalPrevista") or "")[:10]
                if not (dt_ini <= "2027-12-31" and dt_fim >= "2026-11-16" and dt_ini and dt_fim):
                    continue
                sit = str(it.get("situacao") or "")
                if sit.lower() in INACTIVE_STATUS:
                    continue
                id_unico = str(it.get("idUnico") or "").strip()
                if not id_unico:
                    continue
                ufs = it.get("ufs") or []
                uf = ufs[0] if isinstance(ufs, list) and ufs else ""
                if isinstance(uf, dict):
                    uf = uf.get("sigla") or ""
                execs = it.get("executores") or []
                empresa = execs[0].get("nome", "") if execs and isinstance(execs, list) else ""
                cnpj = re.sub(r"\D", "", str(execs[0].get("codigo") or "")) if execs and isinstance(execs, list) else ""
                rows.append({
                    "fonte": "obrasgov_api",
                    "id_externo": id_unico,
                    "obra_nome": re.sub(r"\s+", " ", nome)[:500],
                    "obra_empresa": empresa[:250],
                    "obra_cnpj": cnpj if len(cnpj) == 14 else "",
                    "categoria_macro": classify_obra(texto),
                    "obra_uf": str(uf)[:2].upper(),
                    "capex_estimado": valor,
                    "data_inicio_prevista": dt_ini,
                    "data_fim_prevista": dt_fim,
                    "situacao": sit,
                    "url_origem": f"https://obrasgov.gestao.gov.br/projetos/{id_unico}",
                })
        except Exception as e:
            print(f"[ObrasGov] Indisponivel/timeout na pagina {page}: {e}")
            break
    print(f"[ObrasGov] Ativas com fonte comprovada: {len(rows)}")
    return rows


def rebuild_verified_only_db(api_rows):
    if os.path.exists(SUB_DB):
        os.remove(SUB_DB)

    con = duckdb.connect(SUB_DB)
    temp_api_csv = os.path.join(BASE_DIR, "Arquivos_Tratados", "_tmp_api_sync.csv")
    fields = [
        "fonte", "id_externo", "obra_nome", "obra_empresa", "obra_cnpj",
        "categoria_macro", "obra_uf", "capex_estimado", "data_inicio_prevista",
        "data_fim_prevista", "situacao", "url_origem"
    ]
    with open(temp_api_csv, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(api_rows)

    csv_sql = temp_api_csv.replace("\\", "/")
    con.execute(f"""
    CREATE TABLE obras_oficiais_2026_2027 AS
    SELECT DISTINCT ON (COALESCE(NULLIF(obra_cnpj, ''), ''), LOWER(TRIM(REGEXP_REPLACE(obra_nome, '\\s+', ' ', 'g'))))
        fonte,
        id_externo,
        obra_nome,
        obra_empresa,
        NULLIF(obra_cnpj, '') AS obra_cnpj,
        categoria_macro,
        NULLIF(obra_uf, '') AS obra_uf,
        TRY_CAST(capex_estimado AS DOUBLE) AS capex_estimado,
        TRY_CAST(NULLIF(data_inicio_prevista, '') AS DATE) AS data_inicio_prevista,
        TRY_CAST(NULLIF(data_fim_prevista, '') AS DATE) AS data_fim_prevista,
        situacao,
        url_origem
    FROM (
        SELECT DISTINCT ON (id_externo) *
        FROM read_csv('{csv_sql}', header=true, all_varchar=true)
        WHERE id_externo <> '' AND url_origem <> ''
        ORDER BY id_externo, TRY_CAST(capex_estimado AS DOUBLE) DESC
    )
    ORDER BY COALESCE(NULLIF(obra_cnpj, ''), ''), LOWER(TRIM(REGEXP_REPLACE(obra_nome, '\\s+', ' ', 'g'))), capex_estimado DESC;
    """)
    if os.path.exists(temp_api_csv):
        os.remove(temp_api_csv)

    # Enriquecer com cruzamento de fornecedores do banco principal (sem manter obras sem fonte comprovada)
    main_sql = MAIN_DB.replace("\\", "/")
    con.execute(f"ATTACH '{main_sql}' AS main_db (READ_ONLY);")
    con.execute("""
    CREATE TABLE obras_consolidadas_ativas AS
    SELECT
        o.*,
        CASE WHEN f.cnpj IS NOT NULL THEN TRUE ELSE FALSE END AS tem_match_fornecedor
    FROM obras_oficiais_2026_2027 o
    LEFT JOIN main_db.fornecedores f ON o.obra_cnpj = f.cnpj;
    """)
    con.execute("DETACH main_db;")

    con.execute("CREATE INDEX idx_oca_uf_cat ON obras_consolidadas_ativas(obra_uf, categoria_macro);")
    con.execute("CREATE INDEX idx_oca_cnpj ON obras_consolidadas_ativas(obra_cnpj);")

    cnt = con.execute("SELECT COUNT(*) FROM obras_consolidadas_ativas").fetchone()[0]
    breakdown = con.execute("""
    SELECT fonte, categoria_macro, COUNT(*) AS qtd, ROUND(SUM(capex_estimado)/1e6, 2) AS capex_mi
    FROM obras_consolidadas_ativas
    GROUP BY 1, 2
    ORDER BY 3 DESC
    """).fetchdf()

    out_csv_sql = OUT_CONSOLIDADO_CSV.replace("\\", "/")
    con.execute(f"COPY obras_consolidadas_ativas TO '{out_csv_sql}' (HEADER, DELIMITER ',');")
    con.close()

    print(f"[SYNC SOMENTE FONTES COMPROVADAS] Total ativo sem duplicidade: {cnt}")
    print(breakdown.to_string(index=False))


if __name__ == "__main__":
    api_rows = []
    api_rows.extend(fetch_pncp(data_ini="20261017", data_fim="20261116", modalidades=(4, 5, 6), max_pages=12))
    api_rows.extend(fetch_obrasgov(max_pages=6, page_size=50))
    rebuild_verified_only_db(api_rows)
