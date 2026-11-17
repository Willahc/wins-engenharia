import os
import re
import time
import unicodedata
import requests
import duckdb

BASE_DIR = r"C:\Users\kbadmin\Documents\Projetos\01_Ecossistema_WiNS\Engenharia"
MAIN_DB = os.path.join(BASE_DIR, "Banco_Dados", "wins_engenharia.duckdb")
OUT_ALL_CSV = os.path.join(BASE_DIR, "Arquivos_Tratados", "obras_ativas_fontes_validadas.csv").replace("\\", "/")
OUT_DEC_CSV = os.path.join(BASE_DIR, "Arquivos_Tratados", "obras_novas_com_decisores.csv").replace("\\", "/")
OUT_GAP_QUEUE = os.path.join(BASE_DIR, "Arquivos_Tratados", "fila_openbot_fechamento_lacunas.csv").replace("\\", "/")

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
    "compras", "suprimentos", "licitacao", "licitacoes", "engenharia",
    "projetos", "obras", "orcamento", "orcamentos", "noreply", "no-reply",
    "naoresponda", "secretaria", "diretoria", "gerencia", "recepcao",
    "faleconosco", "ouvidoria", "juridico", "marketing", "ti", "geral",
    "abertura", "meucnpj", "societario", "legalizacao"
}


def strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s or "") if not unicodedata.combining(c))


def extract_aneel_owner_v2(raw: str) -> str:
    if not raw:
        return ""
    part = re.split(r"[;|,]\s*\d", raw)[0].strip()
    part = re.sub(r"^\s*\d+(?:[.,]\d+)?\s*%\s*(?:para\s+)?", "", part, flags=re.I)
    part = re.sub(r"\s*\([A-Z]{2,5}\)\s*$", "", part, flags=re.I)
    return re.sub(r"\s+", " ", part).strip()


def norm_razao(name: str) -> str:
    if not name:
        return ""
    s = strip_accents(name.upper())
    s = re.sub(r"[^A-Z0-9\s]", " ", s)
    s = re.sub(r"\b(LTDA|S\.?A\.?|SA|EIRELI|ME|EPP|SPE)\b", " ", s)
    return re.sub(r"\s+", " ", s).strip()


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


def extract_domain(em: str) -> str:
    if not em or "@" not in em:
        return ""
    dom = em.strip().lower().split("@", 1)[1]
    return "" if dom in FREE_OR_BUREAU_DOMAINS else dom


def fetch_brasilapi(cnpj: str):
    url = f"https://brasilapi.com.br/api/cnpj/v1/{cnpj}"
    for attempt in range(3):
        try:
            r = requests.get(url, timeout=15, headers={"User-Agent": "WiNS-Engenharia-GapCloser/1.0"})
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
con.create_function("extract_aneel_owner_v2", extract_aneel_owner_v2, ["VARCHAR"], "VARCHAR")
con.create_function("norm_razao", norm_razao, ["VARCHAR"], "VARCHAR")
con.create_function("extract_domain", extract_domain, ["VARCHAR"], "VARCHAR")

# ---------------------------------------------------------------------------
# PASSO 1: Tentar resolver os 94 CNPJs restantes da ANEEL (consorcios / SPE)
# ---------------------------------------------------------------------------
con.execute("""
CREATE OR REPLACE TEMP TABLE aneel_sem_cnpj AS
SELECT
    id_externo,
    extract_aneel_owner_v2(obra_empresa) AS emp_limpa,
    norm_razao(extract_aneel_owner_v2(obra_empresa)) AS emp_norm
FROM obras_oficiais_ativas
WHERE obra_cnpj IS NULL;
""")

con.execute("""
CREATE OR REPLACE TEMP TABLE lookup_cnpj_v2 AS
WITH uniao AS (
    SELECT norm_razao(razao_social) AS emp_norm, cnpj, 1 AS prio FROM fornecedores WHERE razao_social IS NOT NULL
    UNION ALL
    SELECT norm_razao(obra_empresa) AS emp_norm, obra_cnpj AS cnpj, 2 AS prio FROM obras WHERE obra_empresa IS NOT NULL AND obra_cnpj IS NOT NULL
)
SELECT DISTINCT ON (emp_norm) emp_norm, cnpj
FROM uniao
WHERE LENGTH(emp_norm) >= 6
ORDER BY emp_norm, prio, cnpj;
""")

resolved_v2 = con.execute("""
SELECT a.id_externo, a.emp_limpa, l.cnpj
FROM aneel_sem_cnpj a
JOIN lookup_cnpj_v2 l ON a.emp_norm = l.emp_norm;
""").fetchall()

