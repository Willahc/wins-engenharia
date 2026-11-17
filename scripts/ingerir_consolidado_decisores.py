import os
import re
import subprocess
import unicodedata
import duckdb

BASE_DIR = r"C:\Users\kbadmin\Documents\Projetos\01_Ecossistema_WiNS\Engenharia"
MAIN_DB = os.path.join(BASE_DIR, "Banco_Dados", "wins_engenharia.duckdb")
SUB_DB = os.path.join(BASE_DIR, "Banco_Dados", "obras_civil_industrial_2026_2027_100k.duckdb")
EMP_CSV = os.path.join(BASE_DIR, "Arquivos", "base_decisores_por_empresa_2026-11-16.csv").replace("\\", "/")
PES_CSV = os.path.join(BASE_DIR, "Arquivos", "base_decisores_por_pessoa_2026-11-16.csv").replace("\\", "/")
OUT_CSV = os.path.join(BASE_DIR, "Arquivos_Tratados", "obras_novas_com_decisores.csv").replace("\\", "/")

GENERIC_PREFIXES = {
    "contato", "comercial", "vendas", "atendimento", "sac", "suporte", "info",
    "adm", "administrativo", "administracao", "financeiro", "faturamento",
    "fiscal", "contabil", "contabilidade", "rh", "dp", "recrutamento",
    "compras", "suprimentos", "licitacao", "licitacoes", "engenharia",
    "projetos", "obras", "orcamento", "orcamentos", "noreply", "no-reply",
    "naoresponda", "secretaria", "diretoria", "gerencia", "recepcao",
    "faleconosco", "ouvidoria", "juridico", "marketing", "ti", "geral"
}


def norm_razao(name: str) -> str:
    if not name:
        return ""
    s = "".join(c for c in unicodedata.normalize("NFKD", name.upper()) if not unicodedata.combining(c))
    s = re.sub(r"[^A-Z0-9\s]", " ", s)
    s = re.sub(r"\b(LTDA|S\.?A\.?|SA|EIRELI|ME|EPP)\b", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def clean_email(raw: str) -> str:
    em = (raw or "").strip().lower()
    if not em or "@" not in em or " " in em:
        return ""
    pref = em.split("@", 1)[0]
    pref_base = re.split(r"[._\-+]", pref)[0]
    if pref in GENERIC_PREFIXES or pref_base in GENERIC_PREFIXES:
        return ""
    return em


def clean_phone(raw: str) -> str:
    d = re.sub(r"\D", "", raw or "")
    if d.startswith("55") and len(d) in (12, 13):
        d = d[2:]
    if len(d) in (10, 11) and len(set(d)) > 2:
        return d
    return ""


con = duckdb.connect(MAIN_DB)
con.create_function("norm_razao", norm_razao, ["VARCHAR"], "VARCHAR")
con.create_function("clean_email", clean_email, ["VARCHAR"], "VARCHAR")
con.create_function("clean_phone", clean_phone, ["VARCHAR"], "VARCHAR")

# 1. Carregar tabelas consolidadas oficiais no DuckDB
con.execute(f"""
CREATE OR REPLACE TABLE decisores_por_empresa_consolidado AS
SELECT * FROM read_csv('{EMP_CSV}', delim=';', header=true, all_varchar=true);
""")
con.execute(f"""
CREATE OR REPLACE TABLE decisores_por_pessoa_consolidado AS
SELECT * FROM read_csv('{PES_CSV}', delim=';', header=true, all_varchar=true);
""")

# 2. Inserir os vinculos novos/faltantes em dim_decisores_empresa (filtrando generic email e linkedin invalido/errado)
before_dim = con.execute("SELECT COUNT(*) FROM dim_decisores_empresa").fetchone()[0]

con.execute("""
INSERT INTO dim_decisores_empresa
SELECT
    'CONS-' || e.decisor_key AS decisor_id,
    TRIM(e.decisor_nome) AS nome,
    NULLIF(TRIM(e.decisor_cargo), '') AS cargo,
    NULLIF(TRIM(e.funcao_canonica), '') AS funcao_canonica,
    NULLIF(TRIM(e.tipo_cargo), '') AS tipo_cargo,
    NULLIF(clean_email(e.email), '') AS email,
    NULLIF(clean_phone(e.telefone), '') AS telefone,
    CASE
        WHEN e.linkedin_valido = 'sim' AND COALESCE(e.linkedin_confere_nome, 'sim') <> 'nao'
            THEN NULLIF(TRIM(e.linkedin_url), '')
        ELSE NULL
    END AS linkedin_url,
    NULLIF(TRIM(e.qualidade_lead), '') AS qualidade_lead,
    TRY_CAST(e.confianca_score_max AS DOUBLE) AS confianca_score,
    (
        NULLIF(clean_email(e.email), '') IS NOT NULL
        OR NULLIF(clean_phone(e.telefone), '') IS NOT NULL
        OR (e.linkedin_valido = 'sim' AND COALESCE(e.linkedin_confere_nome, 'sim') <> 'nao' AND NULLIF(TRIM(e.linkedin_url), '') IS NOT NULL)
    ) AS is_contato_acionavel,
    'CONSOLIDADO_2026_11_16' AS obra_origem_id,
    NULLIF(REGEXP_REPLACE(COALESCE(e.cnpj, ''), '[^0-9]', '', 'g'), '') AS obra_cnpj,
    SUBSTR(NULLIF(REGEXP_REPLACE(COALESCE(e.cnpj, ''), '[^0-9]', '', 'g'), ''), 1, 8) AS obra_cnpj_raiz,
    NULLIF(TRIM(e.empresa), '') AS obra_empresa,
    norm_razao(e.empresa) AS obra_empresa_norm
FROM decisores_por_empresa_consolidado e
WHERE NOT EXISTS (
    SELECT 1 FROM dim_decisores_empresa d
    WHERE COALESCE(d.obra_cnpj, '') = COALESCE(NULLIF(REGEXP_REPLACE(COALESCE(e.cnpj, ''), '[^0-9]', '', 'g'), ''), '')
      AND LOWER(TRIM(d.nome)) = LOWER(TRIM(e.decisor_nome))
);
""")

after_dim = con.execute("SELECT COUNT(*) FROM dim_decisores_empresa").fetchone()[0]

# 3. Re-cruzar dim_decisores_empresa com obras_oficiais_ativas mantendo tambem os 4_QSA_BRASILAPI
con.execute("""
CREATE OR REPLACE TEMP TABLE qsa_existentes AS
SELECT * EXCLUDE (perfil_decisor)
FROM validacao_decisores_obras_novas
WHERE tipo_match = '4_QSA_BRASILAPI';
""")

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
    UNION ALL
    SELECT * FROM qsa_existentes
),
dedup AS (
    SELECT DISTINCT ON (id_externo, LOWER(TRIM(decisor_nome)), COALESCE(decisor_email, ''), COALESCE(decisor_linkedin, ''))
        *
    FROM matches
    ORDER BY id_externo, LOWER(TRIM(decisor_nome)), COALESCE(decisor_email, ''), COALESCE(decisor_linkedin, ''), tipo_match, is_contato_acionavel DESC
)
SELECT
    *,
    CASE
        WHEN REGEXP_MATCHES(COALESCE(decisor_cargo, ''), '(?i)(compra|suprimento|procurement|sourcing|supply\\s*chain|licitac|pregoeir|aquisic|contrato)')
            THEN '1_COMPRADOR_SUPRIMENTOS'
        WHEN REGEXP_MATCHES(COALESCE(decisor_cargo, ''), '(?i)(engenheir|engenharia|projeto|obra|capex|implantac|manutenc|operac|industrial|construc|infraestrutura|tecnic|meio\\s*ambiente)')
            THEN '2_GESTOR_TECNICO_OBRA'
        WHEN REGEXP_MATCHES(COALESCE(decisor_cargo, ''), '(?i)(diretor|presidente|ceo|cfo|coo|vp|vice[- ]presidente|superintendente|head|gerente\\s*geral)')
            THEN '3_DIRETORIA_EXECUTIVA'
        WHEN tipo_match = '4_QSA_BRASILAPI'
          OR REGEXP_MATCHES(COALESCE(decisor_cargo, ''), '(?i)(s[oó]cio|administrador|procurador|representante\\s*legal|titular)')
            THEN '4_SOCIO_QSA'
        ELSE '5_OUTRO_NAO_CLASSIFICADO'
    END AS perfil_decisor
