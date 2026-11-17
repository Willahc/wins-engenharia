import os
import duckdb

BASE_DIR = r"C:\Users\kbadmin\Documents\Projetos\01_Ecossistema_WiNS\Engenharia"
TRATADOS_DIR = os.path.join(BASE_DIR, "Arquivos_Tratados")
DB_DIR = os.path.join(BASE_DIR, "Banco_Dados")
os.makedirs(DB_DIR, exist_ok=True)
DB_PATH = os.path.join(DB_DIR, "wins_engenharia.duckdb")

if os.path.exists(DB_PATH):
    os.remove(DB_PATH)

con = duckdb.connect(DB_PATH)

fontes_csv = os.path.join(TRATADOS_DIR, "fontes_obras_tratado.csv").replace("\\", "/")
decisores_csv = os.path.join(TRATADOS_DIR, "wins_eng_comercial_decisores_tratado.csv").replace("\\", "/")
fornecedores_csv = os.path.join(TRATADOS_DIR, "wins_eng_fornecedores_tratado.csv").replace("\\", "/")

# 1. Tabela fontes_obras
con.execute(f"""
CREATE TABLE fontes_obras AS
SELECT
    fonte,
    tipo,
    CAST(obras AS BIGINT) AS obras,
    CAST(com_url AS BIGINT) AS com_url,
    CAST(pct_com_url AS DOUBLE) AS pct_com_url,
    CAST(via_captador_novo AS BIGINT) AS via_captador_novo,
    CAST(capex_bi AS DOUBLE) AS capex_bi,
    CAST(capex_medio_obra_mi AS DOUBLE) AS capex_medio_obra_mi,
    (flag_capex_outlier = 't') AS flag_capex_outlier,
    TRY_CAST(NULLIF(primeira_publicacao, '') AS DATE) AS primeira_publicacao,
    TRY_CAST(NULLIF(ultima_publicacao, '') AS DATE) AS ultima_publicacao,
    CAST(linhas_consolidadas AS INTEGER) AS linhas_consolidadas
FROM read_csv('{fontes_csv}', header=true, all_varchar=true, ignore_errors=false);
""")

# 2. Staging de decisores para normalizar obras vs decisores
con.execute(f"""
CREATE TEMP TABLE stg_decisores AS
SELECT * FROM read_csv('{decisores_csv}', header=true, all_varchar=true, ignore_errors=false);
""")

# 2a. Tabela obras (normalizada por obra_id)
con.execute("""
CREATE TABLE obras AS
SELECT
    obra_id,
    ANY_VALUE(NULLIF(obra_nome, '')) AS obra_nome,
    ANY_VALUE(NULLIF(obra_empresa, '')) AS obra_empresa,
    ANY_VALUE(NULLIF(obra_cnpj, '')) AS obra_cnpj,
    SUBSTR(ANY_VALUE(NULLIF(obra_cnpj, '')), 1, 8) AS obra_cnpj_raiz,
    ANY_VALUE(NULLIF(obra_setor, '')) AS obra_setor,
    ANY_VALUE(NULLIF(obra_uf, '')) AS obra_uf,
    ANY_VALUE(NULLIF(obra_municipio, '')) AS obra_municipio,
    ANY_VALUE(NULLIF(obra_classificacao, '')) AS obra_classificacao,
    MAX(TRY_CAST(NULLIF(obra_capex_analitico, '') AS DOUBLE)) AS obra_capex_analitico,
    COUNT(*) AS total_decisores,
    SUM(CASE WHEN is_contato_acionavel = 't' THEN 1 ELSE 0 END) AS decisores_acionaveis
FROM stg_decisores
GROUP BY obra_id;
""")

# 2b. Tabela decisores (sem duplicar atributos da obra)
con.execute("""
CREATE TABLE decisores AS
SELECT
    decisor_id,
    obra_id,
    NULLIF(nome, '') AS nome,
    NULLIF(cargo, '') AS cargo,
    NULLIF(funcao_canonica, '') AS funcao_canonica,
    NULLIF(tipo_cargo, '') AS tipo_cargo,
    NULLIF(email, '') AS email,
    NULLIF(email_classificacao, '') AS email_classificacao,
    NULLIF(email_status, '') AS email_status,
    CASE email_corporativo_validado WHEN 't' THEN TRUE WHEN 'f' THEN FALSE ELSE NULL END AS email_corporativo_validado,
    NULLIF(email_smtp_status, '') AS email_smtp_status,
    NULLIF(telefone, '') AS telefone,
    NULLIF(telefone_classificacao, '') AS telefone_classificacao,
    NULLIF(whatsapp_status, '') AS whatsapp_status,
    NULLIF(linkedin_url, '') AS linkedin_url,
    (tem_linkedin = 't') AS tem_linkedin,
    NULLIF(fonte, '') AS fonte,
    NULLIF(tipo_evidencia, '') AS tipo_evidencia,
    NULLIF(fonte_evidencia, '') AS fonte_evidencia,
    TRY_CAST(NULLIF(confianca_score, '') AS DOUBLE) AS confianca_score,
    NULLIF(status_qualidade, '') AS status_qualidade,
    NULLIF(qualidade_lead, '') AS qualidade_lead,
    NULLIF(status_vinculo_obra, '') AS status_vinculo_obra,
    NULLIF(classificacao_compatibilidade, '') AS classificacao_compatibilidade,
    NULLIF(base_legal_lgpd, '') AS base_legal_lgpd,
    TRY_CAST(NULLIF(registrado_em, '') AS TIMESTAMPTZ) AS registrado_em,
    TRY_CAST(NULLIF(verificado_em, '') AS TIMESTAMPTZ) AS verificado_em,
    (is_contato_acionavel = 't') AS is_contato_acionavel
FROM stg_decisores;
""")

