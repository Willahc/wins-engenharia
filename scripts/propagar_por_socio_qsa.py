import os
import subprocess
import duckdb

BASE_DIR = r"C:\Users\kbadmin\Documents\Projetos\01_Ecossistema_WiNS\Engenharia"
MAIN_DB = os.path.join(BASE_DIR, "Banco_Dados", "wins_engenharia.duckdb")

con = duckdb.connect(MAIN_DB)

before_ce = con.execute("SELECT COUNT(*) FROM todas_obras_consolidadas WHERE decisores_operacionais > 0").fetchone()[0]

# 1. Propagacao segura por Socio/Administrador/Diretor em comum (nome completo >= 3 palavras)
con.execute("""
CREATE OR REPLACE TEMP TABLE prop_socio AS
WITH obras_com_ce AS (
    SELECT DISTINCT id_externo
    FROM validacao_decisores_obras_novas
    WHERE perfil_decisor IN ('1_COMPRADOR_SUPRIMENTOS', '2_GESTOR_TECNICO_OBRA', '2_ENGENHARIA_OBRAS_CAPEX')
      AND is_contato_acionavel = TRUE
),
socios_em_com_ce AS (
    SELECT DISTINCT
        LOWER(TRIM(v.decisor_nome)) AS socio_norm,
        v.id_externo AS obra_doadora
    FROM validacao_decisores_obras_novas v
    JOIN obras_com_ce c ON v.id_externo = c.id_externo
    WHERE v.perfil_decisor IN ('3_DIRETORIA_EXECUTIVA', '4_SOCIO_QSA')
      AND LENGTH(TRIM(v.decisor_nome)) >= 16
      AND ARRAY_LENGTH(STRING_SPLIT(TRIM(v.decisor_nome), ' ')) >= 3
),
obras_sem_ce AS (
    SELECT t.*
    FROM todas_obras_consolidadas t
    WHERE t.decisores_operacionais = 0
      AND t.fonte IN ('aneel_siga', 'aneel_transmissao', 'bndes_financiamento', 'debentures_infra', 'convisao_cnc', 'ibama_sislic', 'cimm_investimentos')
),
ponte_obras AS (
    SELECT DISTINCT
        s.obra_id AS id_externo_destino,
        sc.obra_doadora
    FROM obras_sem_ce s
    JOIN validacao_decisores_obras_novas v_dest ON s.obra_id = v_dest.id_externo
    JOIN socios_em_com_ce sc ON LOWER(TRIM(v_dest.decisor_nome)) = sc.socio_norm
    WHERE v_dest.perfil_decisor IN ('3_DIRETORIA_EXECUTIVA', '4_SOCIO_QSA')
),
decisores_doadores AS (
    SELECT
        p.id_externo_destino,
        v.decisor_id,
        v.decisor_nome,
        v.decisor_cargo,
        v.decisor_email,
        v.decisor_telefone,
        v.decisor_linkedin,
        v.qualidade_lead,
        v.is_contato_acionavel,
        v.perfil_decisor
    FROM ponte_obras p
    JOIN validacao_decisores_obras_novas v ON p.obra_doadora = v.id_externo
    WHERE v.perfil_decisor IN ('1_COMPRADOR_SUPRIMENTOS', '2_GESTOR_TECNICO_OBRA', '2_ENGENHARIA_OBRAS_CAPEX')
      AND v.is_contato_acionavel = TRUE
)
SELECT DISTINCT ON (o.obra_id, LOWER(TRIM(d.decisor_nome)))
    o.obra_id AS id_externo,
    o.fonte,
    o.obra_nome,
    o.obra_empresa,
    o.obra_cnpj,
    o.categoria_macro,
    o.obra_uf,
    o.capex_estimado,
    o.capex_tipo,
    o.url_origem,
    '11_GRUPO_SOCIO_QSA' AS tipo_match,
    d.decisor_id,
    d.decisor_nome,
    d.decisor_cargo,
    d.decisor_email,
    d.decisor_telefone,
    d.decisor_linkedin,
    d.qualidade_lead,
    d.is_contato_acionavel,
    d.perfil_decisor
FROM obras_sem_ce o
JOIN decisores_doadores d ON o.obra_id = d.id_externo_destino
ORDER BY o.obra_id, LOWER(TRIM(d.decisor_nome)), d.perfil_decisor;
""")

cnt_prop = con.execute("SELECT COUNT(*), COUNT(DISTINCT id_externo) FROM prop_socio").fetchone()
if cnt_prop[0] > 0:
    con.execute("""
        INSERT INTO validacao_decisores_obras_novas (
            id_externo, fonte, obra_nome, obra_empresa, obra_cnpj, categoria_macro,
            obra_uf, capex_estimado, capex_tipo, url_origem, tipo_match, decisor_id,
            decisor_nome, decisor_cargo, decisor_email, decisor_telefone, decisor_linkedin,
            qualidade_lead, is_contato_acionavel, perfil_decisor
        )
        SELECT
            id_externo, fonte, obra_nome, obra_empresa, obra_cnpj, categoria_macro,
            obra_uf, capex_estimado, capex_tipo, url_origem, tipo_match, decisor_id,
            decisor_nome, decisor_cargo, decisor_email, decisor_telefone, decisor_linkedin,
            qualidade_lead, is_contato_acionavel, perfil_decisor
        FROM prop_socio;
    """)

con.execute("CHECKPOINT;")
con.close()

print(f"[PROPAGACAO SOCIO QSA] +{cnt_prop[0]:,} vinculos em {cnt_prop[1]:,} obras!")

# Roda saneamento + sincronizacao final (Dashboard, Excel, score_prioridade)
subprocess.run(["python", os.path.join(BASE_DIR, "scripts", "auditar_e_sanear_decisores.py")], check=True)
