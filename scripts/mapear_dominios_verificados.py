import os
import re
import subprocess
import duckdb

BASE_DIR = r"C:\Users\kbadmin\Documents\Projetos\01_Ecossistema_WiNS\Engenharia"
MAIN_DB = os.path.join(BASE_DIR, "Banco_Dados", "wins_engenharia.duckdb")
OUT_DOMAINS = os.path.join(BASE_DIR, "Arquivos_Tratados", "dominios_corporativos_mapeados.csv").replace("\\", "/")

FREE_OR_BUREAU_DOMAINS = {
    "gmail.com", "hotmail.com", "hotmail.com.br", "outlook.com", "outlook.com.br",
    "live.com", "yahoo.com", "yahoo.com.br", "uol.com.br", "bol.com.br",
    "terra.com.br", "ig.com.br", "icloud.com", "globo.com", "r7.com",
    "contabilizei.com.br", "maismei.com.br", "agilize.com.br", "senhorcontabil.com.br",
    "protonmail.com", "aol.com", "msn.com", "zipmail.com.br"
}

con = duckdb.connect(MAIN_DB)

# 1. Tentar recuperar emails nominais REAIS (nao inventados) ja existentes em decisores_por_pessoa_consolidado
#    pelo mesmo LinkedIn valido
recovered = con.execute("""
SELECT COUNT(*)
FROM validacao_decisores_obras_novas v
JOIN decisores_por_pessoa_consolidado p
  ON LOWER(TRIM(v.decisor_linkedin)) = LOWER(TRIM(p.linkedin_url))
WHERE v.decisor_email IS NULL
  AND v.decisor_linkedin IS NOT NULL
  AND p.email IS NOT NULL AND p.email <> ''
  AND p.email_classificacao = 'EMAIL_CORPORATIVO';
""").fetchone()[0]

if recovered > 0:
    con.execute("""
    UPDATE validacao_decisores_obras_novas v
    SET
        decisor_email = LOWER(TRIM(p.email)),
        is_contato_acionavel = TRUE
    FROM decisores_por_pessoa_consolidado p
    WHERE LOWER(TRIM(v.decisor_linkedin)) = LOWER(TRIM(p.linkedin_url))
      AND v.decisor_email IS NULL
      AND v.decisor_linkedin IS NOT NULL
      AND p.email IS NOT NULL AND p.email <> ''
      AND p.email_classificacao = 'EMAIL_CORPORATIVO';
    """)

