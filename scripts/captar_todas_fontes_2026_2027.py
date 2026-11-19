import csv
import io
import os
import re
import time
from datetime import datetime
import duckdb
import requests

BASE_DIR = r"C:\Users\kbadmin\Documents\Projetos\01_Ecossistema_WiNS\Engenharia"
MAIN_DB = os.path.join(BASE_DIR, "Banco_Dados", "wins_engenharia.duckdb")
SUB_DB = os.path.join(BASE_DIR, "Banco_Dados", "obras_civil_industrial_2026_2027_100k.duckdb")
OUT_CSV = os.path.join(BASE_DIR, "Arquivos_Tratados", "obras_consolidadas_sem_duplicidade.csv")

UFS_BR = {
    "AC", "AL", "AP", "AM", "BA", "CE", "DF", "ES", "GO", "MA", "MT", "MS",
    "MG", "PA", "PB", "PR", "PE", "PI", "RJ", "RN", "RS", "RO", "RR", "SC",
    "SP", "SE", "TO"
}

OBRA_KEYWORDS = re.compile(
    r"\b(obra|obras|constru[cç][aã]o|reforma|amplia[cç][aã]o|pavimenta[cç][aã]o|"
    r"drenagem|saneamento|esgoto|adutora|ponte|viaduto|rodovia|ferrovia|porto|"
    r"subesta[cç][aã]o|usina|f[aá]brica|galp[aã]o|planta\s+industrial|terraplanagem|"
    r"edifica[cç][aã]o|engenharia|infraestrutura|hospital|escola|creche|implanta[cç][aã]o)\b",
    re.I
)
NON_OBRA_KEYWORDS = re.compile(
    r"\b(storage|vigil[aâ]ncia\s+(armada|patrimonial|eletr[oô]nica)|limpeza\s+predial|"
    r"conserva[cç][aã]o\s+e\s+limpeza|software|licen[cç]a\s+de\s+uso|mobili[aá]rio|"
    r"passagens\s+a[eé]reas|alimenta[cç][aã]o|refei[cç][oõ]es|loca[cç][aã]o\s+de\s+ve[ií]culos|"
    r"computador|notebook|switch|datacenter\s+cloud|nuvem)\b",
    re.I
)
INDUSTRIAL_KEYWORDS = re.compile(
    r"\b(industrial|f[aá]brica|usina|planta|sider[uú]rg|petroqu[ií]m|minera[cç][aã]o|"
    r"subesta[cç][aã]o|caldeira|refinaria|galp[aã]o\s+industrial|data\s*center|e[oó]lica|fotovoltaica|termel[eé]trica)\b",
    re.I
)
INACTIVE_STATUS = {"revogada", "anulada", "fracassada", "deserta", "suspensa", "cancelada", "encerrada", "liquidado"}


def classify_obra(text: str) -> str:
    return "INDUSTRIAL" if INDUSTRIAL_KEYWORDS.search(text or "") else "CIVIL"


def get_with_retry(url, params=None, headers=None, timeout=30, max_retries=3):
    for attempt in range(max_retries):
        try:
            resp = requests.get(url, params=params, headers=headers, timeout=timeout)
            if resp.status_code == 429:
                time.sleep(2 ** (attempt + 1))
                continue
            return resp
        except requests.RequestException:
            if attempt == max_retries - 1:
                raise
            time.sleep(2 ** (attempt + 1))
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