FROM dedup;
""")

resumo = con.execute("""
SELECT
    COUNT(DISTINCT o.id_externo) AS total_obras_novas,
    COUNT(DISTINCT m.id_externo) AS obras_com_decisor,
    COUNT(DISTINCT CASE WHEN m.is_contato_acionavel THEN o.id_externo END) AS obras_com_acionavel,
    COUNT(DISTINCT CASE WHEN m.perfil_decisor IN ('1_COMPRADOR_SUPRIMENTOS','2_GESTOR_TECNICO_OBRA','3_DIRETORIA_EXECUTIVA') THEN o.id_externo END) AS obras_com_operacional,
    COUNT(*) FILTER (WHERE m.id_externo IS NOT NULL) AS total_vinculos,
    COUNT(*) FILTER (WHERE m.is_contato_acionavel) AS vinculos_acionaveis
FROM obras_oficiais_ativas o
LEFT JOIN validacao_decisores_obras_novas m ON o.id_externo = m.id_externo;
""").fetchdf()

con.execute(f"COPY validacao_decisores_obras_novas TO '{OUT_CSV}' (HEADER, DELIMITER ',');")
con.execute("ANALYZE;")
con.execute("CHECKPOINT;")
con.close()

# Atualizar banco leve
sub = duckdb.connect(SUB_DB)
main_sql = MAIN_DB.replace("\\", "/")
sub.execute(f"ATTACH '{main_sql}' AS main_db (READ_ONLY);")
sub.execute("CREATE OR REPLACE TABLE decisores_obras_novas AS SELECT * FROM main_db.validacao_decisores_obras_novas;")
sub.execute("DETACH main_db;")
sub.execute("CHECKPOINT;")
sub.close()

print(f"dim_decisores_empresa: {before_dim:,} -> {after_dim:,} (+{after_dim - before_dim:,} novos vinculos)")
print("=== RESUMO OBRAS NOVAS APOS INGESTAO ===")
print(resumo.to_string(index=False))

# Atualizar filas do OpenBot e Dashboard HTML
subprocess.run(["python", os.path.join(BASE_DIR, "scripts", "gerar_fila_openbot.py")], check=True)
subprocess.run(["python", os.path.join(BASE_DIR, "scripts", "gerar_dashboard_html.py")], check=True)
