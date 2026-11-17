import csv
import os
import subprocess
import duckdb

BASE_DIR = r"C:\Users\kbadmin\Documents\Projetos\01_Ecossistema_WiNS\Engenharia"
MAIN_DB = os.path.join(BASE_DIR, "Banco_Dados", "wins_engenharia.duckdb")
SUB_DB = os.path.join(BASE_DIR, "Banco_Dados", "obras_civil_industrial_2026_2027_100k.duckdb")
RET_CSV = os.path.join(BASE_DIR, "Arquivos_Tratados", "retorno_openbot_validar_linkedin.csv")
OUT_CSV = os.path.join(BASE_DIR, "Arquivos_Tratados", "obras_novas_com_decisores.csv").replace("\\", "/")


def main() -> None:
    if not os.path.exists(RET_CSV):
        print(f"Arquivo de retorno nao encontrado: {RET_CSV}")
        return

    updates = []
    removals = []
    with open(RET_CSV, "r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            status = (row.get("status_validacao") or "").strip().upper()
            atual = (row.get("linkedin_atual") or "").strip()
            novo = (row.get("linkedin_validado") or "").strip()
            if not atual:
                continue
            if status == "INVALIDO":
                removals.append((atual,))
            elif status == "CORRIGIDO" and "/in/" in novo.lower():
                updates.append((novo, atual))

    if not updates and not removals:
        print("Nenhuma correcao (CORRIGIDO) ou remocao (INVALIDO) encontrada no retorno.")
        return

    con = duckdb.connect(MAIN_DB)
    for lk_old, in removals:
        for tbl, col in [
            ("decisores", "linkedin_url"),
            ("dim_decisores_empresa", "linkedin_url"),
            ("validacao_decisores_obras_novas", "decisor_linkedin"),
        ]:
            con.execute(f"UPDATE {tbl} SET {col} = NULL WHERE {col} = ?", [lk_old])

    for lk_new, lk_old in updates:
        for tbl, col in [
            ("decisores", "linkedin_url"),
            ("dim_decisores_empresa", "linkedin_url"),
            ("validacao_decisores_obras_novas", "decisor_linkedin"),
        ]:
            con.execute(f"UPDATE {tbl} SET {col} = ? WHERE {col} = ?", [lk_new, lk_old])

    # Recalcular is_contato_acionavel
    con.execute("""
        UPDATE validacao_decisores_obras_novas
        SET is_contato_acionavel = (
            decisor_email IS NOT NULL
            OR decisor_telefone IS NOT NULL
            OR decisor_linkedin IS NOT NULL
        );
    """)
    con.execute(f"COPY validacao_decisores_obras_novas TO '{OUT_CSV}' (HEADER, DELIMITER ',');")
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

    print(f"Aplicado: {len(updates)} LinkedIns corrigidos, {len(removals)} LinkedIns invalidos removidos.")
    subprocess.run(["python", os.path.join(BASE_DIR, "scripts", "gerar_dashboard_html.py")], check=True)


if __name__ == "__main__":
    main()
