import csv
import os
import re
import subprocess
import duckdb

BASE_DIR = r"C:\Users\kbadmin\Documents\Projetos\01_Ecossistema_WiNS\Engenharia"
MAIN_DB = os.path.join(BASE_DIR, "Banco_Dados", "wins_engenharia.duckdb")
SUB_DB = os.path.join(BASE_DIR, "Banco_Dados", "obras_civil_industrial_2026_2027_100k.duckdb")
RET_PRIV = os.path.join(BASE_DIR, "Arquivos_Tratados", "retorno_openbot_privadas.csv")
RET_PUB = os.path.join(BASE_DIR, "Arquivos_Tratados", "retorno_openbot_publicas.csv")
OUT_CSV = os.path.join(BASE_DIR, "Arquivos_Tratados", "obras_novas_com_decisores.csv")

GENERIC_PREFIXES = {
    "contato", "comercial", "vendas", "atendimento", "sac", "suporte", "info",
    "adm", "administrativo", "administracao", "financeiro", "faturamento",
    "fiscal", "contabil", "contabilidade", "rh", "dp", "recrutamento",
    "compras", "suprimentos", "engenharia", "projetos", "obras", "orcamento",
    "noreply", "no-reply", "naoresponda", "secretaria", "diretoria", "gerencia"
}


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


def classify_role(cargo: str) -> str:
    c = cargo or ""
    if re.search(r"(compra|suprimento|procurement|sourcing|supply\s*chain|licitac|pregoeir|aquisic|contrato)", c, re.I):
        return "1_COMPRADOR_SUPRIMENTOS"
    if re.search(r"(engenheir|engenharia|projeto|obra|capex|implantac|manutenc|operac|industrial|construc|infraestrutura|tecnic|construction)", c, re.I):
        return "2_GESTOR_TECNICO_OBRA"
    if re.search(r"(diretor|presidente|ceo|cfo|coo|vp|superintendente|head|gerente\s*geral)", c, re.I):
        return "3_DIRETORIA_EXECUTIVA"
    if re.search(r"(s[oó]cio|administrador|procurador|representante\s*legal)", c, re.I):
        return "4_SOCIO_QSA"
    return "5_OUTRO_NAO_CLASSIFICADO"


con = duckdb.connect(MAIN_DB)
inserted = 0
skipped = 0

