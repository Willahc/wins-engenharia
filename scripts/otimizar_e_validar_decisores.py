import os
import re
import unicodedata
import duckdb

BASE_DIR = r"C:\Users\kbadmin\Documents\Projetos\01_Ecossistema_WiNS\Engenharia"
MAIN_DB = os.path.join(BASE_DIR, "Banco_Dados", "wins_engenharia.duckdb")
SUB_DB = os.path.join(BASE_DIR, "Banco_Dados", "obras_civil_industrial_2026_2027_100k.duckdb")
OUT_MATCHES_CSV = os.path.join(BASE_DIR, "Arquivos_Tratados", "obras_novas_com_decisores.csv")


def norm_company(name: str) -> str:
    if not name:
        return ""
    s = "".join(c for c in unicodedata.normalize("NFKD", name.upper()) if not unicodedata.combining(c))
    s = re.sub(r"[^A-Z0-9\s]", " ", s)
    s = re.sub(r"\b(LTDA|S\.?A\.?|SA|EIRELI|ME|EPP|SPE|EMPREENDIMENTOS|ENERGIA|CONSTRUCOES|ENGENHARIA|DO|DA|DE|DOS|DAS|E)\b", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s if len(s) >= 5 else ""


con = duckdb.connect(MAIN_DB)
con.create_function("norm_company", norm_company, ["VARCHAR"], "VARCHAR")

sub_sql = SUB_DB.replace("\\", "/")
con.execute(f"ATTACH '{sub_sql}' AS sub_db (READ_ONLY);")

# 1. Integrar e otimizar tabela de obras novas no banco principal
con.execute("""
CREATE OR REPLACE TABLE obras_oficiais_ativas AS
SELECT
    id_externo,
    fonte,
    obra_nome,
    obra_empresa,
    norm_company(obra_empresa) AS obra_empresa_norm,
    obra_cnpj,
    SUBSTR(obra_cnpj, 1, 8) AS obra_cnpj_raiz,
    categoria_macro,
    obra_uf,
    obra_municipio,
    capex_estimado,
    CASE
        WHEN fonte = 'aneel_siga' THEN 'PROXY_POTENCIA_KW'
        ELSE 'FINANCEIRO_REAL'
    END AS capex_tipo,
    data_inicio_prevista,
    data_fim_prevista,
    situacao,
    url_origem,
    tem_match_fornecedor
FROM sub_db.obras_consolidadas_ativas;
""")
con.execute("DETACH sub_db;")

# Indices otimizados na tabela nova
con.execute("CREATE INDEX IF NOT EXISTS idx_ooa_cnpj ON obras_oficiais_ativas(obra_cnpj);")
con.execute("CREATE INDEX IF NOT EXISTS idx_ooa_raiz ON obras_oficiais_ativas(obra_cnpj_raiz);")
con.execute("CREATE INDEX IF NOT EXISTS idx_ooa_uf_cat ON obras_oficiais_ativas(obra_uf, categoria_macro);")
con.execute("CREATE INDEX IF NOT EXISTS idx_ooa_fonte ON obras_oficiais_ativas(fonte);")

# 2. Otimizar catalogo de decisores por empresa/CNPJ para match rapido
con.execute("""
CREATE OR REPLACE TABLE dim_decisores_empresa AS
SELECT
    d.decisor_id,
    d.nome,
    d.cargo,
    d.funcao_canonica,
    d.tipo_cargo,
    d.email,
    d.telefone,
    d.linkedin_url,
    d.qualidade_lead,
    d.confianca_score,
    d.is_contato_acionavel,
    o.obra_id AS obra_origem_id,
    o.obra_cnpj,
    o.obra_cnpj_raiz,
    o.obra_empresa,
    norm_company(o.obra_empresa) AS obra_empresa_norm
FROM decisores d
JOIN obras o ON d.obra_id = o.obra_id;
""")
con.execute("CREATE INDEX IF NOT EXISTS idx_dde_cnpj ON dim_decisores_empresa(obra_cnpj);")
con.execute("CREATE INDEX IF NOT EXISTS idx_dde_raiz ON dim_decisores_empresa(obra_cnpj_raiz);")
con.execute("CREATE INDEX IF NOT EXISTS idx_dde_emp ON dim_decisores_empresa(obra_empresa_norm);")

# 3. Validacao - Obras ANTIGAS (tabela obras)
antigas_stats = con.execute("""
SELECT
    COUNT(*) AS total_obras_antigas,
    SUM(CASE WHEN total_decisores > 0 THEN 1 ELSE 0 END) AS com_algum_decisor,
    SUM(CASE WHEN decisores_acionaveis > 0 THEN 1 ELSE 0 END) AS com_decisor_acionavel,
    SUM(total_decisores) AS total_vinculos_decisores,
    SUM(decisores_acionaveis) AS total_decisores_acionaveis
FROM obras;
""").fetchdf()

# 4. Validacao - Obras NOVAS (tabela obras_oficiais_ativas)
# Match por CNPJ exato (prioridade 1), CNPJ raiz (prioridade 2) ou nome empresa normalizado (prioridade 3)
con.execute("""
CREATE OR REPLACE TABLE validacao_decisores_obras_novas AS
WITH matches AS (
    SELECT
        n.id_externo,
        n.fonte,
        n.obra_nome,
        n.obra_empresa,
        n.obra_cnpj,
        n.categoria_macro,
        n.obra_uf,
        n.capex_estimado,
        n.capex_tipo,
        n.url_origem,
        CASE
            WHEN d.obra_cnpj IS NOT NULL AND n.obra_cnpj = d.obra_cnpj THEN '1_CNPJ_EXATO'
            WHEN d.obra_cnpj_raiz IS NOT NULL AND n.obra_cnpj_raiz = d.obra_cnpj_raiz THEN '2_CNPJ_RAIZ'
            WHEN d.obra_empresa_norm <> '' AND n.obra_empresa_norm = d.obra_empresa_norm THEN '3_EMPRESA_NOME'
        END AS tipo_match,
        d.decisor_id,
        d.nome AS decisor_nome,
        d.cargo AS decisor_cargo,
        d.email AS decisor_email,
        d.telefone AS decisor_telefone,
        d.linkedin_url AS decisor_linkedin,
        d.qualidade_lead,
        d.is_contato_acionavel
    FROM obras_oficiais_ativas n
    JOIN dim_decisores_empresa d
      ON (n.obra_cnpj IS NOT NULL AND n.obra_cnpj = d.obra_cnpj)
      OR (n.obra_cnpj_raiz IS NOT NULL AND n.obra_cnpj_raiz = d.obra_cnpj_raiz)
      OR (n.obra_empresa_norm <> '' AND n.obra_empresa_norm = d.obra_empresa_norm)
)
SELECT DISTINCT ON (id_externo, LOWER(TRIM(decisor_nome)), COALESCE(decisor_email, ''), COALESCE(decisor_linkedin, ''))
    *
FROM matches
ORDER BY id_externo, LOWER(TRIM(decisor_nome)), COALESCE(decisor_email, ''), COALESCE(decisor_linkedin, ''), tipo_match, is_contato_acionavel DESC;
""")

novas_resumo = con.execute("""
SELECT
    COUNT(*) AS total_obras_novas,
    COUNT(DISTINCT CASE WHEN m.id_externo IS NOT NULL THEN o.id_externo END) AS obras_novas_com_decisor,
    COUNT(DISTINCT CASE WHEN m.is_contato_acionavel THEN o.id_externo END) AS obras_novas_com_acionavel
FROM obras_oficiais_ativas o
LEFT JOIN validacao_decisores_obras_novas m ON o.id_externo = m.id_externo;
""").fetchdf()

novas_por_match = con.execute("""
SELECT
    tipo_match,
    fonte,
    COUNT(DISTINCT id_externo) AS obras_distintas,
    COUNT(*) AS decisores_unicos,
    SUM(CASE WHEN is_contato_acionavel THEN 1 ELSE 0 END) AS decisores_acionaveis
FROM validacao_decisores_obras_novas
GROUP BY 1, 2
ORDER BY 1, 3 DESC;
""").fetchdf()

amostra_matches = con.execute("""
SELECT fonte, obra_empresa, obra_cnpj, tipo_match, decisor_nome, decisor_cargo, is_contato_acionavel
FROM validacao_decisores_obras_novas
WHERE is_contato_acionavel = TRUE
LIMIT 10;
""").fetchdf()

out_sql = OUT_MATCHES_CSV.replace("\\", "/")
con.execute(f"COPY validacao_decisores_obras_novas TO '{out_sql}' (HEADER, DELIMITER ',');")

# Compactar/otimizar estatisticas do DuckDB
con.execute("ANALYZE;")
con.execute("CHECKPOINT;")
con.close()

# Atualizar tambem o banco leve com os decisores encontrados para obras novas
sub = duckdb.connect(SUB_DB)
main_sql = MAIN_DB.replace("\\", "/")
sub.execute(f"ATTACH '{main_sql}' AS main_db (READ_ONLY);")
sub.execute("CREATE OR REPLACE TABLE obras_consolidadas_ativas AS SELECT * FROM main_db.obras_oficiais_ativas;")
sub.execute("CREATE OR REPLACE TABLE decisores_obras_novas AS SELECT * FROM main_db.validacao_decisores_obras_novas;")
sub.execute("DETACH main_db;")
sub.execute("ANALYZE;")
sub.execute("CHECKPOINT;")
sub.close()

print("=== VALIDACAO OBRAS ANTIGAS (tabela obras) ===")
print(antigas_stats.to_string(index=False))
print("\n=== VALIDACAO OBRAS NOVAS (tabela obras_oficiais_ativas) ===")
print(novas_resumo.to_string(index=False))
print("\n=== DETALHAMENTO POR TIPO DE MATCH (obras novas) ===")
print(novas_por_match.to_string(index=False))
print("\n=== AMOSTRA DE DECISORES ACIONAVEIS NAS OBRAS NOVAS ===")
print(amostra_matches.to_string(index=False))