if resolved_v2:
    con.executemany("""
        UPDATE obras_oficiais_ativas
        SET obra_cnpj = ?, obra_cnpj_raiz = SUBSTR(?, 1, 8), obra_empresa = ?, obra_empresa_norm = norm_razao(?)
        WHERE id_externo = ?
    """, [(r[2], r[2], r[1], r[1], r[0]) for r in resolved_v2])
print(f"[PASSO 1] CNPJs adicionais resolvidos para obras sem CNPJ: {len(resolved_v2)}")

# ---------------------------------------------------------------------------
# PASSO 2: Backfill de dominio corporativo a partir de validacao_decisores e fornecedores (por cnpj_raiz)
# ---------------------------------------------------------------------------
free_list_sql = ",".join(f"'{d}'" for d in sorted(FREE_OR_BUREAU_DOMAINS))
con.execute(f"""
CREATE OR REPLACE TABLE empresa_dominios_verificados AS
WITH dom_val AS (
    SELECT obra_cnpj AS cnpj, SUBSTR(obra_cnpj, 1, 8) AS cnpj_raiz, extract_domain(decisor_email) AS dominio, 'VALIDACAO_DECISORES' AS src
    FROM validacao_decisores_obras_novas
    WHERE decisor_email IS NOT NULL AND extract_domain(decisor_email) <> ''
),
dom_dec AS (
    SELECT obra_cnpj AS cnpj, obra_cnpj_raiz AS cnpj_raiz, extract_domain(email) AS dominio, 'BASE_DECISORES' AS src
    FROM dim_decisores_empresa
    WHERE email IS NOT NULL AND extract_domain(email) <> ''
),
dom_forn AS (
    SELECT cnpj, cnpj_raiz, extract_domain(email) AS dominio, 'BASE_FORNECEDORES' AS src
    FROM fornecedores
    WHERE email IS NOT NULL AND extract_domain(email) <> ''
),
todos_dom AS (
    SELECT cnpj, cnpj_raiz, dominio, src, 1 AS prio FROM dom_val
    UNION ALL
    SELECT cnpj, cnpj_raiz, dominio, src, 2 AS prio FROM dom_dec
    UNION ALL
    SELECT cnpj, cnpj_raiz, dominio, src, 3 AS prio FROM dom_forn
),
alvo AS (
    SELECT DISTINCT obra_cnpj AS cnpj, obra_cnpj_raiz AS cnpj_raiz, ANY_VALUE(obra_empresa) AS obra_empresa, COUNT(*) AS qtd_obras_ativas
    FROM obras_oficiais_ativas
    WHERE obra_cnpj IS NOT NULL
    GROUP BY 1, 2
),
by_cnpj AS (
    SELECT DISTINCT ON (cnpj) cnpj, dominio, src FROM todos_dom WHERE cnpj IS NOT NULL ORDER BY cnpj, prio, dominio
),
by_raiz AS (
    SELECT DISTINCT ON (cnpj_raiz) cnpj_raiz, dominio, src FROM todos_dom WHERE cnpj_raiz IS NOT NULL ORDER BY cnpj_raiz, prio, dominio
)
SELECT
    a.cnpj,
    a.cnpj_raiz,
    a.obra_empresa,
    a.qtd_obras_ativas,
    COALESCE(bc.dominio, br.dominio) AS dominio_corporativo,
    COALESCE(bc.src, CASE WHEN br.dominio IS NOT NULL THEN br.src || '_RAIZ' ELSE 'SEM_DOMINIO_LOCAL' END) AS origem_dominio
FROM alvo a
LEFT JOIN by_cnpj bc ON a.cnpj = bc.cnpj
LEFT JOIN by_raiz br ON a.cnpj_raiz = br.cnpj_raiz;
""")

# ---------------------------------------------------------------------------
# PASSO 3: Consultar BrasilAPI para CNPJs sem dominio ou sem decisor
# ---------------------------------------------------------------------------
cnpjs_api = con.execute("""
SELECT DISTINCT e.cnpj
FROM empresa_dominios_verificados e
WHERE e.dominio_corporativo IS NULL
   OR NOT EXISTS (SELECT 1 FROM validacao_decisores_obras_novas v WHERE v.obra_cnpj = e.cnpj)
""").fetchall()
cnpjs_list = [r[0] for r in cnpjs_api]
print(f"[PASSO 3] Consultando BrasilAPI para {len(cnpjs_list)} CNPJs sem dominio ou sem decisor...")