def fetch_pncp():
    url = "https://pncp.gov.br/api/consulta/v1/contratacoes/publicacao"
    headers = {"Accept": "*/*", "User-Agent": "WiNS-Engenharia-Sync/1.0"}
    today_ymd = datetime.now().strftime("%Y%m%d")
    windows = [
        ("20260701", "20260815"),
        ("20260816", "20260930"),
        ("20261001", "20261031"),
        ("20261101", max("20261116", today_ymd)),
    ]
    modalidades = (4, 5, 6, 8)
    rows = []
    for d_ini, d_fim in windows:
        for mod in modalidades:
            for page in range(1, 10):
                try:
                    resp = get_with_retry(
                        url,
                        params={
                            "dataInicial": d_ini,
                            "dataFinal": d_fim,
                            "codigoModalidadeContratacao": mod,
                            "pagina": page,
                            "tamanhoPagina": 50,
                        },
                        headers=headers,
                        timeout=25,
                    )
                    if resp is None or resp.status_code != 200:
                        break
                    items = (resp.json() or {}).get("data") or []
                    if not items:
                        break
                    for it in items:
                        obj = (it.get("objetoCompra") or "").strip()
                        if not OBRA_KEYWORDS.search(obj) or NON_OBRA_KEYWORDS.search(obj):
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
                            continue
                        url_origem = build_pncp_url(it)
                        id_ext = str(it.get("numeroControlePNCP") or "").strip()
                        if not id_ext or not url_origem:
                            continue
                        org = it.get("orgaoEntidade") or {}
                        unid = it.get("unidadeOrgao") or {}
                        uf = str(unid.get("ufSigla") or "")[:2].upper()
                        if uf not in UFS_BR:
                            continue
                        rows.append({
                            "fonte": f"pncp_mod_{mod}",
                            "id_externo": id_ext,
                            "obra_nome": re.sub(r"\s+", " ", obj)[:500],
                            "obra_empresa": (org.get("razaoSocial") or "")[:250],
                            "obra_cnpj": re.sub(r"\D", "", str(org.get("cnpj") or "")),
                            "categoria_macro": classify_obra(obj),
                            "obra_uf": uf,
                            "obra_municipio": str(unid.get("municipioNome") or "")[:120],
                            "capex_estimado": valor,
                            "data_inicio_prevista": (it.get("dataPublicacaoPncp") or "")[:10],
                            "data_fim_prevista": dt_enc,
                            "situacao": sit,
                            "url_origem": url_origem,
                        })
                    time.sleep(0.8)
                except Exception:
                    break
    print(f"[PNCP] Captadas: {len(rows)}")
    return rows


def fetch_obrasgov():
    url = "https://api.obrasgov.gestao.gov.br/obrasgov/api/projeto-investimento"
    headers = {"Accept": "application/json", "User-Agent": "WiNS-Engenharia-Sync/1.0"}
    rows = []
    for page in range(10):
        try:
            resp = get_with_retry(url, {"page": page, "size": 50}, headers, timeout=60, max_retries=2)
            if resp is None or resp.status_code != 200:
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
                uf = str(uf)[:2].upper()
                if uf not in UFS_BR:
                    continue
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
                    "obra_uf": uf,
                    "obra_municipio": "",
                    "capex_estimado": valor,
                    "data_inicio_prevista": dt_ini,
                    "data_fim_prevista": dt_fim,
                    "situacao": sit,
                    "url_origem": f"https://obrasgov.gestao.gov.br/projetos/{id_unico}",
                })
        except Exception as e:
            print(f"[ObrasGov] Parou na pagina {page}: {e}")
            break
    print(f"[ObrasGov] Captadas: {len(rows)}")
    return rows


def fetch_bndes():
    url = "https://dadosabertos.bndes.gov.br/dataset/10e21ad1-568e-45e5-a8af-43f2c05ef1a2/resource/6f56b78c-510f-44b6-8274-78a5b7e931f4/download/operacoes-financiamento-operacoes-nao-automaticas.csv"
    rows = []
    try:
        resp = requests.get(url, timeout=60, headers={"User-Agent": "WiNS-Engenharia-Sync/1.0"})
        if resp.status_code != 200:
            return rows
        text = resp.content.decode("utf-8", errors="replace")
        reader = csv.DictReader(io.StringIO(text), delimiter=";")
        for r in reader:
            dt = (r.get("data_da_contratacao") or "")[:10]
            if dt < "2026-01-01":
                continue
            sit = (r.get("situacao_do_contrato") or "").strip()
            if sit.lower() in INACTIVE_STATUS:
                continue
            desc = (r.get("descricao_do_projeto") or "").strip()
            setor_b = (r.get("setor_bndes") or "") + " " + (r.get("subsetor_bndes") or "")
            if not (OBRA_KEYWORDS.search(desc) or "INFRAESTRUTURA" in setor_b.upper() or "INDUSTRIA" in setor_b.upper()):
                continue
            val_str = (r.get("valor_contratado_reais") or "0").replace(".", "").replace(",", ".")
            try:
                valor = float(val_str)
            except ValueError:
                valor = 0.0
            if valor <= 100000:
                continue
            uf = (r.get("uf") or "").strip().upper()
            if uf not in UFS_BR:
                continue
            contrato = (r.get("numero_do_contrato") or "").strip()
            cnpj = re.sub(r"\D", "", r.get("cnpj") or "")
            rows.append({
                "fonte": "bndes_financiamento",
                "id_externo": f"BNDES-{contrato}",
                "obra_nome": re.sub(r"\s+", " ", desc)[:500],
                "obra_empresa": (r.get("cliente") or "").strip()[:250],
                "obra_cnpj": cnpj if len(cnpj) == 14 else "",
                "categoria_macro": "INDUSTRIAL" if "INDUSTRIA" in setor_b.upper() or INDUSTRIAL_KEYWORDS.search(desc) else "CIVIL",
                "obra_uf": uf,
                "obra_municipio": (r.get("municipio") or "").strip()[:120],
                "capex_estimado": valor,
                "data_inicio_prevista": dt,
                "data_fim_prevista": "",
                "situacao": sit,
                "url_origem": "https://dadosabertos.bndes.gov.br/dataset/operacoes-financiamento",
            })
    except Exception as e:
        print(f"[BNDES] Erro: {e}")
    print(f"[BNDES] Captadas (2026+): {len(rows)}")
    return rows


