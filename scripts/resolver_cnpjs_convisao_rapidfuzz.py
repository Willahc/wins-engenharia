import os
import re
import subprocess
import unicodedata
import duckdb
from rapidfuzz import fuzz

BASE_DIR = r"C:\Users\kbadmin\Documents\Projetos\01_Ecossistema_WiNS\Engenharia"
MAIN_DB = os.path.join(BASE_DIR, "Banco_Dados", "wins_engenharia.duckdb")
SUB_DB = os.path.join(BASE_DIR, "Banco_Dados", "obras_civil_industrial_2026_2027_100k.duckdb")
OUT_DECISORES_CSV = os.path.join(BASE_DIR, "Arquivos_Tratados", "obras_novas_com_decisores.csv").replace("\\", "/")

LEGAL_SUFFIX_RE = re.compile(
    r"\b(ltda|s\.?a\.?|s/a|eireli|me|epp|spe|cia|companhia|brasil|do\s+brasil)\b",
    re.I,
)
BAD_TITLE_NOISE_RE = re.compile(
    r"^(expansao|obra\s+de|inicio\s+de|nova\s+planta|fase\s+de|disputa\s+define|com\s+proposta|fabricante\s+de|investimento|construcao\s+de|ampliacao\s+de)",
    re.I,
)


def strip_acc(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s or "") if not unicodedata.combining(c))


def clean_core(s: str) -> str:
    s = strip_acc(s or "").upper()
    s = LEGAL_SUFFIX_RE.sub(" ", s)
    s = re.sub(r"[^A-Z0-9\s]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def main() -> None:
    con = duckdb.connect(MAIN_DB)

    # 1. Carregar dim_decisores_empresa em memoria para match rapido e preciso
    dim_emps = con.execute("""
        SELECT DISTINCT obra_cnpj, obra_empresa
        FROM dim_decisores_empresa
        WHERE obra_cnpj IS NOT NULL AND obra_empresa IS NOT NULL
    """).fetchall()
    dim_index = [(cnpj, emp, clean_core(emp)) for cnpj, emp in dim_emps if len(clean_core(emp)) >= 5]

    targets = con.execute("""
        SELECT id_externo, obra_empresa, obra_uf
        FROM obras_oficiais_ativas
        WHERE fonte = 'convisao_cnc' AND obra_cnpj IS NULL
    """).fetchall()

    print(f"Obras ConVisao sem CNPJ para resolver: {len(targets)}")
    resolved = 0

    for id_ext, emp_raw, uf in targets:
        core = clean_core(emp_raw)
        if len(core) < 5 or BAD_TITLE_NOISE_RE.search(core):
            continue

        best_cnpj, best_emp, best_score = None, None, 0.0

        # Tentar 1: dim_decisores_empresa (ja tem decisores!)
        for cnpj, emp_orig, d_core in dim_index:
            sc = fuzz.token_sort_ratio(core, d_core)
            if sc > best_score:
                best_cnpj, best_emp, best_score = cnpj, emp_orig, sc

        if best_score < 88:
            # Tentar 2: fornecedores (situacao 02, matriz preferida, mesma UF se disponivel)
            tokens = [t for t in core.split() if len(t) >= 4]
            if not tokens:
                continue
            tok1 = tokens[0]
            uf_clause = "AND uf = ?" if uf else ""
            params = [f"{tok1}%"] + ([uf] if uf else [])
            cands = con.execute(f"""
                SELECT cnpj, razao_social
                FROM fornecedores
                WHERE (situacao = 'ATIVA' OR situacao IS NULL)
                  AND UPPER(razao_social) LIKE ?
                  {uf_clause}
                ORDER BY (SUBSTR(cnpj, 9, 4) = '0001') DESC, porte_inferido DESC
                LIMIT 60
            """, params).fetchall()

            best_cnpj, best_emp, best_score = None, None, 0.0
            for cnpj, rz in cands:
                sc = fuzz.token_sort_ratio(core, clean_core(rz))
                if sc > best_score:
                    best_cnpj, best_emp, best_score = cnpj, rz, sc

        if best_cnpj and best_score >= 88:
            con.execute("""
                UPDATE obras_oficiais_ativas
                SET
                    obra_cnpj = ?,
                    obra_cnpj_raiz = ?,
                    obra_empresa = ?,
                    obra_empresa_norm = ?,
                    tem_match_fornecedor = TRUE,
                    cnpj_origem_resolucao = 'RAPIDFUZZ_FORNECEDORES'
                WHERE id_externo = ?
            """, [best_cnpj, best_cnpj[:8], best_emp[:180], clean_core(best_emp), id_ext])
            resolved += 1

    # Vincular decisores por CNPJ exato ou CNPJ raiz para obras ConVisao resolvidas
    con.execute("""
        INSERT INTO validacao_decisores_obras_novas
        SELECT
            o.id_externo, o.fonte, o.obra_nome, o.obra_empresa, o.obra_cnpj, o.categoria_macro,
            o.obra_uf, o.capex_estimado, o.capex_tipo, o.url_origem,
            CASE WHEN o.obra_cnpj = d.obra_cnpj THEN '1_CNPJ_EXATO' ELSE '2_CNPJ_RAIZ' END AS tipo_match,
            d.decisor_id, d.nome, d.cargo, d.email, d.telefone, d.linkedin_url,
            'CONVISAO_RAPIDFUZZ' AS qualidade_lead,
            d.is_contato_acionavel,
            CASE
                WHEN LOWER(COALESCE(d.cargo, '')) SIMILAR TO '%(comprador|supriment|procurement|aquisi|cotac)%' THEN '1_COMPRADOR_SUPRIMENTOS'
                WHEN LOWER(COALESCE(d.cargo, '')) SIMILAR TO '%(engenh|obra|projet|implanta|manutenc|epc|planej)%' THEN '2_ENGENHARIA_OBRAS_CAPEX'
                ELSE '3_DIRETORIA_EXECUTIVA'
            END AS perfil_decisor
        FROM obras_oficiais_ativas o
        JOIN dim_decisores_empresa d ON o.obra_cnpj_raiz = d.obra_cnpj_raiz
        WHERE o.fonte = 'convisao_cnc'
          AND o.obra_cnpj IS NOT NULL
          AND o.id_externo NOT IN (SELECT DISTINCT id_externo FROM validacao_decisores_obras_novas);
    """)

    tot_conv_cnpj = con.execute("SELECT COUNT(*) FROM obras_oficiais_ativas WHERE fonte='convisao_cnc' AND obra_cnpj IS NOT NULL").fetchone()[0]
    tot_conv_dec = con.execute("SELECT COUNT(DISTINCT id_externo) FROM validacao_decisores_obras_novas WHERE fonte='convisao_cnc'").fetchone()[0]

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

    print(f"Novos CNPJs resolvidos via RapidFuzz: {resolved} | Total ConVisao com CNPJ: {tot_conv_cnpj} | ConVisao com decisores: {tot_conv_dec}")
    subprocess.run(["python", os.path.join(BASE_DIR, "scripts", "gerar_dashboard_html.py")], check=True)
    subprocess.run(["python", os.path.join(BASE_DIR, "scripts", "exportar_planilha_prospeccao.py")], check=True)


if __name__ == "__main__":
    main()
