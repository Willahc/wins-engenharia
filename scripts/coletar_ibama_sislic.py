import os
import re
import subprocess
import unicodedata
import duckdb
from rapidfuzz import fuzz
import requests

BASE_DIR = r"C:\Users\kbadmin\Documents\Projetos\01_Ecossistema_WiNS\Engenharia"
MAIN_DB = os.path.join(BASE_DIR, "Banco_Dados", "wins_engenharia.duckdb")
SUB_DB = os.path.join(BASE_DIR, "Banco_Dados", "obras_civil_industrial_2026_2027_100k.duckdb")
RAW_CSV = os.path.join(BASE_DIR, "Arquivos_Tratados", "ibama_sislic_raw.csv")
OUT_DEC_CSV = os.path.join(BASE_DIR, "Arquivos_Tratados", "obras_novas_com_decisores.csv").replace("\\", "/")

SISLIC_URL = "https://stibamadadosabertosprd.blob.core.windows.net/dados-abertos/dados/SISLIC/sislic-licencas.csv"
LEGAL_SUFFIX_RE = re.compile(r"\b(ltda|s\.?a\.?|s/a|eireli|me|epp)\b", re.I)


def strip_acc(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s or "") if not unicodedata.combining(c))


def clean_core(s: str) -> str:
    s = strip_acc(s or "").upper()
    s = LEGAL_SUFFIX_RE.sub(" ", s)
    s = re.sub(r"[^A-Z0-9\s]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def classify_macro(tipologia: str, nome: str) -> str:
    t = strip_acc(f"{tipologia} {nome}".lower())
    if any(k in t for k in ("transmiss", "energia", "usina", "petroleo", "gasoduto", "duto", "nuclear", "termel", "eolica", "solar", "hidrel")):
        return "ENERGIA_E_SANEAMENTO"
    if any(k in t for k in ("miner", "fabrica", "industrial", "siderurg")):
        return "INDUSTRIA_E_FABRICAS"
    return "INFRAESTRUTURA_E_OBRAS_CIVIS"


def extract_uf(nome: str, tipologia: str) -> str:
    m = re.search(r"[-/\s]([A-Z]{2})\b", f"{nome} {tipologia}")
    if m and m.group(1) in {
        "AC", "AL", "AP", "AM", "BA", "CE", "DF", "ES", "GO", "MA", "MT", "MS",
        "MG", "PA", "PB", "PR", "PE", "PI", "RJ", "RN", "RS", "RO", "RR", "SC", "SP", "SE", "TO"
    }:
        return m.group(1)
    return ""


def main() -> None:
    r = requests.get(SISLIC_URL, timeout=30)
    r.raise_for_status()
    with open(RAW_CSV, "wb") as f:
        f.write(r.content)

    tmp = duckdb.connect()
    rows = tmp.execute("""
        WITH filtradas AS (
            SELECT
                DES_TIPOLICENCA,
                NUM_LICENCA,
                DAT_EMISSAO,
                DAT_VENCIMENTO,
                TRIM(NOM_EMPREENDIMENTO) AS empreendimento,
                TRIM(NOM_PESSOA) AS empresa,
                NUM_PROCESSO_IBAMA,
                DES_TIPOLOGIA,
                PAC,
                ROW_NUMBER() OVER (
                    PARTITION BY LOWER(TRIM(NOM_EMPREENDIMENTO)), LOWER(TRIM(NOM_PESSOA))
                    ORDER BY DAT_EMISSAO DESC, NUM_LICENCA DESC
                ) AS rn
            FROM read_csv_auto(?, delim=';', header=true)
            WHERE YEAR(DAT_EMISSAO) >= 2026
              AND (
                  DES_TIPOLICENCA IN ('Licença de Instalação', 'Licença Prévia', 'Licença de Instalação e Operação', 'Renovação de Licença de Instalação')
              )
              AND NOM_EMPREENDIMENTO IS NOT NULL
              AND NOM_PESSOA IS NOT NULL
        )
        SELECT * EXCLUDE (rn) FROM filtradas WHERE rn = 1
        ORDER BY DAT_EMISSAO DESC
    """, [RAW_CSV]).fetchall()
    tmp.close()

    print(f"Licencas LI/LP 2026 unicas coletadas no IBAMA SISLIC: {len(rows)}")

    con = duckdb.connect(MAIN_DB)
    dim_emps = con.execute("""
        SELECT DISTINCT obra_cnpj, obra_empresa
        FROM dim_decisores_empresa
        WHERE obra_cnpj IS NOT NULL AND obra_empresa IS NOT NULL
    """).fetchall()
    dim_index = [(c, e, clean_core(e)) for c, e in dim_emps if len(clean_core(e)) >= 4]
    existing_ids = set(r[0] for r in con.execute("SELECT id_externo FROM obras_oficiais_ativas").fetchall())

    inserted = 0
    resolved_cnpj = 0

    for tipo_lic, num_lic, dt_ini, dt_fim, emp_nome, pessoa, proc, tipologia, pac in rows:
        proc_clean = re.sub(r"[^0-9A-Za-z]", "", str(proc or num_lic))
        id_ext = f"IBAMA-{proc_clean[:20]}"
        if id_ext in existing_ids:
            continue

        core = clean_core(pessoa)
        best_cnpj, best_emp, best_sc = None, pessoa, 0.0
        if len(core) >= 4:
            for cnpj, emp_orig, d_core in dim_index:
                sc = fuzz.token_sort_ratio(core, d_core)
                if sc > best_sc:
                    best_cnpj, best_emp, best_sc = cnpj, emp_orig, sc
            if best_sc < 90:
                tok1 = core.split()[0]
                if len(tok1) >= 4:
                    cands = con.execute("""
                        SELECT cnpj, razao_social, uf
                        FROM fornecedores
                        WHERE situacao = '02' AND UPPER(razao_social) LIKE ?
                        ORDER BY (SUBSTR(cnpj, 9, 4) = '0001') DESC, porte_inferido DESC
                        LIMIT 40
                    """, [f"{tok1}%"]).fetchall()
                    best_cnpj, best_emp, best_sc = None, pessoa, 0.0
                    for cnpj, rz, uf_f in cands:
                        sc = fuzz.token_sort_ratio(core, clean_core(rz))
                        if sc > best_sc:
                            best_cnpj, best_emp, best_sc = cnpj, rz, sc
            if best_sc < 90:
                best_cnpj, best_emp = None, pessoa

        uf = extract_uf(emp_nome, tipologia or "")
        if not uf and best_cnpj:
            uf_row = con.execute("SELECT uf FROM fornecedores WHERE cnpj = ? LIMIT 1", [best_cnpj]).fetchone()
            if uf_row and uf_row[0]:
                uf = uf_row[0]

        if best_cnpj:
            resolved_cnpj += 1

        cat = classify_macro(tipologia or "", emp_nome)
        url_orig = "https://dadosabertos.ibama.gov.br/dataset/licencas-ambientais-de-atividades-e-empreendimentos-licenciados-pelo-ibama"
        sit = f"{tipo_lic} ({tipologia or 'IBAMA'})" + (" [PAC]" if str(pac).lower() == "sim" else "")

        con.execute("""
            INSERT INTO obras_oficiais_ativas (
                id_externo, fonte, obra_nome, obra_empresa, obra_empresa_norm,
                obra_cnpj, obra_cnpj_raiz, categoria_macro, obra_uf, obra_municipio,
                capex_estimado, capex_tipo, data_inicio_prevista, data_fim_prevista,
                situacao, url_origem, tem_match_fornecedor, cnpj_origem_resolucao
            ) VALUES (?, 'ibama_sislic', ?, ?, ?, ?, ?, ?, ?, NULL, NULL, 'LICENCA_AMBIENTAL_IBAMA', ?, ?, ?, ?, ?, ?)
        """, [
            id_ext, emp_nome[:220], best_emp[:180], clean_core(best_emp),
            best_cnpj, best_cnpj[:8] if best_cnpj else None, cat, uf or None,
            str(dt_ini) if dt_ini else None, str(dt_fim) if dt_fim else None,
            sit[:90], url_orig, bool(best_cnpj), "RAPIDFUZZ_FORNECEDORES" if best_cnpj else None
        ])
        existing_ids.add(id_ext)
        inserted += 1

    # Vincular decisores existentes deduplicados por (id_externo, nome, email, linkedin)
    con.execute("""
        INSERT INTO validacao_decisores_obras_novas
        SELECT * EXCLUDE (rn)
        FROM (
            SELECT
                o.id_externo, o.fonte, o.obra_nome, o.obra_empresa, o.obra_cnpj, o.categoria_macro,
                o.obra_uf, o.capex_estimado, o.capex_tipo, o.url_origem,
                '1_CNPJ_EXATO' AS tipo_match,
                d.decisor_id, d.nome, d.cargo, d.email, d.telefone, d.linkedin_url,
                'IBAMA_SISLIC_CNPJ' AS qualidade_lead,
                d.is_contato_acionavel,
                CASE
                    WHEN LOWER(COALESCE(d.cargo, '')) SIMILAR TO '%(comprador|supriment|procurement|aquisi|cotac)%' THEN '1_COMPRADOR_SUPRIMENTOS'
                    WHEN LOWER(COALESCE(d.cargo, '')) SIMILAR TO '%(engenh|obra|projet|implanta|manutenc|epc|planej)%' THEN '2_GESTOR_TECNICO_OBRA'
                    ELSE '3_DIRETORIA_EXECUTIVA'
                END AS perfil_decisor,
                ROW_NUMBER() OVER (
                    PARTITION BY o.id_externo, LOWER(TRIM(d.nome)), COALESCE(LOWER(TRIM(d.email)), ''), COALESCE(LOWER(TRIM(d.linkedin_url)), '')
                    ORDER BY d.is_contato_acionavel DESC, (d.linkedin_url IS NOT NULL) DESC, d.decisor_id
                ) AS rn
            FROM obras_oficiais_ativas o
            JOIN dim_decisores_empresa d ON o.obra_cnpj = d.obra_cnpj
            WHERE o.fonte = 'ibama_sislic'
              AND o.obra_cnpj IS NOT NULL
              AND o.id_externo NOT IN (SELECT DISTINCT id_externo FROM validacao_decisores_obras_novas)
        )
        WHERE rn = 1;
    """)

    ibama_dec = con.execute("SELECT COUNT(DISTINCT id_externo) FROM validacao_decisores_obras_novas WHERE fonte = 'ibama_sislic'").fetchone()[0]
    con.execute(f"COPY validacao_decisores_obras_novas TO '{OUT_DEC_CSV}' (HEADER, DELIMITER ',');")
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

    print(f"IBAMA SISLIC inseridas: {inserted} | Com CNPJ resolvido: {resolved_cnpj} | Ja vinculadas a decisores: {ibama_dec}")
    subprocess.run(["python", os.path.join(BASE_DIR, "scripts", "sincronizar_todas_obras_consolidadas.py")], check=True)


if __name__ == "__main__":
    main()
