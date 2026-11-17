import math
import os
import re
import time
import subprocess
import requests
import duckdb

BASE_DIR = r"C:\Users\kbadmin\Documents\Projetos\01_Ecossistema_WiNS\Engenharia"
MAIN_DB = os.path.join(BASE_DIR, "Banco_Dados", "wins_engenharia.duckdb")
SUB_DB = os.path.join(BASE_DIR, "Banco_Dados", "obras_civil_industrial_2026_2027_100k.duckdb")
OUT_ALL_CSV = os.path.join(BASE_DIR, "Arquivos_Tratados", "obras_ativas_fontes_validadas.csv").replace("\\", "/")
OUT_DEC_CSV = os.path.join(BASE_DIR, "Arquivos_Tratados", "obras_novas_com_decisores.csv").replace("\\", "/")

FREE_OR_BUREAU_DOMAINS = {
    "gmail.com", "hotmail.com", "hotmail.com.br", "outlook.com", "outlook.com.br",
    "live.com", "yahoo.com", "yahoo.com.br", "uol.com.br", "bol.com.br",
    "terra.com.br", "ig.com.br", "icloud.com", "globo.com", "r7.com",
    "contabilizei.com.br", "maismei.com.br", "agilize.com.br", "senhorcontabil.com.br",
    "protonmail.com", "aol.com", "msn.com", "zipmail.com.br"
}

GENERIC_PREFIXES = {
    "contato", "comercial", "vendas", "atendimento", "sac", "suporte", "info",
    "adm", "administrativo", "administracao", "financeiro", "faturamento",
    "fiscal", "contabil", "contabilidade", "rh", "dp", "recrutamento",
    "compras", "suprimentos", "engenharia", "projetos", "obras", "orcamento",
    "noreply", "no-reply", "naoresponda", "secretaria", "diretoria", "gerencia",
    "abertura", "meucnpj", "societario", "legalizacao"
}


def safe_str(val) -> str:
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return ""
    return str(val).strip()


def clean_email(raw, allow_public_institutional: bool = False) -> str:
    em = safe_str(raw).lower()
    if not em or "@" not in em or " " in em:
        return ""
    pref, dom = em.split("@", 1)
    if dom in FREE_OR_BUREAU_DOMAINS:
        return ""
    if allow_public_institutional and (".gov.br" in dom or ".leg.br" in dom or ".jus.br" in dom or ".mp.br" in dom):
        return em
    pref_base = re.split(r"[._\-+]", pref)[0]
    if pref in GENERIC_PREFIXES or pref_base in GENERIC_PREFIXES:
        return ""
    return em


def clean_phone(raw) -> str:
    d = re.sub(r"\D", "", safe_str(raw))
    if d.startswith("55") and len(d) in (12, 13):
        d = d[2:]
    if len(d) in (10, 11) and len(set(d)) > 2:
        return d
    return ""


def extract_domain(em) -> str:
    s = safe_str(em).lower()
    if not s or "@" not in s:
        return ""
    dom = s.split("@", 1)[1]
    return "" if dom in FREE_OR_BUREAU_DOMAINS else dom


def fetch_brasilapi(cnpj: str):
    url = f"https://brasilapi.com.br/api/cnpj/v1/{cnpj}"
    for attempt in range(3):
        try:
            r = requests.get(url, timeout=15, headers={"User-Agent": "WiNS-Engenharia-Alavanca1/1.0"})
            if r.status_code == 200:
                return r.json()
            if r.status_code == 429:
                time.sleep(2 ** (attempt + 1))
                continue
            return None
        except requests.RequestException:
            time.sleep(1.0)
    return None


con = duckdb.connect(MAIN_DB)