def fetch_aneel_siga():
    url = "https://dadosabertos.aneel.gov.br/dataset/6d90b77c-c5f5-4d81-bdec-7bc619494bb9/resource/11ec447d-698d-4ab8-977f-b424d5deee6a/download/siga-empreendimentos-geracao.csv"
    rows = []
    try:
        resp = requests.get(url, timeout=60, headers={"User-Agent": "WiNS-Engenharia-Sync/1.0"})
        if resp.status_code != 200:
            return rows
        text = resp.content.decode("utf-8-sig", errors="replace")
        reader = csv.DictReader(io.StringIO(text), delimiter=";")
        for r in reader:
            fase = (r.get("DscFaseUsina") or "").strip()
            if fase not in ("Construção", "Construção não iniciada"):
                continue
            dt_fim_vig = (r.get("DatFimVigencia") or "")[:10]
            today_iso = datetime.now().strftime("%Y-%m-%d")
            if dt_fim_vig and dt_fim_vig < today_iso:
                continue
            uf = (r.get("SigUFPrincipal") or "").strip().upper()
            if uf not in UFS_BR:
                continue
            pot_str = (r.get("MdaPotenciaOutorgadaKw") or "0").replace(".", "").replace(",", ".")
            try:
                pot_kw = float(pot_str)
            except ValueError:
                pot_kw = 0.0
            if pot_kw < 100:
                continue
            ceg = (r.get("CodCEG") or "").strip()
            nome = (r.get("NomEmpreendimento") or "").strip()
            tipo_g = (r.get("SigTipoGeracao") or "").strip()
            rows.append({
                "fonte": "aneel_siga",
                "id_externo": ceg,
                "obra_nome": f"Usina {tipo_g} {nome} ({pot_kw:,.0f} kW)",
                "obra_empresa": (r.get("DscPropriRegimePariticipacao") or "").strip()[:250],
                "obra_cnpj": "",
                "categoria_macro": "INDUSTRIAL",
                "obra_uf": uf,
                "obra_municipio": (r.get("DscMuninicpios") or "").strip()[:120],
                "capex_estimado": round(pot_kw * 4500.0, 2),
                "data_inicio_prevista": (r.get("DatGeracaoConjuntoDados") or "")[:10],
                "data_fim_prevista": dt_fim_vig,
                "situacao": fase,
                "url_origem": "https://dadosabertos.aneel.gov.br/dataset/siga-sistema-de-informacoes-de-geracao-da-aneel",
            })
    except Exception as e:
        print(f"[ANEEL] Erro: {e}")
    print(f"[ANEEL SIGA] Captadas (em construcao/outorgadas 2026+): {len(rows)}")
    return rows


def fetch_recife_licenciamento():
    url = "https://dados.recife.pe.gov.br:443/dataset/f79dbcdf-ec99-4f4c-9b84-b33175c35528/resource/39927a3d-3235-436a-9dc8-df7f4ea3b720/download/licenciamento_urbanistico.csv"
    rows = []
    try:
        resp = requests.get(url, timeout=45, headers={"User-Agent": "WiNS-Engenharia-Sync/1.0"})
        if resp.status_code != 200:
            return rows
        text = resp.content.decode("utf-8-sig", errors="replace")
        reader = csv.DictReader(io.StringIO(text), delimiter=";")
        for r in reader:
            cat = (r.get("categoria_empreendimento") or "").strip().lower()
            if cat != "obra":
                continue
            dt_val = (r.get("data_validade_licenca") or "")[:10]
            if not (dt_val >= "2026-11-16" and dt_val <= "2028-12-31"):
                continue
            area_str = (r.get("areatotalconstruida") or "0").replace(".", "").replace(",", ".")
            try:
                area = float(area_str)
            except ValueError:
                area = 0.0
            capex_est = area * 2500.0
            if capex_est <= 100000:
                continue
            num_proc = (r.get("num_processo") or r.get("dsqfl") or "").strip()
            assunto = (r.get("assunto") or "").strip()
            end = (r.get("endereco_empreendimento") or "").strip()
            cnpj = re.sub(r"\D", "", r.get("cnpj") or "")
            rows.append({
                "fonte": "recife_licenciamento",
                "id_externo": f"RECIFE-{num_proc}",
                "obra_nome": f"{assunto} - {end}"[:500],
                "obra_empresa": (r.get("razao_social") or "").strip()[:250],
                "obra_cnpj": cnpj if len(cnpj) == 14 else "",
                "categoria_macro": "CIVIL",
                "obra_uf": "PE",
                "obra_municipio": "Recife",
                "capex_estimado": round(capex_est, 2),
                "data_inicio_prevista": (r.get("data_emissao_licenca") or "")[:10],
                "data_fim_prevista": dt_val,
                "situacao": (r.get("situacao_processo") or "Licenca Ativa")[:120],
                "url_origem": "https://dados.recife.pe.gov.br/dataset/licenciamento-urbanistico",
            })
    except Exception as e:
        print(f"[Recife] Erro: {e}")
    print(f"[Recife] Captadas (ativas >100k): {len(rows)}")
    return rows


