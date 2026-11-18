import os
import subprocess
import duckdb
from classificar_fases_obras import apply_fase_classification
from detectar_mudancas_fase import ensure_score_column, compute_lead_score, detect_phase_changes

BASE_DIR = r"C:\Users\kbadmin\Documents\Projetos\01_Ecossistema_WiNS\Engenharia"
MAIN_DB = os.path.join(BASE_DIR, "Banco_Dados", "wins_engenharia.duckdb")
SUB_DB = os.path.join(BASE_DIR, "Banco_Dados", "obras_civil_industrial_2026_2027_100k.duckdb")
OUT_ALL_CSV = os.path.join(BASE_DIR, "Arquivos_Tratados", "todas_obras_antigas_e_novas_consolidadas.csv").replace("\\", "/")
OUT_ANTISPAM_CSV = os.path.join(BASE_DIR, "Arquivos_Tratados", "WiNS_Prospeccao_Por_Decisor_Unico.csv")


def main() -> None:
    con = duckdb.connect(MAIN_DB)

    # 1. Inserir em todas_obras_consolidadas quaisquer obras novas de obras_oficiais_ativas (ex: convisao_cnc)
    dom_cols = {r[0] for r in con.execute("DESCRIBE empresa_dominios_verificados").fetchall()}
    mx_expr = "COALESCE(d.mx_ativo, FALSE)" if "mx_ativo" in dom_cols else "FALSE"
    before_cnt = con.execute("SELECT COUNT(*) FROM todas_obras_consolidadas").fetchone()[0]
    con.execute(f"""
        INSERT INTO todas_obras_consolidadas (
            obra_id, origem_registro, status_validacao_fonte, fonte, obra_nome, obra_empresa,
            obra_cnpj, obra_cnpj_raiz, categoria_macro, setor_detalhado, obra_uf, obra_municipio,
            capex_estimado, capex_tipo, data_inicio_prevista, data_fim_prevista, situacao,
            url_origem, tem_match_fornecedor, dominio_corporativo, mx_ativo,
            total_decisores, decisores_acionaveis, decisores_operacionais,
            whatsapp_oficial, telefones_site
        )
        SELECT
            o.id_externo AS obra_id,
            'OBRA_NOVA_2026_2027' AS origem_registro,
            'VALIDADA_FONTE_OFICIAL' AS status_validacao_fonte,
            o.fonte,
            o.obra_nome,
            o.obra_empresa,
            o.obra_cnpj,
            o.obra_cnpj_raiz,
            o.categoria_macro,
            o.categoria_macro AS setor_detalhado,
            o.obra_uf,
            o.obra_municipio,
            o.capex_estimado,
            o.capex_tipo,
            TRY_CAST(o.data_inicio_prevista AS DATE),
            TRY_CAST(o.data_fim_prevista AS DATE),
            o.situacao,
            o.url_origem,
            o.tem_match_fornecedor,
            d.dominio_corporativo,
            {mx_expr},
            0, 0, 0,
            w.whatsapp_oficial,
            w.telefones_site
        FROM obras_oficiais_ativas o
        LEFT JOIN empresa_dominios_verificados d ON o.obra_cnpj = d.cnpj
        LEFT JOIN empresa_whatsapp_oficial w ON d.dominio_corporativo = w.dominio
        WHERE o.id_externo NOT IN (SELECT obra_id FROM todas_obras_consolidadas);
    """)

    # 2. Recalcular contagens de decisores em todas_obras_consolidadas
    con.execute("""
        CREATE OR REPLACE TABLE todas_obras_consolidadas AS
        WITH novas_dec AS (
            SELECT
                id_externo,
                COUNT(*) AS qtd_decisores,
                SUM(CASE WHEN is_contato_acionavel THEN 1 ELSE 0 END) AS qtd_acionaveis,
                SUM(CASE WHEN perfil_decisor IN ('1_COMPRADOR_SUPRIMENTOS', '2_ENGENHARIA_OBRAS_CAPEX', '2_GESTOR_TECNICO_OBRA') THEN 1 ELSE 0 END) AS qtd_compras_eng
            FROM validacao_decisores_obras_novas
            GROUP BY 1
        )
        SELECT
            t.* EXCLUDE (total_decisores, decisores_acionaveis, decisores_operacionais),
            COALESCE(d.qtd_decisores, 0) AS total_decisores,
            COALESCE(d.qtd_acionaveis, 0) AS decisores_acionaveis,
            COALESCE(d.qtd_compras_eng, 0) AS decisores_operacionais
        FROM todas_obras_consolidadas t
        LEFT JOIN novas_dec d ON t.obra_id = d.id_externo;
    """)

    # 3. Reconstruir campanha_por_decisor_unico
    con.execute("""
        CREATE OR REPLACE TABLE campanha_por_decisor_unico AS
        WITH base AS (
            SELECT
                v.*,
                t.dominio_corporativo,
                t.mx_ativo,
                t.whatsapp_oficial,
                LOWER(TRIM(v.decisor_nome)) || '|' || COALESCE(
                    NULLIF(LOWER(TRIM(v.decisor_email)), ''),
                    NULLIF(LOWER(TRIM(v.decisor_linkedin)), ''),
                    NULLIF(TRIM(v.decisor_telefone), ''),
                    'SEM_CANAL'
                ) AS chave_pessoa
            FROM validacao_decisores_obras_novas v
            JOIN todas_obras_consolidadas t ON v.id_externo = t.obra_id
            WHERE v.is_contato_acionavel = TRUE
        )
        SELECT
            chave_pessoa,
            ANY_VALUE(decisor_nome) AS decisor_nome,
            MIN(perfil_decisor) AS perfil_prioritario,
            ANY_VALUE(decisor_cargo) AS decisor_cargo,
            NULLIF(MAX(COALESCE(decisor_email, '')), '') AS decisor_email,
            NULLIF(MAX(COALESCE(decisor_telefone, '')), '') AS decisor_telefone,
            NULLIF(MAX(COALESCE(decisor_linkedin, '')), '') AS decisor_linkedin,
            NULLIF(MAX(COALESCE(dominio_corporativo, '')), '') AS dominio_corporativo,
            BOOL_OR(COALESCE(mx_ativo, FALSE)) AS dominio_mx_ativo,
            NULLIF(MAX(COALESCE(whatsapp_oficial, '')), '') AS whatsapp_oficial_empresa,
            COUNT(DISTINCT id_externo) AS qtd_obras_sob_gestao,
            ROUND(SUM(capex_estimado), 2) AS capex_total_sob_gestao,
            STRING_AGG(DISTINCT obra_uf, ', ' ORDER BY obra_uf) AS ufs_atuacao,
            STRING_AGG(DISTINCT categoria_macro, ', ' ORDER BY categoria_macro) AS categorias,
            STRING_AGG(DISTINCT obra_empresa, ' | ') FILTER (WHERE obra_empresa IS NOT NULL) AS empresas_relacionadas,
            ARG_MAX(obra_nome, capex_estimado) AS obra_principal_maior_capex,
            ARG_MAX(url_origem, capex_estimado) AS url_obra_principal
        FROM base
        GROUP BY chave_pessoa
        ORDER BY perfil_prioritario, capex_total_sob_gestao DESC;
    """)

    after_cnt = con.execute("SELECT COUNT(*) FROM todas_obras_consolidadas").fetchone()[0]
    conv_cnt = con.execute("SELECT COUNT(*) FROM todas_obras_consolidadas WHERE fonte = 'convisao_cnc'").fetchone()[0]
    apply_fase_classification(con)
    ensure_score_column(con)
    compute_lead_score(con)
    detect_phase_changes(con)

    con.execute(f"COPY todas_obras_consolidadas TO '{OUT_ALL_CSV}' (HEADER, DELIMITER ',');")
    con.execute("SELECT * FROM campanha_por_decisor_unico").fetchdf().to_csv(OUT_ANTISPAM_CSV, index=False, encoding="utf-8-sig")
    con.execute("ANALYZE;")
    con.execute("CHECKPOINT;")
    con.close()

    print(f"todas_obras_consolidadas: {before_cnt:,} -> {after_cnt:,} (convisao_cnc={conv_cnt:,})")

    subprocess.run(["python", os.path.join(BASE_DIR, "scripts", "gerar_dashboard_html.py")], check=True)
    subprocess.run(["python", os.path.join(BASE_DIR, "scripts", "exportar_planilha_prospeccao.py")], check=True)


if __name__ == "__main__":
    main()
