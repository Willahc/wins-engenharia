import os
import subprocess
import duckdb

BASE_DIR = r"C:\Users\kbadmin\Documents\Projetos\01_Ecossistema_WiNS\Engenharia"
MAIN_DB = os.path.join(BASE_DIR, "Banco_Dados", "wins_engenharia.duckdb")
SUB_DB = os.path.join(BASE_DIR, "Banco_Dados", "obras_civil_industrial_2026_2027_100k.duckdb")
OUT_ALL_CSV = os.path.join(BASE_DIR, "Arquivos_Tratados", "obras_ativas_fontes_validadas.csv").replace("\\", "/")
OUT_DEC_CSV = os.path.join(BASE_DIR, "Arquivos_Tratados", "obras_novas_com_decisores.csv").replace("\\", "/")

con = duckdb.connect(MAIN_DB)

before_ce = con.execute("SELECT COUNT(*) FROM todas_obras_consolidadas WHERE decisores_operacionais > 0").fetchone()[0]

# 1. Reclassificar TODOS os decisores com regex completa PT + EN
con.execute("""
CREATE OR REPLACE TABLE validacao_decisores_obras_novas AS
SELECT
    * EXCLUDE (perfil_decisor),
    CASE
        WHEN REGEXP_MATCHES(COALESCE(decisor_cargo, ''), '(?i)(compra|suprimento|procurement|purchasing|sourcing|supply\\s*chain|logistics|log[ií]stica|warehouse|almoxarifado|licitac|pregoeir|aquisic|contrato|contract)')
            THEN '1_COMPRADOR_SUPRIMENTOS'
        WHEN REGEXP_MATCHES(COALESCE(decisor_cargo, ''), '(?i)(engenheir|engenharia|engineering|projeto|project|obra|capex|implantac|manutenc|maintenance|operac|operations|industrial|construc|construction|infraestrutura|tecnic|meio\\s*ambiente|greenfield|subesta|commissioning|comissionamento|site\\s*manager|plant\\s*manager|asset\\s*management)')
            THEN '2_GESTOR_TECNICO_OBRA'
        WHEN REGEXP_MATCHES(COALESCE(decisor_cargo, ''), '(?i)(diretor|director|presidente|ceo|cfo|coo|cto|cco|vp|vice[- ]presidente|superintendente|head|gerente\\s*geral|general\\s*manager|general\\s*counsel)')
            THEN '3_DIRETORIA_EXECUTIVA'
        WHEN tipo_match = '4_QSA_BRASILAPI'
          OR REGEXP_MATCHES(COALESCE(decisor_cargo, ''), '(?i)(s[oó]cio|administrador|procurador|representante\\s*legal|titular|conselheiro)')
            THEN '4_SOCIO_QSA'
        ELSE '5_OUTRO_NAO_CLASSIFICADO'
    END AS perfil_decisor
FROM validacao_decisores_obras_novas;
""")

after_reclass = con.execute("""
SELECT COUNT(DISTINCT id_externo)
FROM validacao_decisores_obras_novas
WHERE perfil_decisor IN ('1_COMPRADOR_SUPRIMENTOS', '2_GESTOR_TECNICO_OBRA')
""").fetchone()[0]

# 2. Propagar decisores de Compras/Engenharia por grupo economico (mesmo dominio_corporativo privado)
#    para SPEs que compartilham o mesmo dominio corporativo da holding/desenvolvedora
con.execute("""
CREATE OR REPLACE TEMP TABLE prop_grupo AS
WITH dom_op AS (
    SELECT DISTINCT ON (t.dominio_corporativo, LOWER(TRIM(v.decisor_nome)))
        t.dominio_corporativo,
        v.decisor_id,
        v.decisor_nome,
        v.decisor_cargo,
        v.decisor_email,
        v.decisor_telefone,
        v.decisor_linkedin,
        v.qualidade_lead,
        v.is_contato_acionavel,
        v.perfil_decisor
    FROM validacao_decisores_obras_novas v
    JOIN todas_obras_consolidadas t ON v.id_externo = t.obra_id
    WHERE t.dominio_corporativo IS NOT NULL
      AND t.dominio_corporativo NOT LIKE '%.gov.br'
      AND t.dominio_corporativo NOT LIKE '%.leg.br'
      AND t.dominio_corporativo NOT LIKE '%.jus.br'
      AND v.perfil_decisor IN ('1_COMPRADOR_SUPRIMENTOS', '2_GESTOR_TECNICO_OBRA')
      AND v.is_contato_acionavel = TRUE
    ORDER BY t.dominio_corporativo, LOWER(TRIM(v.decisor_nome)), v.perfil_decisor
),
obras_sem_ce AS (
    SELECT t.*
    FROM todas_obras_consolidadas t
    WHERE t.dominio_corporativo IS NOT NULL
      AND NOT EXISTS (
          SELECT 1 FROM validacao_decisores_obras_novas v
          WHERE v.id_externo = t.obra_id
            AND v.perfil_decisor IN ('1_COMPRADOR_SUPRIMENTOS', '2_GESTOR_TECNICO_OBRA')
      )
)
SELECT
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
    '10_GRUPO_DOMINIO_SPE' AS tipo_match,
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
JOIN dom_op d ON o.dominio_corporativo = d.dominio_corporativo;
""")

prop_cnt = con.execute("SELECT COUNT(*) FROM prop_grupo").fetchone()[0]
if prop_cnt > 0:
    con.execute("INSERT INTO validacao_decisores_obras_novas SELECT * FROM prop_grupo;")
    con.execute("""
    CREATE OR REPLACE TABLE validacao_decisores_obras_novas AS
    SELECT DISTINCT ON (id_externo, LOWER(TRIM(decisor_nome)), COALESCE(decisor_email, ''), COALESCE(decisor_linkedin, ''))
        *
    FROM validacao_decisores_obras_novas
    ORDER BY id_externo, LOWER(TRIM(decisor_nome)), COALESCE(decisor_email, ''), COALESCE(decisor_linkedin, ''), perfil_decisor, is_contato_acionavel DESC;
    """)

# Reconstruir todas_obras_consolidadas
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

after_prop = con.execute("SELECT COUNT(*) FROM todas_obras_consolidadas WHERE decisores_operacionais > 0").fetchone()[0]
con.execute(f"COPY todas_obras_consolidadas TO '{OUT_ALL_CSV}' (HEADER, DELIMITER ',');")
con.execute(f"COPY validacao_decisores_obras_novas TO '{OUT_DEC_CSV}' (HEADER, DELIMITER ',');")

con.execute("ANALYZE;")
con.execute("CHECKPOINT;")
con.close()

print(f"Obras com Compras/Eng/CAPEX:")
print(f"  Antes:               {before_ce:,} / 2,604 ({before_ce/2604*100:.1f}%)")
print(f"  Apos reclassif PT/EN:{after_reclass:,} / 2,604 ({after_reclass/2604*100:.1f}%)")
print(f"  Apos prop. grupo/dom:{after_prop:,} / 2,604 ({after_prop/2604*100:.1f}%) (+{prop_cnt:,} vinculos de grupo)")

subprocess.run(["python", os.path.join(BASE_DIR, "scripts", "limpar_cargos_decisores.py")], check=True)