# 1. Re-cruzar obras com CNPJ OPENBOT_WEB contra dim_decisores_empresa
con.execute("""
CREATE OR REPLACE TEMP TABLE novos_matches_dim AS
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
        ELSE '2_CNPJ_RAIZ'
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
  ON (n.obra_cnpj = d.obra_cnpj) OR (n.obra_cnpj_raiz = d.obra_cnpj_raiz)
WHERE n.cnpj_origem_resolucao = 'OPENBOT_WEB';
""")
cnt_dim = con.execute("SELECT COUNT(*) FROM novos_matches_dim").fetchone()[0]
print(f"[1] Matches recuperados em dim_decisores_empresa para os 35 CNPJs OPENBOT_WEB: {cnt_dim}")

if cnt_dim > 0:
    con.execute("""
    INSERT INTO validacao_decisores_obras_novas
    SELECT
        *,
        CASE
            WHEN REGEXP_MATCHES(COALESCE(decisor_cargo, ''), '(?i)(compra|suprimento|procurement|sourcing|supply\\s*chain|licitac|pregoeir|aquisic|contrato)')
                THEN '1_COMPRADOR_SUPRIMENTOS'
            WHEN REGEXP_MATCHES(COALESCE(decisor_cargo, ''), '(?i)(engenheir|engenharia|projeto|obra|capex|implantac|manutenc|operac|industrial|construc|infraestrutura|tecnic|meio\\s*ambiente)')
                THEN '2_GESTOR_TECNICO_OBRA'
            WHEN REGEXP_MATCHES(COALESCE(decisor_cargo, ''), '(?i)(diretor|presidente|ceo|cfo|coo|vp|vice[- ]presidente|superintendente|head|gerente\\s*geral)')
                THEN '3_DIRETORIA_EXECUTIVA'
            WHEN REGEXP_MATCHES(COALESCE(decisor_cargo, ''), '(?i)(s[oó]cio|administrador|procurador|representante\\s*legal|titular)')
                THEN '4_SOCIO_QSA'
            ELSE '5_OUTRO_NAO_CLASSIFICADO'
        END AS perfil_decisor
    FROM novos_matches_dim;
    """)

# 2. Para as obras sem contato acionavel, checar fornecedores + BrasilAPI
pendentes = con.execute("""
SELECT
    t.obra_id,
    t.fonte,
    t.obra_nome,
    t.obra_empresa,
    t.obra_cnpj,
    t.categoria_macro,
    t.obra_uf,
    t.capex_estimado,
    t.capex_tipo,
    t.url_origem,
    f.telefone_1 AS forn_tel,
    f.email AS forn_email
FROM todas_obras_consolidadas t
LEFT JOIN fornecedores f ON t.obra_cnpj = f.cnpj
WHERE t.decisores_acionaveis = 0;
""").fetchdf()

cnpjs_pend = sorted(pendentes["obra_cnpj"].dropna().unique().tolist())
print(f"[2] Obras sem acionavel: {len(pendentes)} ({len(cnpjs_pend)} CNPJs distintos). Consultando BrasilAPI...")

api_cache = {}
for idx, cnpj in enumerate(cnpjs_pend, 1):
    api_cache[cnpj] = fetch_brasilapi(cnpj)
    if idx % 40 == 0:
        print(f"  BrasilAPI: {idx}/{len(cnpjs_pend)}")
    time.sleep(0.25)

