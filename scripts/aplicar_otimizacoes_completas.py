import os
import re
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
import duckdb
import pandas as pd

BASE_DIR = r"C:\Users\kbadmin\Documents\Projetos\01_Ecossistema_WiNS\Engenharia"
MAIN_DB = os.path.join(BASE_DIR, "Banco_Dados", "wins_engenharia.duckdb")
OUT_XLSX = os.path.join(BASE_DIR, "Arquivos_Tratados", "WiNS_Prospeccao_Obras_2026_2027.xlsx")
OUT_ANTISPAM_CSV = os.path.join(BASE_DIR, "Arquivos_Tratados", "WiNS_Prospeccao_Por_Decisor_Unico.csv")
OUT_ALL_CSV = os.path.join(BASE_DIR, "Arquivos_Tratados", "obras_ativas_fontes_validadas.csv").replace("\\", "/")

NON_OBRA_REGEX = (
    "(?i)\\b(storage|vigil[aâ]ncia\\s+(armada|patrimonial|eletr[oô]nica)|limpeza\\s+predial|"
    "conserva[cç][aã]o\\s+e\\s+limpeza|software|licen[cç]a\\s+de\\s+uso|mobili[aá]rio|"
    "passagens\\s+a[eé]reas|alimenta[cç][aã]o|refei[cç][oõ]es|loca[cç][aã]o\\s+de\\s+ve[ií]culos|"
    "computador|notebook|datacenter\\s+cloud|nuvem)\\b"
)


def check_mx(dom: str):
    try:
        res = subprocess.run(
            ["nslookup", "-type=mx", dom],
            capture_output=True, text=True, encoding="latin-1", errors="replace", timeout=6
        )
        out = (res.stdout or "") + (res.stderr or "")
        has_mx = "mail exchanger" in out.lower()
        return dom, has_mx
    except Exception:
        return dom, False


con = duckdb.connect(MAIN_DB)

# ---------------------------------------------------------------------------
# OTIMIZACAO 3: Limpar licitacoes nao-obra (TI/vigilancia/limpeza) do PNCP
# ---------------------------------------------------------------------------
non_obra_ids = con.execute(f"""
SELECT obra_id, obra_nome
FROM todas_obras_consolidadas
WHERE fonte LIKE 'pncp_%'
  AND REGEXP_MATCHES(obra_nome, '{NON_OBRA_REGEX}');
""").fetchall()

if non_obra_ids:
    con.execute(f"""
    DELETE FROM todas_obras_consolidadas
    WHERE fonte LIKE 'pncp_%' AND REGEXP_MATCHES(obra_nome, '{NON_OBRA_REGEX}');
    """)
    con.execute(f"""
    DELETE FROM obras_oficiais_ativas
    WHERE fonte LIKE 'pncp_%' AND REGEXP_MATCHES(obra_nome, '{NON_OBRA_REGEX}');
    """)
    con.execute(f"""
    DELETE FROM validacao_decisores_obras_novas
    WHERE fonte LIKE 'pncp_%' AND REGEXP_MATCHES(obra_nome, '{NON_OBRA_REGEX}');
    """)
print(f"[OTIMIZACAO 3] Licitacoes nao-obra removidas do PNCP: {len(non_obra_ids)}")

# ---------------------------------------------------------------------------
# OTIMIZACAO 5: Verificacao DNS MX nos dominios corporativos
# ---------------------------------------------------------------------------
domains = [
    r[0] for r in con.execute("""
        SELECT DISTINCT dominio_corporativo
        FROM empresa_dominios_verificados
        WHERE dominio_corporativo IS NOT NULL
    """).fetchall()
]
print(f"[OTIMIZACAO 5] Verificando DNS MX para {len(domains)} dominios...")
mx_map = {}
with ThreadPoolExecutor(max_workers=20) as ex:
    for fut in as_completed([ex.submit(check_mx, d) for d in domains]):
        d, ok = fut.result()
        mx_map[d] = ok

mx_ok_cnt = sum(1 for v in mx_map.values() if v)
print(f"  Dominios com MX ativo: {mx_ok_cnt}/{len(domains)} ({mx_ok_cnt/len(domains)*100:.1f}%)")

con.execute("CREATE OR REPLACE TEMP TABLE tmp_mx (dominio VARCHAR, mx_ativo BOOLEAN);")
con.executemany("INSERT INTO tmp_mx VALUES (?, ?)", list(mx_map.items()))

con.execute("""
CREATE OR REPLACE TABLE empresa_dominios_verificados AS
SELECT
    e.*,
    COALESCE(m.mx_ativo, FALSE) AS mx_ativo
FROM empresa_dominios_verificados e
LEFT JOIN tmp_mx m ON e.dominio_corporativo = m.dominio;
""")

