import os
import duckdb

BASE_DIR = r"C:\Users\kbadmin\Documents\Projetos\01_Ecossistema_WiNS\Engenharia"
MAIN_DB = os.path.join(BASE_DIR, "Banco_Dados", "wins_engenharia.duckdb")
SUB_DB = os.path.join(BASE_DIR, "Banco_Dados", "obras_civil_industrial_2026_2027_100k.duckdb")
OUT_CSV = os.path.join(BASE_DIR, "Arquivos_Tratados", "obras_brasil_civil_industrial_100k.csv")

con = duckdb.connect(MAIN_DB)

con.execute("""
CREATE OR REPLACE TABLE obras_brasil_civil_industrial_100k AS
SELECT
    o.obra_id,
    o.obra_nome,
    o.obra_empresa,
    o.obra_cnpj,
    o.obra_cnpj_raiz,
    o.obra_setor,
    CASE
        WHEN o.obra_setor IN ('INFRAESTRUTURA', 'SANEAMENTO', 'HOSPITALAR', 'LOGISTICA', 'PORTUARIO', 'ENERGIA') THEN 'CIVIL'
        WHEN o.obra_setor IN ('INDUSTRIAL', 'AUTOMOTIVO', 'ALIMENTOS_E_BEBIDAS', 'PAPEL_E_CELULOSE', 'SIDERURGIA', 'QUIMICA', 'PETROLEO_GAS', 'MINERACAO', 'DATA_CENTER') THEN 'INDUSTRIAL'
    END AS categoria_macro,
    o.obra_uf,
    o.obra_municipio,
    o.obra_classificacao,
    o.obra_capex_analitico,
    CASE
        WHEN o.obra_nome LIKE '%2027%' THEN '2026/2027'
        ELSE '2026'
    END AS ano_referencia,
    o.total_decisores,
    o.decisores_acionaveis,
    CASE WHEN f.cnpj IS NOT NULL THEN TRUE ELSE FALSE END AS tem_match_fornecedor
FROM obras o
LEFT JOIN fornecedores f ON o.obra_cnpj = f.cnpj
WHERE o.obra_uf IS NOT NULL
  AND o.obra_capex_analitico > 100000
  AND o.obra_setor IN (
      'INFRAESTRUTURA', 'SANEAMENTO', 'HOSPITALAR', 'LOGISTICA', 'PORTUARIO', 'ENERGIA',
      'INDUSTRIAL', 'AUTOMOTIVO', 'ALIMENTOS_E_BEBIDAS', 'PAPEL_E_CELULOSE',
      'SIDERURGIA', 'QUIMICA', 'PETROLEO_GAS', 'MINERACAO', 'DATA_CENTER'
  );
""")

cnt = con.execute("SELECT COUNT(*) FROM obras_brasil_civil_industrial_100k").fetchone()[0]
breakdown = con.execute("""
SELECT categoria_macro, COUNT(*) AS qtd, ROUND(SUM(obra_capex_analitico)/1e9, 2) AS capex_bi, SUM(decisores_acionaveis) AS decisores_acionaveis
FROM obras_brasil_civil_industrial_100k
GROUP BY 1
ORDER BY 2 DESC
""").fetchdf()

out_csv_sql = OUT_CSV.replace("\\", "/")
con.execute(f"COPY obras_brasil_civil_industrial_100k TO '{out_csv_sql}' (HEADER, DELIMITER ',');")
con.close()

# Criar tambem um DuckDB dedicado leve apenas com esse recorte + decisores filtrados
if os.path.exists(SUB_DB):
    os.remove(SUB_DB)

sub = duckdb.connect(SUB_DB)
main_db_sql = MAIN_DB.replace("\\", "/")
sub.execute(f"ATTACH '{main_db_sql}' AS src (READ_ONLY);")
sub.execute("CREATE TABLE obras_filtradas AS SELECT * FROM src.obras_brasil_civil_industrial_100k;")
sub.execute("""
CREATE TABLE decisores_filtrados AS
SELECT d.*
FROM src.decisores d
JOIN obras_filtradas o ON d.obra_id = o.obra_id;
""")
sub.execute("DETACH src;")
sub.execute("CREATE INDEX idx_of_uf_cat ON obras_filtradas(obra_uf, categoria_macro);")
sub.execute("CREATE INDEX idx_df_obra ON decisores_filtrados(obra_id);")
dec_cnt = sub.execute("SELECT COUNT(*) FROM decisores_filtrados").fetchone()[0]
sub.close()

print(f"Total obras_brasil_civil_industrial_100k: {cnt:,}")
print(f"Total decisores_filtrados: {dec_cnt:,}")
print(breakdown.to_string(index=False))
print(f"DB dedicado: {SUB_DB} ({os.path.getsize(SUB_DB)/(1024*1024):.1f} MB)")
print(f"CSV exportado: {OUT_CSV} ({os.path.getsize(OUT_CSV)/(1024*1024):.1f} MB)")
