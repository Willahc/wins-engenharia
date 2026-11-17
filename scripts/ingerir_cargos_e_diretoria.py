import csv
import os
import re
import subprocess
import duckdb
import pandas as pd

BASE_DIR = r"C:\Users\kbadmin\Documents\Projetos\01_Ecossistema_WiNS\Engenharia"
MAIN_DB = os.path.join(BASE_DIR, "Banco_Dados", "wins_engenharia.duckdb")
SUB_DB = os.path.join(BASE_DIR, "Banco_Dados", "obras_civil_industrial_2026_2027_100k.duckdb")
RET_CE = os.path.join(BASE_DIR, "Arquivos_Tratados", "retorno_openbot_compras_eng.csv")
RET_DL = os.path.join(BASE_DIR, "Arquivos_Tratados", "retorno_openbot_linkedin_diretoria.csv")
OUT_ALL_CSV = os.path.join(BASE_DIR, "Arquivos_Tratados", "obras_ativas_fontes_validadas.csv").replace("\\", "/")
OUT_DEC_CSV = os.path.join(BASE_DIR, "Arquivos_Tratados", "obras_novas_com_decisores.csv").replace("\\", "/")
OUT_ANTISPAM_CSV = os.path.join(BASE_DIR, "Arquivos_Tratados", "WiNS_Prospeccao_Por_Decisor_Unico.csv")
OUT_XLSX = os.path.join(BASE_DIR, "Arquivos_Tratados", "WiNS_Prospeccao_Obras_2026_2027.xlsx")


def classify_role(cargo: str) -> str:
    c = cargo or ""
    if re.search(r"(compra|suprimento|procurement|sourcing|supply\s*chain|licitac|pregoeir|aquisic|contrato)", c, re.I):
        return "1_COMPRADOR_SUPRIMENTOS"
    if re.search(r"(engenheir|engenharia|projeto|obra|capex|implantac|manutenc|operac|industrial|construc|infraestrutura|tecnic|construction|project|mechanical|electrical)", c, re.I):
        return "2_GESTOR_TECNICO_OBRA"
    if re.search(r"(diretor|presidente|ceo|cfo|coo|vp|superintendente|head|gerente\s*geral)", c, re.I):
        return "3_DIRETORIA_EXECUTIVA"
    return "5_OUTRO_NAO_CLASSIFICADO"


con = duckdb.connect(MAIN_DB)
ins_ce = 0
upd_dl = 0

