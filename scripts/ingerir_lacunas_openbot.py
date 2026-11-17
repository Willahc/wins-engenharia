import csv
import os
import re
import subprocess
import duckdb

BASE_DIR = r"C:\Users\kbadmin\Documents\Projetos\01_Ecossistema_WiNS\Engenharia"
MAIN_DB = os.path.join(BASE_DIR, "Banco_Dados", "wins_engenharia.duckdb")
SUB_DB = os.path.join(BASE_DIR, "Banco_Dados", "obras_civil_industrial_2026_2027_100k.duckdb")
RET_LAC = os.path.join(BASE_DIR, "Arquivos_Tratados", "retorno_openbot_lacunas.csv")
OUT_ALL_CSV = os.path.join(BASE_DIR, "Arquivos_Tratados", "obras_ativas_fontes_validadas.csv").replace("\\", "/")
OUT_DEC_CSV = os.path.join(BASE_DIR, "Arquivos_Tratados", "obras_novas_com_decisores.csv").replace("\\", "/")

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
    return "5_OUTRO_NAO_CLASSIFICADO"


con = duckdb.connect(MAIN_DB)

with open(RET_LAC, "r", encoding="utf-8-sig", newline="") as f:
    rows = list(csv.DictReader(f))

cnpjs_upd = 0
doms_upd = 0
decs_ins = 0

for i, r in enumerate(rows):
    chave = (r.get("chave") or "").strip()
    cnpj = re.sub(r"\D", "", r.get("cnpj") or "")
    dom = (r.get("dominio_corporativo") or "").strip().lower()
    nome = (r.get("decisor_nome") or "").strip()
    cargo = (r.get("decisor_cargo") or "").strip()
    lk = (r.get("decisor_linkedin") or "").strip()
    em = clean_email(r.get("decisor_email") or "")
    tel = clean_phone(r.get("decisor_telefone") or "")

    # 1. Atualizar CNPJ nas obras onde estava faltando
    if len(cnpj) == 14 and chave:
        res = con.execute("""
            UPDATE obras_oficiais_ativas
            SET obra_cnpj = ?, obra_cnpj_raiz = ?, cnpj_origem_resolucao = 'OPENBOT_WEB'
            WHERE obra_cnpj IS NULL AND obra_empresa = ?
            RETURNING id_externo
        """, [cnpj, cnpj[:8], chave]).fetchall()
        cnpjs_upd += len(res)

    # 2. Atualizar dominio corporativo em empresa_dominios_verificados
    if dom and len(cnpj) == 14:
        exists = con.execute("SELECT COUNT(*) FROM empresa_dominios_verificados WHERE cnpj = ?", [cnpj]).fetchone()[0]
        if exists:
            con.execute("""
                UPDATE empresa_dominios_verificados
                SET dominio_corporativo = ?, origem_dominio = 'OPENBOT_WEB'
                WHERE cnpj = ? AND dominio_corporativo IS NULL
            """, [dom, cnpj])
        else:
            con.execute("""
                INSERT INTO empresa_dominios_verificados VALUES (?, ?, ?, 1, ?, 'OPENBOT_WEB')
            """, [cnpj, cnpj[:8], r.get("empresa") or chave, dom])
        doms_upd += 1

    # 3. Inserir decisor novo encontrado
    if len(nome) >= 4 and (lk or em or tel):
        obras_m = con.execute("""
            SELECT id_externo, fonte, obra_nome, obra_empresa, obra_cnpj, categoria_macro, obra_uf, capex_estimado, capex_tipo, url_origem
            FROM obras_oficiais_ativas
            WHERE (obra_cnpj = ? AND ? <> '')
               OR (obra_empresa = ? AND ? <> '')
        """, [cnpj, cnpj, chave, chave]).fetchall()
        perfil = classify_role(cargo)
        for o in obras_m:
            con.execute("""
                INSERT INTO validacao_decisores_obras_novas VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, [
                o[0], o[1], o[2], o[3], o[4], o[5], o[6], o[7], o[8], o[9],
                "7_OPENBOT_LACUNAS", f"OPENBOT-LAC-{i}", nome, cargo or None,
                em or None, tel or None, lk or None,
                "verde", True, perfil
            ])
            decs_ins += 1

# Deduplicar validacao_decisores_obras_novas
con.execute("""
CREATE OR REPLACE TABLE validacao_decisores_obras_novas AS
SELECT DISTINCT ON (id_externo, LOWER(TRIM(decisor_nome)), COALESCE(decisor_email, ''), COALESCE(decisor_linkedin, ''))
    *
FROM validacao_decisores_obras_novas
ORDER BY id_externo, LOWER(TRIM(decisor_nome)), COALESCE(decisor_email, ''), COALESCE(decisor_linkedin, ''), perfil_decisor, is_contato_acionavel DESC;
""")

# Reconstruir todas_obras_consolidadas
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
    o.id_externo AS obra_id,
    'NOVA_API_OFICIAL' AS origem_registro,
    'ATIVA_COMPROVADA_API' AS status_validacao_fonte,
    o.fonte,
    o.obra_nome,
    o.obra_empresa,
    o.obra_cnpj,
    o.obra_cnpj_raiz,
    o.categoria_macro,
    o.categoria_macro AS setor_detalhado,
    o.obra_uf,
    o.obra_municipio,
    o.capex_estimado,
    o.capex_tipo,
    o.data_inicio_prevista,
    o.data_fim_prevista,
    o.situacao,
    o.url_origem,
    COALESCE(d.qtd_decisores, 0) AS total_decisores,
    COALESCE(d.qtd_acionaveis, 0) AS decisores_acionaveis,
    COALESCE(d.qtd_operacionais, 0) AS decisores_operacionais,
    o.tem_match_fornecedor,
    dom.dominio_corporativo
FROM obras_oficiais_ativas o
LEFT JOIN novas_dec d ON o.id_externo = d.id_externo
LEFT JOIN empresa_dominios_verificados dom ON o.obra_cnpj = dom.cnpj;
""")

