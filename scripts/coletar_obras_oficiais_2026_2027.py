import os
import re
import time
import json
import requests
import duckdb

BASE_DIR = r"C:\Users\kbadmin\Documents\Projetos\01_Ecossistema_WiNS\Engenharia"
SUB_DB = os.path.join(BASE_DIR, "Banco_Dados", "obras_civil_industrial_2026_2027_100k.duckdb")
OUT_CSV = os.path.join(BASE_DIR, "Arquivos_Tratados", "obras_oficiais_captadas_2026_2027.csv")

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


def classify_obra(text: str) -> str:
    if INDUSTRIAL_KEYWORDS.search(text or ""):
        return "INDUSTRIAL"
    return "CIVIL"


def fetch_obrasgov(max_pages: int = 10, page_size: int = 100):
    url = "https://api.obrasgov.gestao.gov.br/obrasgov/api/projeto-investimento"
    results = []
    headers = {"Accept": "application/json", "User-Agent": "WiNS-Engenharia-DataPipeline/1.0"}
    for page in range(max_pages):
        try:
            resp = requests.get(
                url,
                params={"page": page, "size": page_size},
                headers=headers,
                timeout=20,
            )
            if resp.status_code != 200:
                print(f"[ObrasGov] HTTP {resp.status_code} na pagina {page}")
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

                # Extrair valor previsto (fontesDeRecurso ou valorTotal)
                valor = 0.0
                for fr in (it.get("fontesDeRecurso") or []):
                    try:
                        valor += float(fr.get("valorInvestimentoPrevisto") or 0)
                    except (TypeError, ValueError):
                        pass
                if valor <= 100000:
                    continue

                dt_ini = (it.get("dataInicialPrevista") or "")[:10]
                dt_fim = (it.get("dataFinalPrevista") or "")[:10]
                anos = {dt_ini[:4], dt_fim[:4]}
                # Filtrar projetos com vigencia/previsao em 2026 ou 2027
                if not (("2026" in anos or "2027" in anos) or (dt_ini <= "2027-12-31" and dt_fim >= "2026-01-01" and dt_ini and dt_fim)):
                    continue

                ufs = it.get("ufs") or []
                uf = ufs[0] if isinstance(ufs, list) and ufs else ""
                if isinstance(uf, dict):
                    uf = uf.get("sigla") or ""

                execs = it.get("executores") or []
                empresa = ""
                cnpj = ""
                if execs and isinstance(execs, list):
                    empresa = execs[0].get("nome") or ""
                    cnpj = re.sub(r"\D", "", str(execs[0].get("codigo") or ""))

                results.append({
                    "fonte": "obrasgov_api",
                    "id_externo": str(it.get("idUnico") or ""),
                    "obra_nome": nome[:500],
                    "obra_empresa": empresa[:250],
                    "obra_cnpj": cnpj if len(cnpj) == 14 else "",
                    "categoria_macro": classify_obra(texto),
                    "obra_uf": str(uf)[:2].upper(),
                    "capex_estimado": valor,
                    "data_inicio_prevista": dt_ini,
                    "data_fim_prevista": dt_fim,
                    "situacao": str(it.get("situacao") or ""),
                    "url_origem": f"https://obrasgov.gestao.gov.br/projetos/{it.get('idUnico')}",
                })
        except Exception as e:
            print(f"[ObrasGov] Erro na pagina {page}: {e}")
            break
    print(f"[ObrasGov] Captadas {len(results)} obras 2026-2027 (>100k).")
    return results


def fetch_pncp(data_ini: str = "20261001", data_fim: str = "20261116", modalidades=(4, 6), max_pages: int = 5):
    url = "https://pncp.gov.br/api/consulta/v1/contratacoes/publicacao"
    results = []
    headers = {"Accept": "*/*", "User-Agent": "WiNS-Engenharia-DataPipeline/1.0"}
    for mod in modalidades:
        for page in range(1, max_pages + 1):
            try:
                resp = requests.get(
                    url,
                    params={
                        "dataInicial": data_ini,
                        "dataFinal": data_fim,
                        "codigoModalidadeContratacao": mod,
                        "pagina": page,
                        "tamanhoPagina": 50,
                    },
                    headers=headers,
                    timeout=20,
                )
                if resp.status_code != 200:
                    print(f"[PNCP mod={mod}] HTTP {resp.status_code} na pagina {page}")
                    break
                payload = resp.json()
                items = payload.get("data") or []
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

                    org = it.get("orgaoEntidade") or {}
                    unid = it.get("unidadeOrgao") or {}
                    dt_pub = (it.get("dataPublicacaoPncp") or "")[:10]
                    dt_enc = (it.get("dataEncerramentoProposta") or "")[:10]
                    results.append({
                        "fonte": f"pncp_mod_{mod}",
                        "id_externo": str(it.get("numeroControlePNCP") or ""),
                        "obra_nome": obj[:500],
                        "obra_empresa": (org.get("razaoSocial") or "")[:250],
                        "obra_cnpj": re.sub(r"\D", "", str(org.get("cnpj") or "")),
                        "categoria_macro": classify_obra(obj),
                        "obra_uf": str(unid.get("ufSigla") or "")[:2].upper(),
                        "capex_estimado": valor,
                        "data_inicio_prevista": dt_pub,
                        "data_fim_prevista": dt_enc,
                        "situacao": str(it.get("situacaoCompraNome") or ""),
                        "url_origem": str(it.get("linkSistemaOrigem") or ""),
                    })
                time.sleep(0.2)
            except Exception as e:
                print(f"[PNCP mod={mod}] Erro na pagina {page}: {e}")
                break
    print(f"[PNCP] Captadas {len(results)} obras 2026-2027 (>100k).")
    return results


def save_results(rows):
    import csv
    fields = [
        "fonte", "id_externo", "obra_nome", "obra_empresa", "obra_cnpj",
        "categoria_macro", "obra_uf", "capex_estimado", "data_inicio_prevista",
        "data_fim_prevista", "situacao", "url_origem"
    ]
    with open(OUT_CSV, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)

    con = duckdb.connect(SUB_DB)
    csv_sql = OUT_CSV.replace("\\", "/")
    con.execute(f"""
    CREATE OR REPLACE TABLE obras_oficiais_captadas_2026_2027 AS
    SELECT
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
        NULLIF(url_origem, '') AS url_origem
    FROM read_csv('{csv_sql}', header=true, all_varchar=true);
    """)
    cnt = con.execute("SELECT COUNT(*) FROM obras_oficiais_captadas_2026_2027").fetchone()[0]
    con.close()
    print(f"[DB] Tabela obras_oficiais_captadas_2026_2027 salva com {cnt} registros em {SUB_DB}")


if __name__ == "__main__":
    all_rows = []
    all_rows.extend(fetch_obrasgov(max_pages=10, page_size=100))
    all_rows.extend(fetch_pncp(data_ini="20261001", data_fim="20261116", modalidades=(4, 6), max_pages=5))
    save_results(all_rows)
