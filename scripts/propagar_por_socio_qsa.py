import os
import subprocess
import duckdb

BASE_DIR = r"C:\Users\kbadmin\Documents\Projetos\01_Ecossistema_WiNS\Engenharia"
MAIN_DB = os.path.join(BASE_DIR, "Banco_Dados", "wins_engenharia.duckdb")

con = duckdb.connect(MAIN_DB)

before_ce = con.execute("SELECT COUNT(*) FROM todas_obras_consolidadas WHERE decisores_operacionais > 0").fetchone()[0]

# 1. Propagacao segura por Socio/Administrador/Diretor em comum (nome completo >= 3 palavras)
con.execute("""
CREATE OR REPLACE TEMP TABLE prop_socio AS
WITH obras_com_ce AS (
    SELECT DISTINCT id_externo
    FROM validacao_decisores_obras_novas
    WHERE perfil_decisor IN ('1_COMPRADOR_SUPRIMENTOS', '2_GESTOR_TECNICO_OBRA')
      AND is_contato_acionavel = TRUE
),
socios_em_com_ce AS (
    SELECT DISTINCT
        LOWER(TRIM(v.decisor_nome)) AS socio_norm,
        v.id_externo AS obra_doadora
    FROM validacao_decisores_obras_novas v
    JOIN obras_com_ce c ON v.id_externo = c.id_externo
    WHERE v.perfil_decisor IN ('3_DIRETORIA_EXECUTIVA', '4_SOCIO_QSA')
      AND LENGTH(TRIM(v.decisor_nome)) >= 16
      AND ARRAY_LENGTH(STRING_SPLIT(TRIM(v.decisor_nome), ' ')) >= 3
),
obras_sem_ce AS (
    SELECT t.*
    FROM todas_obras_consolidadas t
    WHERE t.decisores_operacionais = 0
      AND t.fonte IN ('aneel_siga', 'bndes_financiamento')
),
ponte_obras AS (
    SELECT DISTINCT
        s.obra_id AS id_externo_destino,
        sc.obra_doadora
    FROM obras_sem_ce s
    JOIN validacao_decisores_obras_novas v_dest ON s.obra_id = v_dest.id_externo
    JOIN socios_em_com_ce sc ON LOWER(TRIM(v_dest.decisor_nome)) = sc.socio_norm
    WHERE v_dest.perfil_decisor IN ('3_DIRETORIA_EXECUTIVA', '4_SOCIO_QSA')
),
decisores_doadores AS (
    SELECT
        p.id_externo_destino,
        v.decisor_id,
        v.decisor_nome,
        v.decisor_cargo,
        v.decisor_email,
        v.decisor_telefone,
        v.decisor_linkedin,
        v.qualidade_lead,
        v.is_contato_acionavel,
        v.perfil_decisor
    FROM ponte_obras p
    JOIN validacao_decisores_obras_novas v ON p.obra_doadora = v.id_externo
    WHERE v.perfil_decisor IN ('1_COMPRADOR_SUPRIMENTOS', '2_GESTOR_TECNICO_OBRA')
      AND v.is_contato_acionavel = TRUE
)
SELECT DISTINCT ON (o.obra_id, LOWER(TRIM(d.decisor_nome)))
    o.obra_id AS id_externo,
    o.fonte,
    o.obra_nome,
    o.obra_empresa,
    o.obra_cnpj,
    o.categoria_macro,
    o.obra_uf,
    o.capex_estimado,
    o.capex_tipo,
    o.url_origem,
    '11_GRUPO_SOCIO_QSA' AS tipo_match,
    d.decisor_id,
    d.decisor_nome,
    d.decisor_cargo,
    d.decisor_email,
    d.decisor_telefone,
    d.decisor_linkedin,
    d.qualidade_lead,
    d.is_contato_acionavel,
    d.perfil_decisor
FROM obras_sem_ce o
JOIN decisores_doadores d ON o.obra_id = d.id_externo_destino
ORDER BY o.obra_id, LOWER(TRIM(d.decisor_nome)), d.perfil_decisor;
""")

cnt_prop = con.execute("SELECT COUNT(*), COUNT(DISTINCT id_externo) FROM prop_socio").fetchone()
if cnt_prop[0] > 0:
    con.execute("INSERT INTO validacao_decisores_obras_novas SELECT * FROM prop_socio;")
    con.execute("""
    CREATE OR REPLACE TABLE validacao_decisores_obras_novas AS
    SELECT DISTINCT ON (id_externo, LOWER(TRIM(decisor_nome)), COALESCE(decisor_email, ''), COALESCE(decisor_linkedin, ''))
        *
    FROM validacao_decisores_obras_novas
    ORDER BY id_externo, LOWER(TRIM(decisor_nome)), COALESCE(decisor_email, ''), COALESCE(decisor_linkedin, ''), perfil_decisor, is_contato_acionavel DESC;
    """)

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

after_ce = con.execute("SELECT COUNT(*) FROM todas_obras_consolidadas WHERE decisores_operacionais > 0").fetchone()[0]
con.execute("ANALYZE;")
con.execute("CHECKPOINT;")
con.close()

print(f"[PROPAGACAO SOCIO QSA] +{cnt_prop[0]:,} vinculos em {cnt_prop[1]:,} obras!")
print(f"Obras com Compras/Eng/CAPEX: {before_ce:,} -> {after_ce:,} / 2,604 ({after_ce/2604*100:.1f}%)")

# Atualiza Excel, CSVs e Dashboard HTML
subprocess.run(["python", os.path.join(BASE_DIR, "scripts", "limpar_cargos_decisores.py")], check=True)