con.execute("DROP TABLE stg_decisores;")

# 3. Tabela fornecedores (4.09M linhas)
con.execute(f"""
CREATE TABLE fornecedores AS
SELECT
    cnpj,
    cnpj_raiz,
    NULLIF(razao_social, '') AS razao_social,
    NULLIF(nome_fantasia, '') AS nome_fantasia,
    cnae_principal,
    NULLIF(cnae_descricao, '') AS cnae_descricao,
    NULLIF(divisao_cnae, '') AS divisao_cnae,
    NULLIF(cnae_secundarios, '') AS cnae_secundarios,
    NULLIF(cnae_fiscal_secundaria, '') AS cnae_fiscal_secundaria,
    NULLIF(setor, '') AS setor_original,
    setor_consolidado,
    NULLIF(situacao, '') AS situacao,
    NULLIF(situacao_cadastral, '') AS situacao_cadastral,
    TRY_CAST(NULLIF(data_situacao_cadastral, '') AS DATE) AS data_situacao_cadastral,
    TRY_CAST(NULLIF(data_abertura, '') AS DATE) AS data_abertura,
    TRY_CAST(NULLIF(anos_ativos, '') AS INTEGER) AS anos_ativos,
    NULLIF(porte, '') AS porte,
    NULLIF(porte_descricao, '') AS porte_descricao,
    NULLIF(porte_inferido, '') AS porte_inferido,
    NULLIF(porte_consolidado, '') AS porte_consolidado,
    TRY_CAST(NULLIF(capital_social, '') AS DOUBLE) AS capital_social,
    NULLIF(tipo_estabelecimento, '') AS tipo_estabelecimento,
    NULLIF(logradouro, '') AS logradouro,
    NULLIF(numero, '') AS numero,
    NULLIF(complemento, '') AS complemento,
    NULLIF(bairro, '') AS bairro,
    NULLIF(cep, '') AS cep,
    NULLIF(municipio_nome, '') AS municipio_nome,
    NULLIF(municipio_ibge, '') AS municipio_ibge,
    uf,
    NULLIF(telefone_1, '') AS telefone_1,
    NULLIF(telefone_2, '') AS telefone_2,
    NULLIF(email, '') AS email,
    TRY_CAST(NULLIF(matches_count, '') AS INTEGER) AS matches_count,
    (cadastrado = 't') AS cadastrado,
    TRY_CAST(NULLIF(atualizado_em, '') AS TIMESTAMPTZ) AS atualizado_em,
    (is_contato_acionavel = 't') AS is_contato_acionavel
FROM read_csv('{fornecedores_csv}', header=true, all_varchar=true, ignore_errors=false);
""")

# 4. Indices para performance em joins e filtros
con.execute("CREATE INDEX idx_obras_cnpj ON obras(obra_cnpj);")
con.execute("CREATE INDEX idx_obras_uf_setor ON obras(obra_uf, obra_setor);")
con.execute("CREATE INDEX idx_decisores_obra_id ON decisores(obra_id);")
con.execute("CREATE INDEX idx_decisores_acionavel ON decisores(is_contato_acionavel, qualidade_lead);")
con.execute("CREATE INDEX idx_forn_cnpj ON fornecedores(cnpj);")
con.execute("CREATE INDEX idx_forn_raiz ON fornecedores(cnpj_raiz);")
con.execute("CREATE INDEX idx_forn_uf_setor ON fornecedores(uf, setor_consolidado);")
con.execute("CREATE INDEX idx_forn_cnae ON fornecedores(cnae_principal);")

# 5. Views analiticas prontas
con.execute("""
CREATE VIEW vw_decisores_completos AS
SELECT
    d.*,
    o.obra_nome,
    o.obra_empresa,
    o.obra_cnpj,
    o.obra_setor,
    o.obra_uf,
    o.obra_municipio,
    o.obra_classificacao,
    o.obra_capex_analitico
FROM decisores d
JOIN obras o ON d.obra_id = o.obra_id;
""")

con.execute("""
CREATE VIEW vw_decisores_acionaveis AS
SELECT * FROM vw_decisores_completos
WHERE is_contato_acionavel = TRUE;
""")

con.execute("""
CREATE VIEW vw_obras_com_fornecedores AS
SELECT
    o.obra_id,
    o.obra_nome,
    o.obra_empresa,
    o.obra_cnpj,
    o.obra_setor,
    o.obra_uf,
    o.obra_capex_analitico,
    o.total_decisores,
    o.decisores_acionaveis,
    f.razao_social AS fornecedor_razao_social,
    f.cnae_principal,
    f.setor_consolidado AS fornecedor_setor,
    f.porte_consolidado AS fornecedor_porte,
    f.uf AS fornecedor_uf,
    f.telefone_1 AS fornecedor_telefone,
    f.email AS fornecedor_email
FROM obras o
JOIN fornecedores f ON o.obra_cnpj = f.cnpj;
""")

# Verificacao final
for tbl in ["fontes_obras", "obras", "decisores", "fornecedores"]:
    cnt = con.execute(f"SELECT COUNT(*) FROM {tbl}").fetchone()[0]
    print(f"Tabela {tbl:15s}: {cnt:>10,} registros")

vw_match = con.execute("SELECT COUNT(*) FROM vw_obras_com_fornecedores").fetchone()[0]
print(f"View vw_obras_com_fornecedores: {vw_match:,} obras com match exato de CNPJ em fornecedores")

con.close()
size_mb = os.path.getsize(DB_PATH) / (1024 * 1024)
print(f"Banco criado com sucesso em: {DB_PATH} ({size_mb:.1f} MB)")
