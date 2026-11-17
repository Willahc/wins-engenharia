import os
import subprocess
import duckdb
import pandas as pd

BASE_DIR = r"C:\Users\kbadmin\Documents\Projetos\01_Ecossistema_WiNS\Engenharia"
MAIN_DB = os.path.join(BASE_DIR, "Banco_Dados", "wins_engenharia.duckdb")
OUT_XLSX = os.path.join(BASE_DIR, "Arquivos_Tratados", "WiNS_Prospeccao_Obras_2026_2027.xlsx")
OUT_CSV = os.path.join(BASE_DIR, "Arquivos_Tratados", "WiNS_Prospeccao_Obras_2026_2027.csv").replace("\\", "/")

con = duckdb.connect(MAIN_DB)

# 1. Atualizar todas_obras_consolidadas com whatsapp_oficial e telefones_site
con.execute("""
CREATE OR REPLACE TABLE todas_obras_consolidadas AS
SELECT
    t.* EXCLUDE (whatsapp_oficial, telefones_site),
    w.whatsapp_oficial,
    w.telefones_site
FROM todas_obras_consolidadas t
LEFT JOIN empresa_whatsapp_oficial w ON t.dominio_corporativo = w.dominio;
""") if "whatsapp_oficial" in [r[0] for r in con.execute("DESCRIBE todas_obras_consolidadas").fetchall()] else con.execute("""
CREATE OR REPLACE TABLE todas_obras_consolidadas AS
SELECT
    t.*,
    w.whatsapp_oficial,
    w.telefones_site
FROM todas_obras_consolidadas t
LEFT JOIN empresa_whatsapp_oficial w ON t.dominio_corporativo = w.dominio;
""")

# 2. Abas do Excel
df_resumo = con.execute("""
SELECT
    fonte,
    categoria_macro,
    COUNT(*) AS total_obras,
    SUM(CASE WHEN decisores_acionaveis > 0 THEN 1 ELSE 0 END) AS obras_acionaveis,
    SUM(CASE WHEN decisores_operacionais > 0 THEN 1 ELSE 0 END) AS obras_com_comprador_eng,
    SUM(CASE WHEN dominio_corporativo IS NOT NULL THEN 1 ELSE 0 END) AS obras_com_dominio,
    SUM(CASE WHEN whatsapp_oficial IS NOT NULL THEN 1 ELSE 0 END) AS obras_com_whatsapp_site,
    ROUND(SUM(capex_estimado)/1e6, 2) AS capex_total_mi
FROM todas_obras_consolidadas
GROUP BY 1, 2
ORDER BY 3 DESC;
""").fetchdf()

df_obras = con.execute("""
SELECT
    obra_id,
    fonte,
    categoria_macro,
    obra_uf,
    obra_municipio,
    obra_nome,
    obra_empresa,
    obra_cnpj,
    dominio_corporativo,
    whatsapp_oficial,
    telefones_site,
    capex_estimado,
    capex_tipo,
    data_inicio_prevista,
    data_fim_prevista,
    situacao,
    total_decisores,
    decisores_acionaveis,
    decisores_operacionais,
    tem_match_fornecedor,
    url_origem
FROM todas_obras_consolidadas
ORDER BY decisores_operacionais DESC, capex_estimado DESC;
""").fetchdf()

df_dec_operacional = con.execute("""
SELECT
    v.id_externo AS obra_id,
    v.fonte,
    v.categoria_macro,
    v.obra_uf,
    v.obra_nome,
    v.obra_empresa,
    v.obra_cnpj,
    t.dominio_corporativo,
    t.whatsapp_oficial AS whatsapp_oficial_empresa,
    v.capex_estimado,
    v.capex_tipo,
    v.perfil_decisor,
    v.decisor_nome,
    v.decisor_cargo,
    v.decisor_email,
    v.decisor_telefone,
    v.decisor_linkedin,
    v.tipo_match,
    v.url_origem
FROM validacao_decisores_obras_novas v
JOIN todas_obras_consolidadas t ON v.id_externo = t.obra_id
WHERE v.is_contato_acionavel = TRUE
  AND v.perfil_decisor IN ('1_COMPRADOR_SUPRIMENTOS', '2_GESTOR_TECNICO_OBRA', '3_DIRETORIA_EXECUTIVA')
ORDER BY v.perfil_decisor, v.capex_estimado DESC;
""").fetchdf()

df_dec_todos = con.execute("""
SELECT
    v.id_externo AS obra_id,
    v.fonte,
    v.categoria_macro,
    v.obra_uf,
    v.obra_nome,
    v.obra_empresa,
    v.obra_cnpj,
    t.dominio_corporativo,
    t.whatsapp_oficial AS whatsapp_oficial_empresa,
    v.capex_estimado,
    v.capex_tipo,
    v.perfil_decisor,
    v.decisor_nome,
    v.decisor_cargo,
    v.decisor_email,
    v.decisor_telefone,
    v.decisor_linkedin,
    v.tipo_match,
    v.url_origem
FROM validacao_decisores_obras_novas v
JOIN todas_obras_consolidadas t ON v.id_externo = t.obra_id
WHERE v.is_contato_acionavel = TRUE
ORDER BY v.perfil_decisor, v.capex_estimado DESC;
""").fetchdf()

# Salvar CSV de decisores operacionais acionaveis
df_dec_operacional.to_csv(OUT_CSV, index=False, encoding="utf-8-sig")

# Salvar Excel multi-aba
with pd.ExcelWriter(OUT_XLSX, engine="openpyxl") as writer:
    df_resumo.to_excel(writer, sheet_name="Resumo_Executivo", index=False)
    df_dec_operacional.to_excel(writer, sheet_name="Prioritarios_Compras_Eng", index=False)
    df_obras.to_excel(writer, sheet_name="Todas_Obras_2608", index=False)
    df_dec_todos.to_excel(writer, sheet_name="Todos_Decisores_Acionaveis", index=False)

con.execute("ANALYZE;")
con.execute("CHECKPOINT;")
con.close()

print(f"Excel gerado: {OUT_XLSX} ({os.path.getsize(OUT_XLSX)/(1024*1024):.2f} MB)")
print(f"  - Aba Prioritarios_Compras_Eng: {len(df_dec_operacional):,} linhas")
print(f"  - Aba Todas_Obras_2608: {len(df_obras):,} linhas")
print(f"  - Aba Todos_Decisores_Acionaveis: {len(df_dec_todos):,} linhas")
print(f"CSV prioritario gerado: {OUT_CSV}")
