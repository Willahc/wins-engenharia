import os
import re
import subprocess
import duckdb
import requests

BASE_DIR = r"C:\Users\kbadmin\Documents\Projetos\01_Ecossistema_WiNS\Engenharia"
MAIN_DB = os.path.join(BASE_DIR, "Banco_Dados", "wins_engenharia.duckdb")
SUB_DB = os.path.join(BASE_DIR, "Banco_Dados", "obras_civil_industrial_2026_2027_100k.duckdb")
OUT_DEC_CSV = os.path.join(BASE_DIR, "Arquivos_Tratados", "obras_novas_com_decisores.csv").replace("\\", "/")

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/131.0.0.0"}
BASE_MG = "https://dados.mg.gov.br/dataset/78b78e97-f94c-421e-9d2e-71b16533857d/resource"
URL_CONTRATOS = f"{BASE_MG}/0aea8831-9c53-463c-a2d3-0c6ccf87ad95/download/contratos.csv"
URL_FISCAIS = f"{BASE_MG}/f1977208-c0f0-464a-b0ff-7f93d09c0335/download/fiscais.csv"

CSV_CONTRATOS = os.path.join(BASE_DIR, "Arquivos_Tratados", "mg_contratos.csv")
CSV_FISCAIS = os.path.join(BASE_DIR, "Arquivos_Tratados", "mg_fiscais.csv")


def parse_brl(val) -> float:
    if val is None:
        return 0.0
    s = str(val).strip().replace(".", "").replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return 0.0


def clean_mun(raw: str) -> str:
    if not raw:
        return ""
    s = re.sub(r"Obra\s+\d+\s*-\s*", "", str(raw)).strip()
    return s.split(",")[0].strip()[:80]


def classify_macro(nat: str, obj: str) -> str:
    t = f"{nat or ''} {obj or ''}".lower()
    if any(k in t for k in ("saneamento", "esgoto", "agua", "energia", "subestacao", "fotovolta")):
        return "ENERGIA_E_SANEAMENTO"
    if any(k in t for k in ("rodovi", "ponte", "viaduto", "drenagem", "paviment", "infraestrutura", "aeroporto")):
        return "INFRAESTRUTURA_E_OBRAS_CIVIS"
    return "EDIFICACOES_E_COMERCIAL"


