import os
import re
import unicodedata
import duckdb

BASE_DIR = r"C:\Users\kbadmin\Documents\Projetos\01_Ecossistema_WiNS\Engenharia"
MAIN_DB = os.path.join(BASE_DIR, "Banco_Dados", "wins_engenharia.duckdb")
SUB_DB = os.path.join(BASE_DIR, "Banco_Dados", "obras_civil_industrial_2026_2027_100k.duckdb")


def strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


def extract_aneel_owner(raw: str) -> str:
    if not raw:
        return ""
    # Se houver multiplos proprietarios separados por ';', pega o primeiro (maior participacao)
    part = raw.split(";")[0].strip()
    # Remove prefixos como "100% para " ou "50,00% para "
    part = re.sub(r"^\s*\d+(?:[.,]\d+)?\s*%\s*(?:para\s+)?", "", part, flags=re.I)
    # Remove sufixos como " (PIE)", " (APE)", " (REG)"
    part = re.sub(r"\s*\([A-Z]{2,5}\)\s*$", "", part, flags=re.I)
    return re.sub(r"\s+", " ", part).strip()


def norm_razao(name: str) -> str:
    if not name:
        return ""
    s = strip_accents(name.upper())
    s = re.sub(r"[^A-Z0-9\s]", " ", s)
    s = re.sub(r"\b(LTDA|S\.?A\.?|SA|EIRELI|ME|EPP)\b", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


con = duckdb.connect(MAIN_DB)
con.create_function("extract_aneel_owner", extract_aneel_owner, ["VARCHAR"], "VARCHAR")
con.create_function("norm_razao", norm_razao, ["VARCHAR"], "VARCHAR")

# 1. Extrair razao social limpa para ANEEL
con.execute("""
CREATE OR REPLACE TEMP TABLE aneel_to_resolve AS
SELECT
    id_externo,
    obra_uf,
    obra_empresa AS obra_empresa_original,
    extract_aneel_owner(obra_empresa) AS empresa_limpa,
    norm_razao(extract_aneel_owner(obra_empresa)) AS empresa_norm
FROM obras_oficiais_ativas
WHERE fonte = 'aneel_siga' AND obra_cnpj IS NULL;
""")

# 2. Indice de razoes sociais unicas das bases locais (fornecedores + obras historicas)
con.execute("""
CREATE OR REPLACE TEMP TABLE lookup_cnpj_local AS
WITH uniao AS (
    SELECT
        norm_razao(razao_social) AS emp_norm,
        cnpj,
        uf,
        1 AS prio_src
    FROM fornecedores
    WHERE razao_social IS NOT NULL AND razao_social <> ''
    UNION ALL
    SELECT
        norm_razao(obra_empresa) AS emp_norm,
        obra_cnpj AS cnpj,
        obra_uf AS uf,
        2 AS prio_src
    FROM obras
    WHERE obra_empresa IS NOT NULL AND obra_cnpj IS NOT NULL AND LENGTH(obra_cnpj) = 14
)
SELECT DISTINCT ON (emp_norm)
    emp_norm,
    cnpj,
    uf,
    prio_src
FROM uniao
WHERE LENGTH(emp_norm) >= 6
ORDER BY emp_norm, prio_src, cnpj;
""")

# 3. Resolver CNPJs por match exato de razao social normalizada
con.execute("""
CREATE OR REPLACE TEMP TABLE aneel_resolved AS
SELECT
    a.id_externo,
    a.empresa_limpa,
    l.cnpj AS cnpj_resolvido,
    CASE l.prio_src
        WHEN 1 THEN 'FORNECEDORES_RAZAO_SOCIAL'
        WHEN 2 THEN 'OBRAS_HISTORICAS_EMPRESA'
    END AS origem_cnpj
FROM aneel_to_resolve a
JOIN lookup_cnpj_local l ON a.empresa_norm = l.emp_norm;
""")

resolved_cnt = con.execute("SELECT COUNT(*) FROM aneel_resolved").fetchone()[0]
by_src = con.execute("SELECT origem_cnpj, COUNT(*) AS qtd FROM aneel_resolved GROUP BY 1").fetchdf()
print(f"[ANEEL] CNPJs resolvidos localmente: {resolved_cnt:,} de 2,215")
print(by_src.to_string(index=False))

# 4. Atualizar obras_oficiais_ativas com os CNPJs resolvidos e empresa_limpa
con.execute("""
CREATE OR REPLACE TABLE obras_oficiais_ativas AS
SELECT
    o.id_externo,
    o.fonte,
    o.obra_nome,
    COALESCE(r.empresa_limpa, o.obra_empresa) AS obra_empresa,
    norm_razao(COALESCE(r.empresa_limpa, o.obra_empresa)) AS obra_empresa_norm,
    COALESCE(o.obra_cnpj, r.cnpj_resolvido) AS obra_cnpj,
    SUBSTR(COALESCE(o.obra_cnpj, r.cnpj_resolvido), 1, 8) AS obra_cnpj_raiz,
    o.categoria_macro,
    o.obra_uf,
    o.obra_municipio,
    o.capex_estimado,
    o.capex_tipo,
    o.data_inicio_prevista,
    o.data_fim_prevista,
    o.situacao,
    o.url_origem,
    CASE WHEN f.cnpj IS NOT NULL THEN TRUE ELSE o.tem_match_fornecedor END AS tem_match_fornecedor,
    CASE
        WHEN o.obra_cnpj IS NOT NULL THEN 'FONTE_ORIGINAL'
        WHEN r.cnpj_resolvido IS NOT NULL THEN r.origem_cnpj
        ELSE 'NAO_RESOLVIDO'
    END AS cnpj_origem_resolucao
FROM obras_oficiais_ativas o
LEFT JOIN aneel_resolved r ON o.id_externo = r.id_externo
LEFT JOIN fornecedores f ON COALESCE(o.obra_cnpj, r.cnpj_resolvido) = f.cnpj;
""")

# 5. Re-executar validacao de decisores com os novos CNPJs!
con.execute("""
CREATE OR REPLACE TABLE validacao_decisores_obras_novas AS
WITH matches AS (
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
            WHEN d.obra_cnpj_raiz IS NOT NULL AND n.obra_cnpj_raiz = d.obra_cnpj_raiz THEN '2_CNPJ_RAIZ'
            WHEN d.obra_empresa_norm <> '' AND n.obra_empresa_norm = d.obra_empresa_norm THEN '3_EMPRESA_NOME'
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
      ON (n.obra_cnpj IS NOT NULL AND n.obra_cnpj = d.obra_cnpj)
      OR (n.obra_cnpj_raiz IS NOT NULL AND n.obra_cnpj_raiz = d.obra_cnpj_raiz)
      OR (n.obra_empresa_norm <> '' AND n.obra_empresa_norm = d.obra_empresa_norm)
)
SELECT DISTINCT ON (id_externo, LOWER(TRIM(decisor_nome)), COALESCE(decisor_email, ''), COALESCE(decisor_linkedin, ''))
    *
FROM matches
ORDER BY id_externo, LOWER(TRIM(decisor_nome)), COALESCE(decisor_email, ''), COALESCE(decisor_linkedin, ''), tipo_match, is_contato_acionavel DESC;
""")

print("\n=== COBERTURA DE CNPJ POR FONTE (APOS RESOLUCAO) ===")
print(con.execute("""
SELECT fonte, COUNT(*) AS total,
       SUM(CASE WHEN obra_cnpj IS NOT NULL THEN 1 ELSE 0 END) AS com_cnpj,
       SUM(CASE WHEN tem_match_fornecedor THEN 1 ELSE 0 END) AS match_fornecedor
FROM obras_oficiais_ativas
GROUP BY 1 ORDER BY 2 DESC
""").fetchdf().to_string(index=False))

print("\n=== DECISORES NAS OBRAS NOVAS (APOS RESOLUCAO DE CNPJ) ===")
print(con.execute("""
SELECT
    COUNT(DISTINCT o.id_externo) AS total_obras_novas,
    COUNT(DISTINCT m.id_externo) AS obras_com_decisor,
    COUNT(DISTINCT CASE WHEN m.is_contato_acionavel THEN o.id_externo END) AS obras_com_acionavel,
    COUNT(*) FILTER (WHERE m.id_externo IS NOT NULL) AS total_vinculos,
    COUNT(*) FILTER (WHERE m.is_contato_acionavel) AS vinculos_acionaveis
FROM obras_oficiais_ativas o
LEFT JOIN validacao_decisores_obras_novas m ON o.id_externo = m.id_externo
""").fetchdf().to_string(index=False))

con.execute("ANALYZE;")
con.execute("CHECKPOINT;")
con.close()