# 1. Ingerir retorno privado (suporta schema original e schema estendido do OpenBot)
if os.path.exists(RET_PRIV):
    with open(RET_PRIV, "r", encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    for i, r in enumerate(rows):
        status = (r.get("status") or "").strip().upper()
        conf = (r.get("confianca") or "").strip().lower()
        if status in ("CNPJ_PENDENTE", "SUGESTAO_VINCULO") or conf == "baixa":
            skipped += 1
            continue

        nome = (r.get("decisor_nome") or "").strip()
        if len(nome) < 4:
            skipped += 1
            continue

        cargo = (r.get("decisor_cargo") or "").strip()
        em = clean_email(r.get("decisor_email") or "")
        tel = clean_phone(r.get("decisor_telefone") or "")
        lk = (r.get("decisor_linkedin") or "").strip()
        acionavel = bool(em or tel or lk)
        perfil = classify_role(cargo)
        chave = (r.get("chave_empresa_grupo") or "").strip()
        cnpj = re.sub(r"\D", "", (r.get("cnpj_principal") or r.get("cnpj") or ""))

        obras_match = con.execute("""
            SELECT id_externo, fonte, obra_nome, obra_empresa, obra_cnpj, categoria_macro, obra_uf, capex_estimado, capex_tipo, url_origem
            FROM obras_oficiais_ativas
            WHERE (obra_cnpj = ? AND ? <> '')
               OR (COALESCE(NULLIF(obra_cnpj_raiz, ''), obra_empresa_norm) = ? AND ? <> '')
        """, [cnpj, cnpj, chave, chave]).fetchall()

        for o in obras_match:
            con.execute("""
                INSERT INTO validacao_decisores_obras_novas VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, [
                o[0], o[1], o[2], o[3], o[4], o[5], o[6], o[7], o[8], o[9],
                "5_OPENBOT_PRIVADA", f"OPENBOT-PRIV-{i}", nome, cargo or None,
                em or None, tel or None, lk or None,
                "verde" if (status == "CONFIRMADO_WEB" and acionavel) else ("amarelo" if acionavel else "vermelho"),
                acionavel, perfil
            ])
            inserted += 1

# 2. Ingerir retorno publico PNCP
if os.path.exists(RET_PUB):
    with open(RET_PUB, "r", encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    for i, r in enumerate(rows):
        status = (r.get("status") or "").strip().upper()
        conf = (r.get("confianca") or "").strip().lower()
        if status in ("CNPJ_PENDENTE", "SUGESTAO_VINCULO") or conf == "baixa":
            skipped += 1
            continue
        nome = (r.get("decisor_nome") or "").strip()
        if len(nome) < 4:
            skipped += 1
            continue
        cargo = (r.get("decisor_cargo") or "").strip()
        em = (r.get("decisor_email") or "").strip().lower()
        tel = clean_phone(r.get("decisor_telefone") or "")
        lk = (r.get("decisor_linkedin") or "").strip()
        acionavel = bool(em or tel or lk)
        perfil = classify_role(cargo)
        pncp_id = (r.get("numero_controle_pncp") or "").strip()

        obras_match = con.execute("""
            SELECT id_externo, fonte, obra_nome, obra_empresa, obra_cnpj, categoria_macro, obra_uf, capex_estimado, capex_tipo, url_origem
            FROM obras_oficiais_ativas
            WHERE id_externo = ?
        """, [pncp_id]).fetchall()

        for o in obras_match:
            con.execute("""
                INSERT INTO validacao_decisores_obras_novas VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, [
                o[0], o[1], o[2], o[3], o[4], o[5], o[6], o[7], o[8], o[9],
                "6_OPENBOT_PNCP", f"OPENBOT-PUB-{i}", nome, cargo or None,
                em or None, tel or None, lk or None,
                "verde" if acionavel else "amarelo", acionavel, perfil
            ])
            inserted += 1

if inserted > 0:
    con.execute("""
    CREATE OR REPLACE TABLE validacao_decisores_obras_novas AS
    SELECT DISTINCT ON (id_externo, LOWER(TRIM(decisor_nome)), COALESCE(decisor_email, ''), COALESCE(decisor_linkedin, ''))
        *
    FROM validacao_decisores_obras_novas
    ORDER BY id_externo, LOWER(TRIM(decisor_nome)), COALESCE(decisor_email, ''), COALESCE(decisor_linkedin, ''), perfil_decisor, is_contato_acionavel DESC;
    """)
    out_sql = OUT_CSV.replace("\\", "/")
    con.execute(f"COPY validacao_decisores_obras_novas TO '{out_sql}' (HEADER, DELIMITER ',');")

con.execute("ANALYZE;")
con.execute("CHECKPOINT;")
con.close()

if inserted > 0:
    sub = duckdb.connect(SUB_DB)
    main_sql = MAIN_DB.replace("\\", "/")
    sub.execute(f"ATTACH '{main_sql}' AS main_db (READ_ONLY);")
    sub.execute("CREATE OR REPLACE TABLE decisores_obras_novas AS SELECT * FROM main_db.validacao_decisores_obras_novas;")
    sub.execute("DETACH main_db;")
    sub.execute("CHECKPOINT;")
    sub.close()
    subprocess.run(["python", os.path.join(BASE_DIR, "scripts", "gerar_dashboard_html.py")], check=True)

print(f"Ingestao OpenBot concluida: {inserted} vinculos processados | {skipped} descartados (baixa confianca/pendente/sugestao).")
