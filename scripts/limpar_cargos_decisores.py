import os
import re
import subprocess
import duckdb
import pandas as pd

BASE_DIR = r"C:\Users\kbadmin\Documents\Projetos\01_Ecossistema_WiNS\Engenharia"
MAIN_DB = os.path.join(BASE_DIR, "Banco_Dados", "wins_engenharia.duckdb")
SUB_DB = os.path.join(BASE_DIR, "Banco_Dados", "obras_civil_industrial_2026_2027_100k.duckdb")
OUT_DEC_CSV = os.path.join(BASE_DIR, "Arquivos_Tratados", "obras_novas_com_decisores.csv").replace("\\", "/")
OUT_ANTISPAM_CSV = os.path.join(BASE_DIR, "Arquivos_Tratados", "WiNS_Prospeccao_Por_Decisor_Unico.csv")
OUT_XLSX = os.path.join(BASE_DIR, "Arquivos_Tratados", "WiNS_Prospeccao_Obras_2026_2027.xlsx")


def clean_cargo(raw: str) -> str:
    if not raw:
        return ""
    s = raw.strip()
    # Remove " @ Empresa..." ou "@ Empresa" no inicio
    s = re.sub(r"\s*@.*$", "", s).strip()
    # Remove sufixo " - LinkedIn" ou "| LinkedIn"
    s = re.sub(r"\s*[-|]\s*LinkedIn\s*$", "", s, flags=re.I).strip()
    # Remove separadores soltos no fim
    s = s.strip(" -|/,;:")
    return s


con = duckdb.connect(MAIN_DB)
con.create_function("clean_cargo", clean_cargo, ["VARCHAR"], "VARCHAR")

b_novas = con.execute("SELECT COUNT(*) FROM validacao_decisores_obras_novas WHERE decisor_cargo LIKE '%@%'").fetchone()[0]
b_hist = con.execute("SELECT COUNT(*) FROM decisores WHERE cargo LIKE '%@%'").fetchone()[0]

con.execute("UPDATE decisores SET cargo = NULLIF(clean_cargo(cargo), '') WHERE cargo IS NOT NULL;")
con.execute("UPDATE dim_decisores_empresa SET cargo = NULLIF(clean_cargo(cargo), '') WHERE cargo IS NOT NULL;")
con.execute("UPDATE validacao_decisores_obras_novas SET decisor_cargo = NULLIF(clean_cargo(decisor_cargo), '') WHERE decisor_cargo IS NOT NULL;")
con.execute("UPDATE campanha_por_decisor_unico SET decisor_cargo = NULLIF(clean_cargo(decisor_cargo), '') WHERE decisor_cargo IS NOT NULL;")

a_novas = con.execute("SELECT COUNT(*) FROM validacao_decisores_obras_novas WHERE decisor_cargo LIKE '%@%'").fetchone()[0]
a_hist = con.execute("SELECT COUNT(*) FROM decisores WHERE cargo LIKE '%@%'").fetchone()[0]

con.execute(f"COPY validacao_decisores_obras_novas TO '{OUT_DEC_CSV}' (HEADER, DELIMITER ',');")

df_antispam = con.execute("SELECT * FROM campanha_por_decisor_unico").fetchdf()
df_antispam.to_csv(OUT_ANTISPAM_CSV, index=False, encoding="utf-8-sig")

df_resumo = con.execute("""
SELECT
    fonte,
    categoria_macro,
    COUNT(*) AS total_obras,
    SUM(CASE WHEN decisores_acionaveis > 0 THEN 1 ELSE 0 END) AS obras_acionaveis,
    SUM(CASE WHEN decisores_operacionais > 0 THEN 1 ELSE 0 END) AS obras_com_comprador_eng,
    SUM(CASE WHEN mx_ativo THEN 1 ELSE 0 END) AS obras_dominio_mx_ativo,
    SUM(CASE WHEN whatsapp_oficial IS NOT NULL THEN 1 ELSE 0 END) AS obras_com_whatsapp_site,
    ROUND(SUM(capex_estimado)/1e6, 2) AS capex_total_mi
FROM todas_obras_consolidadas
GROUP BY 1, 2
ORDER BY 3 DESC;
""").fetchdf()
df_obras = con.execute("SELECT * FROM todas_obras_consolidadas ORDER BY decisores_operacionais DESC, capex_estimado DESC;").fetchdf()
df_dec_op = con.execute("""
SELECT * FROM campanha_por_decisor_unico
WHERE perfil_prioritario IN ('1_COMPRADOR_SUPRIMENTOS', '2_GESTOR_TECNICO_OBRA', '3_DIRETORIA_EXECUTIVA')
""").fetchdf()

with pd.ExcelWriter(OUT_XLSX, engine="openpyxl") as writer:
    df_resumo.to_excel(writer, sheet_name="Resumo_Executivo", index=False)
    df_dec_op.to_excel(writer, sheet_name="Decisores_Unicos_AntiSpam", index=False)
    df_obras.to_excel(writer, sheet_name="Todas_Obras_Validadas", index=False)
    df_antispam.to_excel(writer, sheet_name="Todos_Decisores_Unicos", index=False)

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

print(f"Cargos com '@' limpos - Obras novas: {b_novas:,} -> {a_novas:,} | Historico: {b_hist:,} -> {a_hist:,}")

subprocess.run(["python", os.path.join(BASE_DIR, "scripts", "gerar_dashboard_html.py")], check=True)
