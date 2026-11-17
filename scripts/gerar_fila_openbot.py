import os
import duckdb

BASE_DIR = r"C:\Users\kbadmin\Documents\Projetos\01_Ecossistema_WiNS\Engenharia"
MAIN_DB = os.path.join(BASE_DIR, "Banco_Dados", "wins_engenharia.duckdb")
OUT_PRIV = os.path.join(BASE_DIR, "Arquivos_Tratados", "fila_openbot_privadas.csv")
OUT_PUB = os.path.join(BASE_DIR, "Arquivos_Tratados", "fila_openbot_publicas_pncp.csv")

con = duckdb.connect(MAIN_DB, read_only=True)

# Obras que JA tem comprador ou gestor tecnico de obra
con.execute("""
CREATE TEMP TABLE obras_com_operacional AS
SELECT DISTINCT id_externo
FROM validacao_decisores_obras_novas
WHERE perfil_decisor IN ('1_COMPRADOR_SUPRIMENTOS', '2_GESTOR_TECNICO_OBRA');
""")

# 1. Fila Privada (BNDES + ANEEL) deduplicada por empresa/CNPJ raiz
con.execute("""
CREATE TEMP TABLE fila_privada AS
WITH pendentes AS (
    SELECT o.*
    FROM obras_oficiais_ativas o
    LEFT JOIN obras_com_operacional op ON o.id_externo = op.id_externo
    WHERE op.id_externo IS NULL
      AND o.fonte IN ('bndes_financiamento', 'aneel_siga')
),
qsa_flag AS (
    SELECT DISTINCT id_externo
    FROM validacao_decisores_obras_novas
    WHERE perfil_decisor = '4_SOCIO_QSA'
)
SELECT
    COALESCE(NULLIF(p.obra_cnpj_raiz, ''), p.obra_empresa_norm) AS chave_empresa_grupo,
    ANY_VALUE(p.obra_cnpj) AS cnpj_principal,
    ANY_VALUE(p.obra_cnpj_raiz) AS cnpj_raiz,
    ANY_VALUE(p.obra_empresa) AS empresa_nome,
    ANY_VALUE(p.fonte) AS fonte_principal,
    ANY_VALUE(p.obra_uf) AS uf_principal,
    COUNT(*) AS qtd_obras_pendentes,
    ROUND(SUM(p.capex_estimado), 2) AS capex_total_estimado,
    MAX(CASE WHEN q.id_externo IS NOT NULL THEN TRUE ELSE FALSE END) AS ja_tem_qsa,
    ANY_VALUE(p.obra_nome) AS exemplo_obra,
    ANY_VALUE(p.url_origem) AS url_exemplo,
    'Gerente de Suprimentos; Gerente de Compras; Gerente de Engenharia; Gerente de Projetos; Coordenador de Obras' AS cargos_alvo
FROM pendentes p
LEFT JOIN qsa_flag q ON p.id_externo = q.id_externo
GROUP BY 1
ORDER BY capex_total_estimado DESC;
""")

# 2. Fila Publica (PNCP) ordenada por CAPEX
con.execute("""
CREATE TEMP TABLE fila_publica AS
SELECT
    o.id_externo AS numero_controle_pncp,
    o.fonte,
    o.categoria_macro,
    o.obra_uf,
    o.obra_municipio,
    o.obra_empresa AS orgao_entidade,
    o.obra_cnpj,
    o.obra_nome AS objeto_obra,
    ROUND(o.capex_estimado, 2) AS capex_estimado,
    o.data_inicio_prevista,
    o.data_fim_prevista,
    o.url_origem,
    'Pregoeiro; Agente de Contratacao; Ordenador de Despesas; Secretario/Diretor de Obras' AS cargos_alvo
FROM obras_oficiais_ativas o
LEFT JOIN obras_com_operacional op ON o.id_externo = op.id_externo
WHERE op.id_externo IS NULL
  AND o.fonte LIKE 'pncp_%'
ORDER BY o.capex_estimado DESC;
""")

priv_cnt = con.execute("SELECT COUNT(*), SUM(qtd_obras_pendentes) FROM fila_privada").fetchone()
pub_cnt = con.execute("SELECT COUNT(*) FROM fila_publica").fetchone()[0]

priv_sql = OUT_PRIV.replace("\\", "/")
pub_sql = OUT_PUB.replace("\\", "/")
con.execute(f"COPY fila_privada TO '{priv_sql}' (HEADER, DELIMITER ',');")
con.execute(f"COPY fila_publica TO '{pub_sql}' (HEADER, DELIMITER ',');")
con.close()

print(f"[FILA PRIVADA] {priv_cnt[0]:,} empresas/grupos unicos (cobrindo {int(priv_cnt[1]):,} obras pendentes) -> {OUT_PRIV}")
print(f"[FILA PUBLICA PNCP] {pub_cnt:,} editais pendentes -> {OUT_PUB}")