def main() -> None:
    for url, path in [(URL_CONTRATOS, CSV_CONTRATOS), (URL_FISCAIS, CSV_FISCAIS)]:
        r = requests.get(url, timeout=30, headers=HEADERS)
        r.raise_for_status()
        with open(path, "wb") as f:
            f.write(r.content)

    tmp = duckdb.connect()
    contratos = tmp.execute("""
        SELECT
            TRIM(contrato) AS contrato,
            TRIM(CAST(contrato_siad AS VARCHAR)) AS siad,
            TRIM(objeto) AS objeto,
            CAST(inicio_execucao AS DATE) AS dt_ini,
            CAST(termino_execucao AS DATE) AS dt_fim,
            TRIM(situacao) AS situacao,
            TRIM(empresa) AS empresa,
            LPAD(REGEXP_REPLACE(CAST(cnpj AS VARCHAR), '[^0-9]', '', 'g'), 14, '0') AS cnpj,
            TRIM(natureza_do_contrato) AS natureza,
            TRIM(municipios) AS municipios,
            valor_total_do_contrato
        FROM read_csv_auto(?, header=true)
        WHERE situacao IN ('Andamento', 'A Iniciar')
          AND (YEAR(termino_execucao) >= 2026 OR YEAR(data_assinatura) >= 2026)
          AND empresa IS NOT NULL
    """, [CSV_CONTRATOS]).fetchall()

    fiscais_rows = tmp.execute("""
        SELECT DISTINCT
            TRIM(contrato) AS contrato,
            TRIM(nome) AS nome,
            TRIM(COALESCE(conselho, '')) AS conselho,
            TRIM(COALESCE(cargo, '')) AS cargo
        FROM read_csv_auto(?, header=true)
        WHERE nome IS NOT NULL AND TRIM(nome) != ''
    """, [CSV_FISCAIS]).fetchall()
    tmp.close()

    fiscais_by_contrato: dict[str, list[tuple[str, str, str]]] = {}
    for ctr, nome, cons, cargo in fiscais_rows:
        fiscais_by_contrato.setdefault(ctr, []).append((nome, cons, cargo))

    con = duckdb.connect(MAIN_DB)
    existing_ids = set(r[0] for r in con.execute("SELECT id_externo FROM obras_oficiais_ativas").fetchall())

    inserted_obras = 0
    inserted_fiscais = 0
    url_orig = "https://dados.mg.gov.br/dataset/portal_obras"

    for ctr, siad, obj, dt_ini, dt_fim, sit, emp, cnpj, nat, mun_raw, val_raw in contratos:
        capex = parse_brl(val_raw)
        if capex < 100_000:
            continue
        ctr_clean = re.sub(r"[^0-9A-Za-z]", "", ctr)
        id_ext = f"MGOBRAS-{siad or ctr_clean}"
        if id_ext in existing_ids:
            continue

        cnpj_ok = cnpj if len(cnpj) == 14 and cnpj != "00000000000000" else None
        mun = clean_mun(mun_raw)
        cat = classify_macro(nat, obj)

        # Buscar telefone/email da empresa executora em fornecedores
        tel_forn, em_forn = None, None
        if cnpj_ok:
            f_row = con.execute("SELECT telefone_1, email FROM fornecedores WHERE cnpj = ? LIMIT 1", [cnpj_ok]).fetchone()
            if f_row:
                tel_forn = (f_row[0] or "").strip() or None
                em_forn = (f_row[1] or "").strip().lower() or None

        con.execute("""
            INSERT INTO obras_oficiais_ativas (
                id_externo, fonte, obra_nome, obra_empresa, obra_empresa_norm,
                obra_cnpj, obra_cnpj_raiz, categoria_macro, obra_uf, obra_municipio,
                capex_estimado, capex_tipo, data_inicio_prevista, data_fim_prevista,
                situacao, url_origem, tem_match_fornecedor, cnpj_origem_resolucao
            ) VALUES (?, 'portal_obras_mg', ?, ?, ?, ?, ?, ?, 'MG', ?, ?, 'OFICIAL_CONTRATO_MG', ?, ?, ?, ?, ?, ?)
        """, [
            id_ext, (obj or f"Contrato {ctr}")[:220], emp[:180], emp.upper()[:180],
            cnpj_ok, cnpj_ok[:8] if cnpj_ok else None, cat, mun or None,
            capex, str(dt_ini) if dt_ini else None, str(dt_fim) if dt_fim else None,
            sit, url_orig, bool(cnpj_ok), "OFICIAL_PORTAL_MG" if cnpj_ok else None
        ])
        existing_ids.add(id_ext)
        inserted_obras += 1

        # Inserir fiscais / representantes nominais vinculados a este contrato
        for idx, (fnome, fcons, fcargo) in enumerate(fiscais_by_contrato.get(ctr, [])[:4]):
            cargo_txt = f"{fcargo} ({fcons})".strip(" ()") if fcons else (fcargo or "Fiscal / Responsável Técnico")
            is_rep = "firma" in (fcargo or "").lower() or "contratada" in (fcargo or "").lower()
            dec_id = f"mg_fisc_{siad}_{idx+1}"
            acionavel = bool(tel_forn or em_forn) if is_rep else False
            con.execute("""
                INSERT INTO validacao_decisores_obras_novas (
                    id_externo, fonte, obra_nome, obra_empresa, obra_cnpj, categoria_macro,
                    obra_uf, capex_estimado, capex_tipo, url_origem, tipo_match,
                    decisor_id, decisor_nome, decisor_cargo, decisor_email, decisor_telefone,
                    decisor_linkedin, qualidade_lead, is_contato_acionavel, perfil_decisor
                ) VALUES (?, 'portal_obras_mg', ?, ?, ?, ?, 'MG', ?, 'OFICIAL_CONTRATO_MG', ?, '1_CNPJ_EXATO', ?, ?, ?, ?, ?, NULL, 'PORTAL_OBRAS_MG_FISCAL', ?, '2_GESTOR_TECNICO_OBRA')
            """, [
                id_ext, (obj or f"Contrato {ctr}")[:220], emp[:180], cnpj_ok, cat,
                capex, url_orig, dec_id, fnome[:120], cargo_txt[:120],
                em_forn if is_rep else None, tel_forn if is_rep else None, acionavel
            ])
            inserted_fiscais += 1

    # Vincular tambem decisores ja existentes da construtora em dim_decisores_empresa (deduplicados)
    con.execute("""
        INSERT INTO validacao_decisores_obras_novas
        SELECT * EXCLUDE (rn)
        FROM (
            SELECT
                o.id_externo, o.fonte, o.obra_nome, o.obra_empresa, o.obra_cnpj, o.categoria_macro,
                o.obra_uf, o.capex_estimado, o.capex_tipo, o.url_origem,
                '1_CNPJ_EXATO' AS tipo_match,
                d.decisor_id, d.nome, d.cargo, d.email, d.telefone, d.linkedin_url,
                'PORTAL_MG_CNPJ' AS qualidade_lead,
                d.is_contato_acionavel,
                CASE
                    WHEN LOWER(COALESCE(d.cargo, '')) SIMILAR TO '%(comprador|supriment|procurement|aquisi|cotac)%' THEN '1_COMPRADOR_SUPRIMENTOS'
                    WHEN LOWER(COALESCE(d.cargo, '')) SIMILAR TO '%(engenh|obra|projet|implanta|manutenc|epc|planej)%' THEN '2_GESTOR_TECNICO_OBRA'
                    ELSE '3_DIRETORIA_EXECUTIVA'
                END AS perfil_decisor,
                ROW_NUMBER() OVER (
                    PARTITION BY o.id_externo, LOWER(TRIM(d.nome)), COALESCE(LOWER(TRIM(d.email)), ''), COALESCE(LOWER(TRIM(d.linkedin_url)), '')
                    ORDER BY d.is_contato_acionavel DESC, (d.linkedin_url IS NOT NULL) DESC, d.decisor_id
                ) AS rn
            FROM obras_oficiais_ativas o
            JOIN dim_decisores_empresa d ON o.obra_cnpj = d.obra_cnpj
            WHERE o.fonte = 'portal_obras_mg'
              AND o.obra_cnpj IS NOT NULL
              AND NOT EXISTS (
                  SELECT 1 FROM validacao_decisores_obras_novas v
                  WHERE v.id_externo = o.id_externo
                    AND LOWER(TRIM(v.decisor_nome)) = LOWER(TRIM(d.nome))
              )
        )
        WHERE rn = 1;
    """)

    con.execute(f"COPY validacao_decisores_obras_novas TO '{OUT_DEC_CSV}' (HEADER, DELIMITER ',');")
    con.execute("ANALYZE;")
    con.execute("CHECKPOINT;")
    con.close()

    sub = duckdb.connect(SUB_DB)
    main_sql = MAIN_DB.replace("\\", "/")
    sub.execute(f"ATTACH '{main_sql}' AS main_db (READ_ONLY);")
    sub.execute("CREATE OR REPLACE TABLE decisores_obras_novas AS SELECT * FROM main_db.validacao_decisores_obras_novas;")
    sub.execute("CREATE OR REPLACE TABLE obras_ativas AS SELECT * FROM main_db.obras_oficiais_ativas;")
    sub.execute("DETACH main_db;")
    sub.execute("CHECKPOINT;")
    sub.close()

    print(f"Portal Obras MG inseridas: {inserted_obras} | Fiscais/Responsaveis vinculados: {inserted_fiscais}")
    subprocess.run(["python", os.path.join(BASE_DIR, "scripts", "sincronizar_todas_obras_consolidadas.py")], check=True)


if __name__ == "__main__":
    main()
