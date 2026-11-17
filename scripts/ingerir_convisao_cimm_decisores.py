import csv
import os
import subprocess
import duckdb

BASE_DIR = r"C:\Users\kbadmin\Documents\Projetos\01_Ecossistema_WiNS\Engenharia"
MAIN_DB = os.path.join(BASE_DIR, "Banco_Dados", "wins_engenharia.duckdb")
SUB_DB = os.path.join(BASE_DIR, "Banco_Dados", "obras_civil_industrial_2026_2027_100k.duckdb")
RET_CSV = os.path.join(BASE_DIR, "Arquivos_Tratados", "retorno_openbot_convisao_cimm.csv")
OUT_DEC_CSV = os.path.join(BASE_DIR, "Arquivos_Tratados", "obras_novas_com_decisores.csv").replace("\\", "/")


def classify_perfil(cargo: str) -> str:
    c = (cargo or "").lower()
    if any(k in c for k in ("comprador", "supriment", "procurement", "aquisi", "cotac", "supply chain", "sourcing")):
        return "1_COMPRADOR_SUPRIMENTOS"
    if any(k in c for k in ("engenh", "obra", "projet", "implanta", "manutenc", "epc", "planej", "industrial", "opera")):
        return "2_GESTOR_TECNICO_OBRA"
    return "3_DIRETORIA_EXECUTIVA"


def main() -> None:
    if not os.path.exists(RET_CSV):
        print(f"Arquivo nao encontrado: {RET_CSV}")
        return

    con = duckdb.connect(MAIN_DB)
    existing = set(
        (r[0], (r[1] or "").strip().lower())
        for r in con.execute("SELECT id_externo, decisor_nome FROM validacao_decisores_obras_novas").fetchall()
    )

    inserted = 0
    with open(RET_CSV, "r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            obra_id = (row.get("obra_id") or "").strip()
            nome = (row.get("decisor_nome") or "").strip()
            cargo = (row.get("decisor_cargo") or "").strip()
            lk = (row.get("decisor_linkedin") or "").strip() or None
            em = (row.get("decisor_email") or "").strip().lower() or None
            tel = (row.get("decisor_telefone") or "").strip() or None
            if not obra_id or not nome or not (lk or em or tel):
                continue
            if (obra_id, nome.lower()) in existing:
                continue

            obra = con.execute("""
                SELECT fonte, obra_nome, obra_empresa, obra_cnpj, categoria_macro, obra_uf,
                       capex_estimado, capex_tipo, url_origem
                FROM todas_obras_consolidadas
                WHERE obra_id = ?
                LIMIT 1
            """, [obra_id]).fetchone()
            if not obra:
                continue

            dec_id = f"ob_cc_{abs(hash((obra_id, nome.lower())))}"
            perfil = classify_perfil(cargo)
            con.execute("""
                INSERT INTO validacao_decisores_obras_novas (
                    id_externo, fonte, obra_nome, obra_empresa, obra_cnpj, categoria_macro,
                    obra_uf, capex_estimado, capex_tipo, url_origem, tipo_match,
                    decisor_id, decisor_nome, decisor_cargo, decisor_email, decisor_telefone,
                    decisor_linkedin, qualidade_lead, is_contato_acionavel, perfil_decisor
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '9_OPENBOT_COMPRAS_ENG', ?, ?, ?, ?, ?, ?, 'OPENBOT_CONVISAO_CIMM', TRUE, ?)
            """, [
                obra_id, obra[0], obra[1], obra[2], obra[3], obra[4],
                obra[5], obra[6], obra[7], obra[8],
                dec_id, nome, cargo, em, tel, lk, perfil,
            ])
            existing.add((obra_id, nome.lower()))
            inserted += 1

    con.execute(f"COPY validacao_decisores_obras_novas TO '{OUT_DEC_CSV}' (HEADER, DELIMITER ',');")
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

    print(f"Decisores ConVisao/CIMM inseridos: {inserted}")
    subprocess.run(["python", os.path.join(BASE_DIR, "scripts", "sincronizar_todas_obras_consolidadas.py")], check=True)


if __name__ == "__main__":
    main()
