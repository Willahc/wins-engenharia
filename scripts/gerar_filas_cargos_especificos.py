import os
import subprocess
import duckdb

BASE_DIR = r"C:\Users\kbadmin\Documents\Projetos\01_Ecossistema_WiNS\Engenharia"
MAIN_DB = os.path.join(BASE_DIR, "Banco_Dados", "wins_engenharia.duckdb")
OUT_CARGOS = os.path.join(BASE_DIR, "Arquivos_Tratados", "fila_openbot_compras_engenharia.csv").replace("\\", "/")
OUT_DIR_LK = os.path.join(BASE_DIR, "Arquivos_Tratados", "fila_openbot_linkedin_diretoria.csv").replace("\\", "/")

con = duckdb.connect(MAIN_DB)

# 1. Atualizar decisores_operacionais em todas_obras_consolidadas para contar ESTRITAMENTE Compras/Suprimentos e Engenharia/Projetos/CAPEX
con.execute("""
CREATE OR REPLACE TABLE todas_obras_consolidadas AS
WITH novas_dec AS (
    SELECT
        id_externo,
        COUNT(*) AS qtd_decisores,
        SUM(CASE WHEN is_contato_acionavel THEN 1 ELSE 0 END) AS qtd_acionaveis,
        SUM(CASE WHEN perfil_decisor IN ('1_COMPRADOR_SUPRIMENTOS','2_GESTOR_TECNICO_OBRA') THEN 1 ELSE 0 END) AS qtd_compras_eng
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

# 2. Fila A: Empresas privadas sem Compras/Suprimentos nem Engenharia/Projetos/CAPEX
con.execute(f"""
COPY (
    WITH sem_op AS (
        SELECT *
        FROM todas_obras_consolidadas
        WHERE decisores_operacionais = 0
          AND fonte IN ('bndes_financiamento', 'aneel_siga')
    )
    SELECT
        COALESCE(obra_cnpj, obra_empresa) AS chave,
        ANY_VALUE(obra_cnpj) AS cnpj,
        ANY_VALUE(obra_empresa) AS empresa,
        ANY_VALUE(fonte) AS fonte,
        ANY_VALUE(obra_uf) AS uf,
        ANY_VALUE(dominio_corporativo) AS dominio_corporativo,
        COUNT(*) AS qtd_obras,
        ROUND(SUM(capex_estimado), 2) AS capex_total,
        ANY_VALUE(obra_nome) AS exemplo_obra,
        ANY_VALUE(url_origem) AS url_exemplo
    FROM sem_op
    GROUP BY 1
    ORDER BY capex_total DESC
) TO '{OUT_CARGOS}' (HEADER, DELIMITER ',');
""")

# 3. Fila B: Diretores e Presidentes ja mapeados que estao SEM LinkedIn
con.execute(f"""
COPY (
    SELECT
        ANY_VALUE(v.obra_cnpj) AS cnpj,
        ANY_VALUE(v.obra_empresa) AS empresa,
        v.decisor_nome,
        ANY_VALUE(v.decisor_cargo) AS decisor_cargo,
        ANY_VALUE(t.dominio_corporativo) AS dominio_corporativo,
        ANY_VALUE(v.obra_uf) AS uf,
        COUNT(DISTINCT v.id_externo) AS qtd_obras,
        ROUND(SUM(v.capex_estimado), 2) AS capex_total
    FROM validacao_decisores_obras_novas v
    JOIN todas_obras_consolidadas t ON v.id_externo = t.obra_id
    WHERE v.perfil_decisor = '3_DIRETORIA_EXECUTIVA'
      AND (v.decisor_linkedin IS NULL OR v.decisor_linkedin = '')
      AND v.decisor_nome IS NOT NULL
    GROUP BY LOWER(TRIM(v.decisor_nome)), COALESCE(v.obra_cnpj, v.obra_empresa), v.decisor_nome
    ORDER BY capex_total DESC
) TO '{OUT_DIR_LK}' (HEADER, DELIMITER ',');
""")

cnt_a = con.execute(f"SELECT COUNT(*), SUM(qtd_obras) FROM read_csv('{OUT_CARGOS}', header=true)").fetchone()
cnt_b = con.execute(f"SELECT COUNT(*) FROM read_csv('{OUT_DIR_LK}', header=true)").fetchone()[0]

con.execute("ANALYZE;")
con.execute("CHECKPOINT;")
con.close()

print(f"[FILA A - Sem Compras/Eng/CAPEX] {cnt_a[0]:,} empresas privadas ({int(cnt_a[1]):,} obras)")
print(f"[FILA B - Diretores/Presidentes sem LinkedIn] {cnt_b:,} executivos unicos")

subprocess.run(["python", os.path.join(BASE_DIR, "scripts", "gerar_dashboard_html.py")], check=True)