# 1. Ingerir retorno Compras/Engenharia/CAPEX
if os.path.exists(RET_CE):
    with open(RET_CE, "r", encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    for i, r in enumerate(rows):
        chave = (r.get("chave") or "").strip()
        cnpj = re.sub(r"\D", "", r.get("cnpj") or "")
        nome = (r.get("decisor_nome") or "").strip()
        cargo = (r.get("decisor_cargo") or "").strip()
        lk = (r.get("decisor_linkedin") or "").strip()
        em = (r.get("decisor_email") or "").strip().lower()
        tel = re.sub(r"\D", "", r.get("decisor_telefone") or "")
        if len(nome) < 4 or not (lk or em or tel):
            continue
        perfil = classify_role(cargo)
        obras_m = con.execute("""
            SELECT id_externo, fonte, obra_nome, obra_empresa, obra_cnpj, categoria_macro, obra_uf, capex_estimado, capex_tipo, url_origem
            FROM obras_oficiais_ativas
            WHERE (obra_cnpj = ? AND ? <> '') OR (obra_empresa = ? AND ? <> '')
        """, [cnpj, cnpj, chave, chave]).fetchall()
        for o in obras_m:
            con.execute("""
                INSERT INTO validacao_decisores_obras_novas VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, [
                o[0], o[1], o[2], o[3], o[4], o[5], o[6], o[7], o[8], o[9],
                "9_OPENBOT_COMPRAS_ENG", f"OPENBOT-CE-{i}", nome, cargo or None,
                em or None, tel or None, lk or None,
                "verde", True, perfil
            ])
            ins_ce += 1

# 2. Ingerir LinkedIns de Diretores e Presidentes
if os.path.exists(RET_DL):
    with open(RET_DL, "r", encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        nome = (r.get("decisor_nome") or "").strip()
        lk = (r.get("decisor_linkedin") or "").strip()
        cnpj = re.sub(r"\D", "", r.get("cnpj") or "")
        if len(nome) < 4 or "linkedin.com/in/" not in lk.lower():
            continue
        res = con.execute("""
            UPDATE validacao_decisores_obras_novas
            SET decisor_linkedin = ?, is_contato_acionavel = TRUE
            WHERE LOWER(TRIM(decisor_nome)) = LOWER(TRIM(?))
              AND (obra_cnpj = ? OR ? = '')
              AND (decisor_linkedin IS NULL OR decisor_linkedin = '')
            RETURNING id_externo
        """, [lk, nome, cnpj, cnpj]).fetchall()
        upd_dl += len(res)

# Deduplicar
con.execute("""
CREATE OR REPLACE TABLE validacao_decisores_obras_novas AS
SELECT DISTINCT ON (id_externo, LOWER(TRIM(decisor_nome)), COALESCE(decisor_email, ''), COALESCE(decisor_linkedin, ''))
    *
FROM validacao_decisores_obras_novas
ORDER BY id_externo, LOWER(TRIM(decisor_nome)), COALESCE(decisor_email, ''), COALESCE(decisor_linkedin, ''), perfil_decisor, is_contato_acionavel DESC;
""")

# Reconstruir todas_obras_consolidadas e campanha_por_decisor_unico
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

con.execute("""
CREATE OR REPLACE TABLE campanha_por_decisor_unico AS
WITH base AS (
    SELECT
        v.*,
        t.dominio_corporativo,
        t.mx_ativo,
        t.whatsapp_oficial,
        LOWER(TRIM(v.decisor_nome)) || '|' || COALESCE(
            NULLIF(LOWER(TRIM(v.decisor_email)), ''),
            NULLIF(LOWER(TRIM(v.decisor_linkedin)), ''),
            NULLIF(TRIM(v.decisor_telefone), ''),
            'SEM_CANAL'
        ) AS chave_pessoa
    FROM validacao_decisores_obras_novas v
    JOIN todas_obras_consolidadas t ON v.id_externo = t.obra_id
    WHERE v.is_contato_acionavel = TRUE
)
SELECT
    chave_pessoa,
    ANY_VALUE(decisor_nome) AS decisor_nome,
    MIN(perfil_decisor) AS perfil_prioritario,
    ANY_VALUE(decisor_cargo) AS decisor_cargo,
    NULLIF(MAX(COALESCE(decisor_email, '')), '') AS decisor_email,
    NULLIF(MAX(COALESCE(decisor_telefone, '')), '') AS decisor_telefone,
    NULLIF(MAX(COALESCE(decisor_linkedin, '')), '') AS decisor_linkedin,
    NULLIF(MAX(COALESCE(dominio_corporativo, '')), '') AS dominio_corporativo,
    BOOL_OR(COALESCE(mx_ativo, FALSE)) AS dominio_mx_ativo,
    NULLIF(MAX(COALESCE(whatsapp_oficial, '')), '') AS whatsapp_oficial_empresa,
    COUNT(DISTINCT id_externo) AS qtd_obras_sob_gestao,
    ROUND(SUM(capex_estimado), 2) AS capex_total_sob_gestao,
    STRING_AGG(DISTINCT obra_uf, ', ' ORDER BY obra_uf) AS ufs_atuacao,
    STRING_AGG(DISTINCT categoria_macro, ', ' ORDER BY categoria_macro) AS categorias,
    STRING_AGG(DISTINCT obra_empresa, ' | ') FILTER (WHERE obra_empresa IS NOT NULL) AS empresas_relacionadas,
    ARG_MAX(obra_nome, capex_estimado) AS obra_principal_maior_capex,
    ARG_MAX(url_origem, capex_estimado) AS url_obra_principal
FROM base
GROUP BY chave_pessoa
ORDER BY perfil_prioritario, capex_total_sob_gestao DESC;
""")

con.execute(f"COPY todas_obras_consolidadas TO '{OUT_ALL_CSV}' (HEADER, DELIMITER ',');")
con.execute(f"COPY validacao_decisores_obras_novas TO '{OUT_DEC_CSV}' (HEADER, DELIMITER ',');")
df_antispam = con.execute("SELECT * FROM campanha_por_decisor_unico").fetchdf()
df_antispam.to_csv(OUT_ANTISPAM_CSV, index=False, encoding="utf-8-sig")

df_resumo = con.execute("""
SELECT fonte, categoria_macro, COUNT(*) AS total_obras,
       SUM(CASE WHEN decisores_acionaveis > 0 THEN 1 ELSE 0 END) AS obras_acionaveis,
       SUM(CASE WHEN decisores_operacionais > 0 THEN 1 ELSE 0 END) AS obras_com_comprador_eng,
       SUM(CASE WHEN mx_ativo THEN 1 ELSE 0 END) AS obras_dominio_mx_ativo,
       SUM(CASE WHEN whatsapp_oficial IS NOT NULL THEN 1 ELSE 0 END) AS obras_com_whatsapp_site,
       ROUND(SUM(capex_estimado)/1e6, 2) AS capex_total_mi
FROM todas_obras_consolidadas GROUP BY 1, 2 ORDER BY 3 DESC;
""").fetchdf()
df_obras = con.execute("SELECT * FROM todas_obras_consolidadas ORDER BY decisores_operacionais DESC, capex_estimado DESC;").fetchdf()
df_dec_op = con.execute("SELECT * FROM campanha_por_decisor_unico WHERE perfil_prioritario IN ('1_COMPRADOR_SUPRIMENTOS', '2_GESTOR_TECNICO_OBRA')").fetchdf()

with pd.ExcelWriter(OUT_XLSX, engine="openpyxl") as writer:
    df_resumo.to_excel(writer, sheet_name="Resumo_Executivo", index=False)
    df_dec_op.to_excel(writer, sheet_name="Decisores_Unicos_AntiSpam", index=False)
    df_obras.to_excel(writer, sheet_name="Todas_Obras_Validadas", index=False)
    df_antispam.to_excel(writer, sheet_name="Todos_Decisores_Unicos", index=False)

cnt_ce = con.execute("SELECT COUNT(*) FROM todas_obras_consolidadas WHERE decisores_operacionais > 0").fetchone()[0]
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

print(f"[INGEST] Novos vinculos Compras/Eng: {ins_ce} | LinkedIns Diretoria atualizados: {upd_dl}")
print(f"[COBERTURA REAL] Obras com Compras/Engenharia/CAPEX: {cnt_ce:,} de 2,604")
subprocess.run(["python", os.path.join(BASE_DIR, "scripts", "gerar_dashboard_html.py")], check=True)
