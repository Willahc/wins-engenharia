import os
import re
import unicodedata
import duckdb

BASE_DIR = r"C:\Users\kbadmin\Documents\Projetos\01_Ecossistema_WiNS\Engenharia"
MAIN_DB = os.path.join(BASE_DIR, "Banco_Dados", "wins_engenharia.duckdb")
OUT_ALL_CSV = os.path.join(BASE_DIR, "Arquivos_Tratados", "todas_obras_antigas_e_novas_consolidadas.csv").replace("\\", "/")


def strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s or "") if not unicodedata.combining(c))


def norm_text(s: str) -> str:
    s = strip_accents((s or "").upper())
    s = re.sub(r"[^A-Z0-9\s]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


con = duckdb.connect(MAIN_DB)
con.create_function("norm_text", norm_text, ["VARCHAR"], "VARCHAR")

# 1. Deduplicar obras antigas elegiveis (Brasil, Civil/Industrial, CAPEX > 100k)
con.execute("""
CREATE OR REPLACE TEMP TABLE antigas_dedup AS
SELECT DISTINCT ON (COALESCE(obra_cnpj, ''), norm_text(obra_nome))
    obra_id,
    obra_nome,
    obra_empresa,
    obra_cnpj,
    obra_cnpj_raiz,
    obra_setor,
    CASE
        WHEN obra_setor IN ('INFRAESTRUTURA', 'SANEAMENTO', 'HOSPITALAR', 'LOGISTICA', 'PORTUARIO', 'ENERGIA') THEN 'CIVIL'
        WHEN obra_setor IN ('INDUSTRIAL', 'AUTOMOTIVO', 'ALIMENTOS_E_BEBIDAS', 'PAPEL_E_CELULOSE', 'SIDERURGIA', 'QUIMICA', 'PETROLEO_GAS', 'MINERACAO', 'DATA_CENTER') THEN 'INDUSTRIAL'
    END AS categoria_macro,
    obra_uf,
    obra_municipio,
    obra_capex_analitico AS capex_estimado,
    total_decisores,
    decisores_acionaveis
FROM obras
WHERE obra_uf IS NOT NULL
  AND obra_capex_analitico > 100000
  AND obra_setor IN (
      'INFRAESTRUTURA', 'SANEAMENTO', 'HOSPITALAR', 'LOGISTICA', 'PORTUARIO', 'ENERGIA',
      'INDUSTRIAL', 'AUTOMOTIVO', 'ALIMENTOS_E_BEBIDAS', 'PAPEL_E_CELULOSE',
      'SIDERURGIA', 'QUIMICA', 'PETROLEO_GAS', 'MINERACAO', 'DATA_CENTER'
  )
ORDER BY COALESCE(obra_cnpj, ''), norm_text(obra_nome), decisores_acionaveis DESC, total_decisores DESC, obra_capex_analitico DESC;
""")

# 2. Unificar:
#    - Todas as 2.608 obras novas (obras_oficiais_ativas) -> ATIVA_COMPROVADA_API
#    - Todas as obras antigas deduplicadas que NAO estao duplicadas nas novas -> HISTORICA_2026_ATIVA_NA_BASE
#      (e se a obra antiga deu match por CNPJ + nome com uma obra nova, ela e absorvida pela obra nova comprovada)
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
),
novas_fmt AS (
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
    LEFT JOIN empresa_dominios_verificados dom ON o.obra_cnpj = dom.cnpj
),
antigas_fmt AS (
    SELECT
        a.obra_id,
        'HISTORICA_2026_WINS' AS origem_registro,
        'HISTORICA_2026_SEM_URL_NA_ORIGEM' AS status_validacao_fonte,
        'base_wins_2026' AS fonte,
        a.obra_nome,
        a.obra_empresa,
        a.obra_cnpj,
        a.obra_cnpj_raiz,
        a.categoria_macro,
        a.obra_setor AS setor_detalhado,
        a.obra_uf,
        a.obra_municipio,
        a.capex_estimado,
        'FINANCEIRO_HISTORICO' AS capex_tipo,
        CAST(NULL AS DATE) AS data_inicio_prevista,
        CAST(NULL AS DATE) AS data_fim_prevista,
        'REGISTRADA_2026' AS situacao,
        CAST(NULL AS VARCHAR) AS url_origem,
        a.total_decisores,
        a.decisores_acionaveis,
        0 AS decisores_operacionais,
        CASE WHEN f.cnpj IS NOT NULL THEN TRUE ELSE FALSE END AS tem_match_fornecedor,
        dom.dominio_corporativo
    FROM antigas_dedup a
    LEFT JOIN fornecedores f ON a.obra_cnpj = f.cnpj
    LEFT JOIN empresa_dominios_verificados dom ON a.obra_cnpj = dom.cnpj
    WHERE NOT EXISTS (
        SELECT 1 FROM obras_oficiais_ativas n
        WHERE COALESCE(n.obra_cnpj, '') = COALESCE(a.obra_cnpj, '')
          AND norm_text(n.obra_nome) = norm_text(a.obra_nome)
    )
)
SELECT * FROM novas_fmt
UNION ALL
SELECT * FROM antigas_fmt;
""")

con.execute("CREATE INDEX IF NOT EXISTS idx_toc_origem ON todas_obras_consolidadas(origem_registro, categoria_macro);")
con.execute("CREATE INDEX IF NOT EXISTS idx_toc_uf ON todas_obras_consolidadas(obra_uf);")
con.execute("CREATE INDEX IF NOT EXISTS idx_toc_cnpj ON todas_obras_consolidadas(obra_cnpj);")

resumo = con.execute("""
SELECT
    origem_registro,
    status_validacao_fonte,
    categoria_macro,
    COUNT(*) AS qtd_obras,
    SUM(CASE WHEN decisores_acionaveis > 0 THEN 1 ELSE 0 END) AS com_acionavel,
    SUM(CASE WHEN dominio_corporativo IS NOT NULL THEN 1 ELSE 0 END) AS com_dominio
FROM todas_obras_consolidadas
GROUP BY 1, 2, 3
ORDER BY 1, 3;
""").fetchdf()

total = con.execute("SELECT COUNT(*) FROM todas_obras_consolidadas").fetchone()[0]
con.execute(f"COPY todas_obras_consolidadas TO '{OUT_ALL_CSV}' (HEADER, DELIMITER ',');")
con.execute("ANALYZE;")
con.execute("CHECKPOINT;")
con.close()

print(f"Total unificado em todas_obras_consolidadas (sem duplicidade): {total:,}")
print(resumo.to_string(index=False))