# 2. Mapear APENAS dominios corporativos reais por CNPJ / CNPJ raiz (sem gerar nenhum email inventado!)
free_list_sql = ",".join(f"'{d}'" for d in sorted(FREE_OR_BUREAU_DOMAINS))
con.execute(f"""
CREATE OR REPLACE TABLE empresa_dominios_verificados AS
WITH dom_dec AS (
    SELECT
        obra_cnpj AS cnpj,
        obra_cnpj_raiz AS cnpj_raiz,
        LOWER(SPLIT_PART(email, '@', 2)) AS dominio,
        'BASE_DECISORES' AS origem_dominio,
        COUNT(*) AS qtd_evidencias
    FROM dim_decisores_empresa
    WHERE email IS NOT NULL AND email LIKE '%@%'
      AND LOWER(SPLIT_PART(email, '@', 2)) NOT IN ({free_list_sql})
    GROUP BY 1, 2, 3
),
dom_forn AS (
    SELECT
        cnpj,
        cnpj_raiz,
        LOWER(SPLIT_PART(email, '@', 2)) AS dominio,
        'BASE_FORNECEDORES_RF' AS origem_dominio,
        1 AS qtd_evidencias
    FROM fornecedores
    WHERE email IS NOT NULL AND email LIKE '%@%'
      AND LOWER(SPLIT_PART(email, '@', 2)) NOT IN ({free_list_sql})
      AND NOT REGEXP_MATCHES(LOWER(email), '(contab|contabil|despach|assessoria|auditoria|cartorio)')
),
dom_val AS (
    SELECT
        obra_cnpj AS cnpj,
        SUBSTR(obra_cnpj, 1, 8) AS cnpj_raiz,
        LOWER(SPLIT_PART(decisor_email, '@', 2)) AS dominio,
        'VALIDACAO_OBRAS_NOVAS' AS origem_dominio,
        COUNT(*) AS qtd_evidencias
    FROM validacao_decisores_obras_novas
    WHERE obra_cnpj IS NOT NULL AND decisor_email IS NOT NULL AND decisor_email LIKE '%@%'
      AND LOWER(SPLIT_PART(decisor_email, '@', 2)) NOT IN ({free_list_sql})
      AND NOT REGEXP_MATCHES(LOWER(decisor_email), '(contab|contabil|despach|assessoria|auditoria|cartorio)')
    GROUP BY 1, 2, 3
),
dom_cons AS (
    SELECT
        cnpj,
        SUBSTR(cnpj, 1, 8) AS cnpj_raiz,
        LOWER(SPLIT_PART(email, '@', 2)) AS dominio,
        'DECISORES_CONSOLIDADO' AS origem_dominio,
        COUNT(*) AS qtd_evidencias
    FROM decisores_por_empresa_consolidado
    WHERE cnpj IS NOT NULL AND email IS NOT NULL AND email LIKE '%@%'
      AND LOWER(SPLIT_PART(email, '@', 2)) NOT IN ({free_list_sql})
      AND NOT REGEXP_MATCHES(LOWER(email), '(contab|contabil|despach|assessoria|auditoria|cartorio)')
    GROUP BY 1, 2, 3
),
alvo_cnpjs AS (
    SELECT DISTINCT
        obra_cnpj AS cnpj,
        obra_cnpj_raiz AS cnpj_raiz,
        ANY_VALUE(obra_empresa) AS obra_empresa,
        COUNT(DISTINCT id_externo) AS qtd_obras_ativas
    FROM obras_oficiais_ativas
    WHERE obra_cnpj IS NOT NULL
    GROUP BY 1, 2
),
candidatos AS (
    SELECT
        a.cnpj,
        a.cnpj_raiz,
        a.obra_empresa,
        a.qtd_obras_ativas,
        COALESCE(d1.dominio, d4.dominio, d2.dominio, d3.dominio, d5.dominio, d6.dominio) AS dominio_corporativo,
        CASE
            WHEN d1.dominio IS NOT NULL THEN '1_DECISORES_CNPJ_EXATO'
            WHEN d4.dominio IS NOT NULL THEN '2_VALIDACAO_CNPJ_EXATO'
            WHEN d2.dominio IS NOT NULL THEN '3_FORNECEDORES_CNPJ_EXATO'
            WHEN d3.dominio IS NOT NULL THEN '4_DECISORES_CNPJ_RAIZ'
            WHEN d5.dominio IS NOT NULL THEN '5_CONSOLIDADO_CNPJ_RAIZ'
            WHEN d6.dominio IS NOT NULL THEN '6_FORNECEDORES_CNPJ_RAIZ'
            ELSE 'SEM_DOMINIO_LOCAL'
        END AS origem_dominio
    FROM alvo_cnpjs a
    LEFT JOIN (
        SELECT DISTINCT ON (cnpj) cnpj, dominio FROM dom_dec WHERE cnpj IS NOT NULL ORDER BY cnpj, qtd_evidencias DESC
    ) d1 ON a.cnpj = d1.cnpj
    LEFT JOIN (
        SELECT DISTINCT ON (cnpj) cnpj, dominio FROM dom_forn ORDER BY cnpj, dominio
    ) d2 ON a.cnpj = d2.cnpj
    LEFT JOIN (
        SELECT DISTINCT ON (cnpj_raiz) cnpj_raiz, dominio FROM dom_dec WHERE cnpj_raiz IS NOT NULL ORDER BY cnpj_raiz, qtd_evidencias DESC
    ) d3 ON a.cnpj_raiz = d3.cnpj_raiz
    LEFT JOIN (
        SELECT DISTINCT ON (cnpj) cnpj, dominio FROM dom_val WHERE cnpj IS NOT NULL ORDER BY cnpj, qtd_evidencias DESC
    ) d4 ON a.cnpj = d4.cnpj
    LEFT JOIN (
        SELECT DISTINCT ON (cnpj_raiz) cnpj_raiz, dominio FROM dom_cons WHERE cnpj_raiz IS NOT NULL ORDER BY cnpj_raiz, qtd_evidencias DESC
    ) d5 ON a.cnpj_raiz = d5.cnpj_raiz
    LEFT JOIN (
        SELECT DISTINCT ON (cnpj_raiz) cnpj_raiz, dominio FROM dom_forn WHERE cnpj_raiz IS NOT NULL ORDER BY cnpj_raiz, dominio
    ) d6 ON a.cnpj_raiz = d6.cnpj_raiz
)
SELECT * FROM candidatos
ORDER BY qtd_obras_ativas DESC;
""")

stats = con.execute("""
SELECT
    origem_dominio,
    COUNT(*) AS cnpjs,
    SUM(qtd_obras_ativas) AS obras_cobertas
FROM empresa_dominios_verificados
GROUP BY 1
ORDER BY 2 DESC;
""").fetchdf()

con.execute(f"COPY empresa_dominios_verificados TO '{OUT_DOMAINS}' (HEADER, DELIMITER ',');")
con.execute("ANALYZE;")
con.execute("CHECKPOINT;")
con.close()

print(f"E-mails corporativos reais recuperados pelo mesmo LinkedIn (sem invencao): {recovered}")
print("\n=== MAPEAMENTO DE DOMINIOS CORPORATIVOS (2.514 OBRAS COM CNPJ) ===")
print(stats.to_string(index=False))