ins_alavanca = 0
dom_updates = []
for _, row in pendentes.iterrows():
    cnpj = row["obra_cnpj"]
    is_pub = str(row["fonte"]).startswith("pncp_")
    data = api_cache.get(cnpj) or {}

    tel = clean_phone(row["forn_tel"]) or clean_phone(data.get("ddd_telefone_1"))
    raw_em = safe_str(row["forn_email"]) or safe_str(data.get("email"))
    em = clean_email(raw_em, allow_public_institutional=is_pub)
    dom = extract_domain(raw_em)
    if dom:
        dom_updates.append((dom, "ALAVANCA1_RF", cnpj))

    # Se ja temos QSA na BrasilAPI, usa os socios; para orgao publico PNCP sem nome, usa unidade institucional oficial
    qsa = data.get("qsa") or []
    if qsa and (tel or em):
        for s_i, s in enumerate(qsa):
            id_soc = s.get("identificador_de_socio")
            nome = (s.get("nome_representante_legal") if id_soc == 1 else s.get("nome_socio") or "").strip()
            cargo = (s.get("qualificacao_representante_legal") if id_soc == 1 else s.get("qualificacao_socio") or "Sócio/Administrador").strip()
            if len(nome) >= 4:
                con.execute("""
                    INSERT INTO validacao_decisores_obras_novas VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, [
                    row["obra_id"], row["fonte"], row["obra_nome"], row["obra_empresa"], cnpj,
                    row["categoria_macro"], row["obra_uf"], float(row["capex_estimado"] or 0),
                    row["capex_tipo"], row["url_origem"],
                    "4_QSA_BRASILAPI", f"ALAV1-QSA-{cnpj}-{s_i}", nome, cargo,
                    em or None, tel or None, None,
                    "amarelo", True, "4_SOCIO_QSA"
                ])
                ins_alavanca += 1
    elif is_pub and (tel or em):
        nome_inst = f"Setor de Licitações / Engenharia - {row['obra_empresa']}"[:200]
        con.execute("""
            INSERT INTO validacao_decisores_obras_novas VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, [
            row["obra_id"], row["fonte"], row["obra_nome"], row["obra_empresa"], cnpj,
            row["categoria_macro"], row["obra_uf"], float(row["capex_estimado"] or 0),
            row["capex_tipo"], row["url_origem"],
            "8_RF_ORGAO_PUBLICO", f"ALAV1-PUB-{cnpj}", nome_inst, "Contato Institucional Oficial (Receita Federal)",
            em or None, tel or None, None,
            "amarelo", True, "1_COMPRADOR_SUPRIMENTOS"
        ])
        ins_alavanca += 1
    elif tel or em:
        # Atualiza contatos em QSA existente caso a obra ja tivesse QSA sem contato
        con.execute("""
            UPDATE validacao_decisores_obras_novas
            SET
                decisor_email = COALESCE(decisor_email, ?),
                decisor_telefone = COALESCE(decisor_telefone, ?),
                is_contato_acionavel = TRUE
            WHERE id_externo = ? AND is_contato_acionavel = FALSE
        """, [em or None, tel or None, row["obra_id"]])

if dom_updates:
    for d, src, c in dom_updates:
        con.execute("""
            UPDATE empresa_dominios_verificados
            SET dominio_corporativo = ?, origem_dominio = ?
            WHERE cnpj = ? AND dominio_corporativo IS NULL
        """, [d, src, c])

# Deduplicar e reconstruir todas_obras_consolidadas
con.execute("""
CREATE OR REPLACE TABLE validacao_decisores_obras_novas AS
SELECT DISTINCT ON (id_externo, LOWER(TRIM(decisor_nome)), COALESCE(decisor_email, ''), COALESCE(decisor_linkedin, ''))
    *
FROM validacao_decisores_obras_novas
ORDER BY id_externo, LOWER(TRIM(decisor_nome)), COALESCE(decisor_email, ''), COALESCE(decisor_linkedin, ''), perfil_decisor, is_contato_acionavel DESC;
""")

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

sub = duckdb.connect(SUB_DB)
main_sql = MAIN_DB.replace("\\", "/")
sub.execute(f"ATTACH '{main_sql}' AS main_db (READ_ONLY);")
sub.execute("CREATE OR REPLACE TABLE decisores_obras_novas AS SELECT * FROM main_db.validacao_decisores_obras_novas;")
sub.execute("CREATE OR REPLACE TABLE obras_consolidadas_ativas AS SELECT * FROM main_db.obras_oficiais_ativas;")
sub.execute("DETACH main_db;")
sub.execute("CHECKPOINT;")
sub.close()

print(f"\n[ALAVANCA 1] Novos vinculos inseridos: {ins_alavanca}")
print(metricas.to_string(index=False))

subprocess.run(["python", os.path.join(BASE_DIR, "scripts", "gerar_dashboard_html.py")], check=True)
