import os
import re
import subprocess
import unicodedata
import duckdb
import pandas as pd

BASE_DIR = r"C:\Users\kbadmin\Documents\Projetos\01_Ecossistema_WiNS\Engenharia"
MAIN_DB = os.path.join(BASE_DIR, "Banco_Dados", "wins_engenharia.duckdb")
SUB_DB = os.path.join(BASE_DIR, "Banco_Dados", "obras_civil_industrial_2026_2027_100k.duckdb")
OUT_ALL_CSV = os.path.join(BASE_DIR, "Arquivos_Tratados", "obras_ativas_fontes_validadas.csv").replace("\\", "/")
OUT_DEC_CSV = os.path.join(BASE_DIR, "Arquivos_Tratados", "obras_novas_com_decisores.csv").replace("\\", "/")
OUT_ANTISPAM_CSV = os.path.join(BASE_DIR, "Arquivos_Tratados", "WiNS_Prospeccao_Por_Decisor_Unico.csv")
OUT_XLSX = os.path.join(BASE_DIR, "Arquivos_Tratados", "WiNS_Prospeccao_Obras_2026_2027.xlsx")

GENERIC_TOKENS = {
    "contato", "comercial", "vendas", "atendimento", "sac", "suporte", "info",
    "adm", "administrativo", "administracao", "financeiro", "faturamento",
    "fiscal", "contabil", "contabilidade", "rh", "dp", "recrutamento",
    "compras", "suprimentos", "licitacao", "licitacoes", "engenharia",
    "projetos", "obras", "orcamento", "orcamentos", "noreply", "no-reply",
    "naoresponda", "secretaria", "diretoria", "gerencia", "recepcao",
    "faleconosco", "ouvidoria", "juridico", "marketing", "ti", "geral",
    "abertura", "meucnpj", "societario", "legalizacao", "grp", "grupo",
    "equipe", "setor", "departamento", "nfe", "nf", "xml", "boletos", "cobranca",
    "tesouraria", "expedicao", "almoxarifado", "operacoesrodoviarias"
}

NON_DECISOR_CARGO_RE = re.compile(
    r"^\s*(auxiliar|assistente|estagi[aá]ri[oa]|jovem\s+aprendiz|aprendiz|"
    r"recepcionista|porteiro|vigia|zelador|servente|ajudante|motorista|"
    r"operador(\s+de)?|balconista|caixa|repositor|faxineir[oa]|copeir[oa])\b",
    re.I
)

COMPANY_CARGO_RE = re.compile(
    r"\b(ltda|s\.?a\.?|s/a|eireli|me|epp|participa[cç][oõ]es|comercio|industria)\b\.?\s*$",
    re.I
)


def strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s or "") if not unicodedata.combining(c))


def is_generic_email_strict(em: str, fonte: str) -> bool:
    if not em or "@" not in em:
        return False
    em_l = em.strip().lower()
    pref, dom = em_l.split("@", 1)
    # Permite canais setoriais oficiais em orgaos publicos (PNCP)
    if (fonte or "").startswith("pncp_") and (".gov.br" in dom or ".leg.br" in dom or ".jus.br" in dom or ".mp.br" in dom):
        return False
    tokens = [t for t in re.split(r"[._\-+0-9]+", pref) if t]
    if pref in GENERIC_TOKENS or any(t in GENERIC_TOKENS for t in tokens):
        return True
    return False


SECTOR_STOPWORDS = {
    "ltda", "brasil", "energia", "energias", "solar", "eolica", "participacoes",
    "industria", "comercio", "celulose", "geracao", "renovaveis", "renovavel",
    "transmissao", "engenharia", "empreendimentos", "solucoes", "servicos",
    "florestal", "saneamento", "mineracao", "agro", "alimentos", "logistica",
    "nacional", "central", "usina", "parque", "complexo", "grupo"
}


def is_bad_cargo_or_wrong_company(cargo: str, obra_empresa: str) -> bool:
    if not cargo:
        return False
    c = cargo.strip()
    if NON_DECISOR_CARGO_RE.search(c):
        return True
    if COMPANY_CARGO_RE.search(c):
        # Cargo e nome de empresa (ex: "Arauco celulose do Brasil S.A")
        c_toks = set(re.findall(r"[a-z]{4,}", strip_accents(c).lower())) - SECTOR_STOPWORDS
        e_toks = set(re.findall(r"[a-z]{4,}", strip_accents(obra_empresa).lower())) - SECTOR_STOPWORDS
        # Se nao compartilha nenhum nome proprio da empresa, e falso positivo de outra empresa!
        if c_toks and e_toks and not (c_toks & e_toks):
            return True
    return False