def save_all(all_rows):
    if os.path.exists(SUB_DB):
        os.remove(SUB_DB)
    con = duckdb.connect(SUB_DB)
    tmp_csv = os.path.join(BASE_DIR, "Arquivos_Tratados", "_tmp_all_sources.csv")
    fields = [
        "fonte", "id_externo", "obra_nome", "obra_empresa", "obra_cnpj",
        "categoria_macro", "obra_uf", "obra_municipio", "capex_estimado",
        "data_inicio_prevista", "data_fim_prevista", "situacao", "url_origem"
    ]
    with open(tmp_csv, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(all_rows)

    csv_sql = tmp_csv.replace("\\", "/")
    con.execute(f"""
    CREATE TABLE obras_oficiais_2026_2027 AS
    SELECT DISTINCT ON (COALESCE(NULLIF(obra_cnpj, ''), ''), LOWER(TRIM(REGEXP_REPLACE(obra_nome, '\\s+', ' ', 'g'))))
        fonte,
        id_externo,
        obra_nome,
        NULLIF(obra_empresa, '') AS obra_empresa,
        NULLIF(obra_cnpj, '') AS obra_cnpj,
        categoria_macro,
        obra_uf,
        NULLIF(obra_municipio, '') AS obra_municipio,
        TRY_CAST(capex_estimado AS DOUBLE) AS capex_estimado,
        TRY_CAST(NULLIF(data_inicio_prevista, '') AS DATE) AS data_inicio_prevista,
        TRY_CAST(NULLIF(data_fim_prevista, '') AS DATE) AS data_fim_prevista,
        NULLIF(situacao, '') AS situacao,
        url_origem
    FROM (
        SELECT DISTINCT ON (id_externo) *
        FROM read_csv('{csv_sql}', header=true, all_varchar=true)
        WHERE id_externo <> '' AND url_origem <> ''
        ORDER BY id_externo, TRY_CAST(capex_estimado AS DOUBLE) DESC
    )
    ORDER BY COALESCE(NULLIF(obra_cnpj, ''), ''), LOWER(TRIM(REGEXP_REPLACE(obra_nome, '\\s+', ' ', 'g'))), capex_estimado DESC;
    """)
    if os.path.exists(tmp_csv):
        os.remove(tmp_csv)

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
    con.execute("CREATE INDEX idx_oca_fonte ON obras_consolidadas_ativas(fonte);")

    cnt = con.execute("SELECT COUNT(*) FROM obras_consolidadas_ativas").fetchone()[0]
    breakdown = con.execute("""
    SELECT fonte, categoria_macro, COUNT(*) AS qtd, ROUND(SUM(capex_estimado)/1e6, 2) AS capex_mi
    FROM obras_consolidadas_ativas
    GROUP BY 1, 2
    ORDER BY 3 DESC
    """).fetchdf()

    out_sql = OUT_CSV.replace("\\", "/")
    con.execute(f"COPY obras_consolidadas_ativas TO '{out_sql}' (HEADER, DELIMITER ',');")
    con.close()

    print(f"\n[TOTAL UNIFICADO SEM DUPLICIDADE] {cnt:,} obras ativas com fonte comprovada")
    print(breakdown.to_string(index=False))


if __name__ == "__main__":
    all_rows = []
    all_rows.extend(fetch_pncp())
    all_rows.extend(fetch_obrasgov())
    all_rows.extend(fetch_bndes())
    all_rows.extend(fetch_aneel_siga())
    all_rows.extend(fetch_recife_licenciamento())
    save_all(all_rows)
