import os
import duckdb

BASE_DIR = r"C:\Users\kbadmin\Documents\Projetos\01_Ecossistema_WiNS\Engenharia"
MAIN_DB = os.path.join(BASE_DIR, "Banco_Dados", "wins_engenharia.duckdb")
SUB_DB = os.path.join(BASE_DIR, "Banco_Dados", "obras_civil_industrial_2026_2027_100k.duckdb")
OUT_CSV = os.path.join(BASE_DIR, "Arquivos_Tratados", "obras_novas_com_decisores.csv")

con = duckdb.connect(MAIN_DB)

con.execute("""
CREATE OR REPLACE TABLE validacao_decisores_obras_novas AS
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
FROM validacao_decisores_obras_novas;
""")

resumo_perfil = con.execute("""
SELECT
    perfil_decisor,
    COUNT(*) AS vinculos,
    COUNT(DISTINCT id_externo) AS obras_distintas,
    SUM(CASE WHEN is_contato_acionavel THEN 1 ELSE 0 END) AS vinculos_acionaveis
FROM validacao_decisores_obras_novas
GROUP BY 1
ORDER BY 1;
""").fetchdf()

resumo_real = con.execute("""
SELECT
    COUNT(DISTINCT id_externo) FILTER (WHERE perfil_decisor IN ('1_COMPRADOR_SUPRIMENTOS', '2_GESTOR_TECNICO_OBRA', '3_DIRETORIA_EXECUTIVA')) AS obras_com_decisor_operacional,
    COUNT(DISTINCT id_externo) FILTER (WHERE perfil_decisor IN ('1_COMPRADOR_SUPRIMENTOS', '2_GESTOR_TECNICO_OBRA')) AS obras_com_comprador_ou_tecnico,
    COUNT(DISTINCT id_externo) FILTER (WHERE perfil_decisor = '1_COMPRADOR_SUPRIMENTOS') AS obras_com_suprimentos_compras,
    COUNT(DISTINCT id_externo) FILTER (WHERE perfil_decisor = '2_GESTOR_TECNICO_OBRA') AS obras_com_engenharia_projetos
FROM validacao_decisores_obras_novas;
""").fetchdf()

out_sql = OUT_CSV.replace("\\", "/")
con.execute(f"COPY validacao_decisores_obras_novas TO '{out_sql}' (HEADER, DELIMITER ',');")
con.execute("ANALYZE;")
con.execute("CHECKPOINT;")
con.close()

sub = duckdb.connect(SUB_DB)
main_sql = MAIN_DB.replace("\\", "/")
sub.execute(f"ATTACH '{main_sql}' AS main_db (READ_ONLY);")
sub.execute("CREATE OR REPLACE TABLE decisores_obras_novas AS SELECT * FROM main_db.validacao_decisores_obras_novas;")
sub.execute("DETACH main_db;")
sub.execute("CHECKPOINT;")
sub.close()

print("=== DISTRIBUICAO POR PERFIL DE PODER DE COMPRA ===")
print(resumo_perfil.to_string(index=False))
print("\n=== COBERTURA REAL DE QUEM CONTRATA/ESPECIFICA (2.608 OBRAS) ===")
print(resumo_real.to_string(index=False))