con.execute(f"COPY todas_obras_consolidadas TO '{OUT_ALL_CSV}' (HEADER, DELIMITER ',');")
con.execute(f"COPY validacao_decisores_obras_novas TO '{OUT_DEC_CSV}' (HEADER, DELIMITER ',');")

metricas = con.execute("""
WITH per_obra AS (
    SELECT
        t.obra_id,
        t.obra_cnpj IS NOT NULL AS tem_cnpj,
        t.dominio_corporativo IS NOT NULL AS tem_dominio,
        t.decisores_acionaveis > 0 AS tem_acionavel,
        MAX(CASE WHEN v.decisor_linkedin IS NOT NULL THEN 1 ELSE 0 END) AS tem_linkedin,
        MAX(CASE WHEN v.decisor_email IS NOT NULL THEN 1 ELSE 0 END) AS tem_email,
        MAX(CASE WHEN v.decisor_telefone IS NOT NULL THEN 1 ELSE 0 END) AS tem_telefone,
        MAX(CASE WHEN v.perfil_decisor IN ('1_COMPRADOR_SUPRIMENTOS','2_GESTOR_TECNICO_OBRA','3_DIRETORIA_EXECUTIVA') THEN 1 ELSE 0 END) AS tem_operacional
    FROM todas_obras_consolidadas t
    LEFT JOIN validacao_decisores_obras_novas v ON t.obra_id = v.id_externo
    GROUP BY 1, 2, 3, 4
)
SELECT
    COUNT(*) AS total_obras,
    SUM(tem_cnpj::INT) AS com_cnpj,
    SUM(tem_acionavel::INT) AS com_acionavel,
    SUM(tem_linkedin) AS com_linkedin,
    SUM(tem_dominio::INT) AS com_dominio,
    SUM(tem_email) AS com_email,
    SUM(tem_telefone) AS com_telefone,
    SUM(tem_operacional) AS com_operacional,
    SUM((tem_cnpj AND tem_linkedin=1 AND tem_dominio AND tem_email=1)::INT) AS completas_4_pilares
FROM per_obra;
""").fetchdf()

con.execute("ANALYZE;")
con.execute("CHECKPOINT;")
con.close()

print(f"Atualizacoes: CNPJs em obras={cnpjs_upd}, Dominios={doms_upd}, Decisores={decs_ins}")
print(metricas.to_string(index=False))

subprocess.run(["python", os.path.join(BASE_DIR, "scripts", "gerar_dashboard_html.py")], check=True)