# Atualizar todas_obras_consolidadas com mx_ativo
cols_toc = [r[0] for r in con.execute("DESCRIBE todas_obras_consolidadas").fetchall()]
if "mx_ativo" in cols_toc:
    con.execute("""
    CREATE OR REPLACE TABLE todas_obras_consolidadas AS
    SELECT t.* EXCLUDE (mx_ativo), COALESCE(d.mx_ativo, FALSE) AS mx_ativo
    FROM todas_obras_consolidadas t
    LEFT JOIN empresa_dominios_verificados d ON t.obra_cnpj = d.cnpj;
    """)
else:
    con.execute("""
    CREATE OR REPLACE TABLE todas_obras_consolidadas AS
    SELECT t.*, COALESCE(d.mx_ativo, FALSE) AS mx_ativo
    FROM todas_obras_consolidadas t
    LEFT JOIN empresa_dominios_verificados d ON t.obra_cnpj = d.cnpj;
    """)

# ---------------------------------------------------------------------------
# OTIMIZACAO 1: Visao Anti-Spam por Decisor Unico
# ---------------------------------------------------------------------------
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

dec_unicos_cnt = con.execute("SELECT COUNT(*) FROM campanha_por_decisor_unico").fetchone()[0]
dec_op_unicos = con.execute("""
SELECT COUNT(*) FROM campanha_por_decisor_unico
WHERE perfil_prioritario IN ('1_COMPRADOR_SUPRIMENTOS', '2_GESTOR_TECNICO_OBRA', '3_DIRETORIA_EXECUTIVA')
""").fetchone()[0]
print(f"[OTIMIZACAO 1] Decisores unicos acionaveis (anti-spam): {dec_unicos_cnt:,} (operacionais/executivos: {dec_op_unicos:,})")

# ---------------------------------------------------------------------------
# OTIMIZACAO 4: Cruzamento Obra x Fornecedores Elegiveis (resumo rapido por UF e Setor)
# ---------------------------------------------------------------------------
con.execute("""
CREATE OR REPLACE TABLE resumo_fornecedores_uf_setor AS
SELECT
    uf,
    setor_consolidado,
    COUNT(*) AS total_fornecedores,
    SUM(CASE WHEN is_contato_acionavel THEN 1 ELSE 0 END) AS fornecedores_acionaveis,
    SUM(CASE WHEN porte_consolidado IN ('MEDIA', 'GRANDE', 'PEQUENA') THEN 1 ELSE 0 END) AS fornecedores_estruturados
FROM fornecedores
WHERE setor_consolidado IN (
    'CONSTRUCAO_ESPECIALIZADA', 'CONSTRUCAO_EDIFICIOS', 'INFRAESTRUTURA',
    'ENGENHARIA_ARQUITETURA', 'ENERGIA', 'SANEAMENTO', 'LOGISTICA_TRANSPORTE',
    'LOCACAO_MAQUINAS_EQUIPAMENTOS', 'MATERIAIS_CONSTRUCAO', 'METALURGIA_ESTRUTURAS'
)
GROUP BY 1, 2
ORDER BY 1, 4 DESC;
""")

con.execute("""
CREATE OR REPLACE VIEW vw_obra_fornecedores_elegiveis AS
SELECT
    o.obra_id,
    o.obra_nome,
    o.obra_uf,
    o.categoria_macro,
    o.capex_estimado,
    SUM(r.fornecedores_acionaveis) AS fornecedores_locais_acionaveis_uf,
    SUM(r.fornecedores_estruturados) AS fornecedores_estruturados_uf
FROM todas_obras_consolidadas o
JOIN resumo_fornecedores_uf_setor r ON o.obra_uf = r.uf
WHERE (o.categoria_macro = 'CIVIL' AND r.setor_consolidado IN ('CONSTRUCAO_ESPECIALIZADA', 'CONSTRUCAO_EDIFICIOS', 'INFRAESTRUTURA', 'ENGENHARIA_ARQUITETURA', 'SANEAMENTO'))
   OR (o.categoria_macro = 'INDUSTRIAL' AND r.setor_consolidado IN ('ENGENHARIA_ARQUITETURA', 'ENERGIA', 'CONSTRUCAO_ESPECIALIZADA', 'METALURGIA_ESTRUTURAS', 'LOCACAO_MAQUINAS_EQUIPAMENTOS'))
GROUP BY 1, 2, 3, 4, 5;
""")
print("[OTIMIZACAO 4] Tabela resumo_fornecedores_uf_setor e view vw_obra_fornecedores_elegiveis criadas!")

# ---------------------------------------------------------------------------
# Re-exportar CSVs e Excel multi-abas com a nova aba Anti-Spam
# ---------------------------------------------------------------------------
con.execute(f"COPY todas_obras_consolidadas TO '{OUT_ALL_CSV}' (HEADER, DELIMITER ',');")
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
print(f"Excel atualizado com aba Anti-Spam: {OUT_XLSX} ({os.path.getsize(OUT_XLSX)/(1024*1024):.2f} MB)")