con = duckdb.connect(MAIN_DB)
con.create_function("is_generic_email_strict", is_generic_email_strict, ["VARCHAR", "VARCHAR"], "BOOLEAN")
con.create_function("is_bad_cargo_or_wrong_company", is_bad_cargo_or_wrong_company, ["VARCHAR", "VARCHAR"], "BOOLEAN")

bad_cargos_cnt = con.execute("""
SELECT COUNT(*) FROM validacao_decisores_obras_novas
WHERE is_bad_cargo_or_wrong_company(decisor_cargo, obra_empresa);
""").fetchone()[0]

bad_emails_cnt = con.execute("""
SELECT COUNT(*) FROM validacao_decisores_obras_novas
WHERE decisor_email IS NOT NULL AND is_generic_email_strict(decisor_email, fonte);
""").fetchone()[0]

print(f"Encontrados em validacao_decisores_obras_novas:")
print(f"  - Cargos nao-decisores (Auxiliar/Assistente/Estagiario) ou empresa errada no cargo: {bad_cargos_cnt:,}")
print(f"  - E-mails genericos/departamentais (ex: grp_fiscal_contabil@): {bad_emails_cnt:,}")

# 1. Remover registros com cargo nao-decisor ou empresa errada no cargo
con.execute("""
DELETE FROM validacao_decisores_obras_novas
WHERE is_bad_cargo_or_wrong_company(decisor_cargo, obra_empresa);
""")

# 2. Limpar e-mails genericos compostos e recalcular acionabilidade
con.execute("""
UPDATE validacao_decisores_obras_novas
SET
    decisor_email = NULL,
    is_contato_acionavel = (decisor_telefone IS NOT NULL OR decisor_linkedin IS NOT NULL)
WHERE decisor_email IS NOT NULL AND is_generic_email_strict(decisor_email, fonte);
""")

# Limpar tambem na dim_decisores_empresa e decisores historico
con.execute("""
UPDATE dim_decisores_empresa
SET
    email = NULL,
    is_contato_acionavel = (telefone IS NOT NULL OR linkedin_url IS NOT NULL)
WHERE email IS NOT NULL AND is_generic_email_strict(email, 'privado');
""")
con.execute("""
DELETE FROM dim_decisores_empresa
WHERE is_bad_cargo_or_wrong_company(cargo, obra_empresa);
""")

# 3. Reconstruir campanha_por_decisor_unico e todas_obras_consolidadas
con.execute("""
CREATE OR REPLACE TABLE todas_obras_consolidadas AS
WITH novas_dec AS (
    SELECT
        id_externo,
        COUNT(*) AS qtd_decisores,
        SUM(CASE WHEN is_contato_acionavel THEN 1 ELSE 0 END) AS qtd_acionaveis,
        SUM(CASE WHEN perfil_decisor IN ('1_COMPRADOR_SUPRIMENTOS','2_GESTOR_TECNICO_OBRA','3_DIRETORIA_EXECUTIVA') THEN 1 ELSE 0 END) AS qtd_operacionais
    FROM validacao_decisores_obras_novas
    GROUP BY 1
)
SELECT
    t.* EXCLUDE (total_decisores, decisores_acionaveis, decisores_operacionais),
    COALESCE(d.qtd_decisores, 0) AS total_decisores,
    COALESCE(d.qtd_acionaveis, 0) AS decisores_acionaveis,
    COALESCE(d.qtd_operacionais, 0) AS decisores_operacionais
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
SELECT
    fonte, categoria_macro, COUNT(*) AS total_obras,
    SUM(CASE WHEN decisores_acionaveis > 0 THEN 1 ELSE 0 END) AS obras_acionaveis,
    SUM(CASE WHEN decisores_operacionais > 0 THEN 1 ELSE 0 END) AS obras_com_comprador_eng,
    SUM(CASE WHEN mx_ativo THEN 1 ELSE 0 END) AS obras_dominio_mx_ativo,
    SUM(CASE WHEN whatsapp_oficial IS NOT NULL THEN 1 ELSE 0 END) AS obras_com_whatsapp_site,
    ROUND(SUM(capex_estimado)/1e6, 2) AS capex_total_mi
FROM todas_obras_consolidadas GROUP BY 1, 2 ORDER BY 3 DESC;
""").fetchdf()
df_obras = con.execute("SELECT * FROM todas_obras_consolidadas ORDER BY decisores_operacionais DESC, capex_estimado DESC;").fetchdf()
df_dec_op = con.execute("SELECT * FROM campanha_por_decisor_unico WHERE perfil_prioritario IN ('1_COMPRADOR_SUPRIMENTOS', '2_GESTOR_TECNICO_OBRA', '3_DIRETORIA_EXECUTIVA')").fetchdf()

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

subprocess.run(["python", os.path.join(BASE_DIR, "scripts", "gerar_dashboard_html.py")], check=True)