api_domains = []
api_qsa = []
for idx, cnpj in enumerate(cnpjs_list, 1):
    data = fetch_brasilapi(cnpj)
    if data:
        raw_em = (data.get("email") or "").strip().lower()
        dom = extract_domain(raw_em)
        if dom:
            api_domains.append((dom, "BRASILAPI_CNPJ", cnpj))
        em_clean = clean_email(raw_em)
        tel_clean = clean_phone(data.get("ddd_telefone_1") or "")
        for s_i, s in enumerate(data.get("qsa") or []):
            id_soc = s.get("identificador_de_socio")
            if id_soc == 1:
                nome = (s.get("nome_representante_legal") or "").strip()
                cargo = (s.get("qualificacao_representante_legal") or "Representante Legal").strip()
            else:
                nome = (s.get("nome_socio") or "").strip()
                cargo = (s.get("qualificacao_socio") or "Sócio/Administrador").strip()
            if nome and len(nome) >= 4:
                api_qsa.append((cnpj, s_i, nome, cargo, em_clean, tel_clean))
    if idx % 50 == 0:
        print(f"  BrasilAPI: {idx}/{len(cnpjs_list)} (dominios={len(api_domains)}, qsa={len(api_qsa)})")
    time.sleep(0.25)

if api_domains:
    con.executemany("""
        UPDATE empresa_dominios_verificados
        SET dominio_corporativo = ?, origem_dominio = ?
        WHERE cnpj = ? AND dominio_corporativo IS NULL
    """, api_domains)

if api_qsa:
    for cnpj, s_i, nome, cargo, em_c, tel_c in api_qsa:
        obras_m = con.execute("""
            SELECT id_externo, fonte, obra_nome, obra_empresa, obra_cnpj, categoria_macro, obra_uf, capex_estimado, capex_tipo, url_origem
            FROM obras_oficiais_ativas WHERE obra_cnpj = ?
        """, [cnpj]).fetchall()
        for o in obras_m:
            acionavel = bool(em_c or tel_c)
            con.execute("""
                INSERT INTO validacao_decisores_obras_novas VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, [
                o[0], o[1], o[2], o[3], o[4], o[5], o[6], o[7], o[8], o[9],
                "4_QSA_BRASILAPI", f"QSA-GAP-{cnpj}-{s_i}", nome, cargo,
                em_c or None, tel_c or None, None,
                "amarelo" if acionavel else "vermelho", acionavel, "4_SOCIO_QSA"
            ])

    con.execute("""
    CREATE OR REPLACE TABLE validacao_decisores_obras_novas AS
    SELECT DISTINCT ON (id_externo, LOWER(TRIM(decisor_nome)), COALESCE(decisor_email, ''), COALESCE(decisor_linkedin, ''))
        *
    FROM validacao_decisores_obras_novas
    ORDER BY id_externo, LOWER(TRIM(decisor_nome)), COALESCE(decisor_email, ''), COALESCE(decisor_linkedin, ''), perfil_decisor, is_contato_acionavel DESC;
    """)

# ---------------------------------------------------------------------------
# PASSO 4: Reconstruir todas_obras_consolidadas e medir cobertura final
# ---------------------------------------------------------------------------
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

# Gerar fila residual de lacunas (quem ainda nao tem dominio ou esta sem nenhum decisor acionavel)
con.execute(f"""
COPY (
    SELECT
        t.obra_id,
        t.fonte,
        t.obra_nome,
        t.obra_empresa,
        t.obra_cnpj,
        t.obra_uf,
        t.capex_estimado,
        t.dominio_corporativo,
        t.decisores_acionaveis,
        t.url_origem
    FROM todas_obras_consolidadas t
    WHERE t.obra_cnpj IS NULL
       OR t.dominio_corporativo IS NULL
       OR t.decisores_acionaveis = 0
    ORDER BY t.capex_estimado DESC
) TO '{OUT_GAP_QUEUE}' (HEADER, DELIMITER ',');
""")

con.execute(f"COPY todas_obras_consolidadas TO '{OUT_ALL_CSV}' (HEADER, DELIMITER ',');")
con.execute(f"COPY validacao_decisores_obras_novas TO '{OUT_DEC_CSV}' (HEADER, DELIMITER ',');")

# Metricas finais
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

print("\n=== COBERTURA FINAL NAS 2.608 OBRAS VALIDADAS ===")
print(metricas.to_string(index=False))
