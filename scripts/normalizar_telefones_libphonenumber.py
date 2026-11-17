import os
import re
import subprocess
import duckdb
import phonenumbers
from phonenumbers import PhoneNumberType

BASE_DIR = r"C:\Users\kbadmin\Documents\Projetos\01_Ecossistema_WiNS\Engenharia"
MAIN_DB = os.path.join(BASE_DIR, "Banco_Dados", "wins_engenharia.duckdb")
SUB_DB = os.path.join(BASE_DIR, "Banco_Dados", "obras_civil_industrial_2026_2027_100k.duckdb")
OUT_CSV = os.path.join(BASE_DIR, "Arquivos_Tratados", "obras_novas_com_decisores.csv").replace("\\", "/")


def normalize_br_libphonenumber(raw: str) -> str:
    """Validate and normalize BR phone numbers via google/libphonenumber, recovering 9th digit on mobiles."""
    if not raw:
        return ""
    d = re.sub(r"\D", "", str(raw))
    if d.startswith("55") and len(d) in (12, 13):
        d = d[2:]
    if len(d) not in (10, 11) or len(set(d)) <= 2:
        return ""

    try:
        parsed = phonenumbers.parse(d, "BR")
        if phonenumbers.is_valid_number(parsed):
            return d
        if len(d) == 10 and d[0] != "0" and d[2] in "6789":
            cand = d[:2] + "9" + d[2:]
            parsed_mob = phonenumbers.parse(cand, "BR")
            if phonenumbers.is_valid_number(parsed_mob) and phonenumbers.number_type(parsed_mob) == PhoneNumberType.MOBILE:
                return cand
    except Exception:
        return ""
    return ""


def main() -> None:
    con = duckdb.connect(MAIN_DB)
    con.create_function("norm_br_phone", normalize_br_libphonenumber, ["VARCHAR"], "VARCHAR")

    before_novas = con.execute("""
        SELECT
            COUNT(*) FILTER (WHERE decisor_telefone IS NOT NULL AND TRIM(decisor_telefone) != ''),
            COUNT(*) FILTER (WHERE LENGTH(TRIM(decisor_telefone)) = 11)
        FROM validacao_decisores_obras_novas
    """).fetchone()

    con.execute("""
        UPDATE decisores
        SET
            telefone = NULLIF(norm_br_phone(telefone), ''),
            is_contato_acionavel = (
                email IS NOT NULL
                OR NULLIF(norm_br_phone(telefone), '') IS NOT NULL
                OR linkedin_url IS NOT NULL
            )
        WHERE telefone IS NOT NULL;
    """)

    con.execute("""
        UPDATE dim_decisores_empresa
        SET
            telefone = NULLIF(norm_br_phone(telefone), ''),
            is_contato_acionavel = (
                email IS NOT NULL
                OR NULLIF(norm_br_phone(telefone), '') IS NOT NULL
                OR linkedin_url IS NOT NULL
            )
        WHERE telefone IS NOT NULL;
    """)

    con.execute("""
        UPDATE validacao_decisores_obras_novas
        SET
            decisor_telefone = NULLIF(norm_br_phone(decisor_telefone), ''),
            is_contato_acionavel = (
                decisor_email IS NOT NULL
                OR NULLIF(norm_br_phone(decisor_telefone), '') IS NOT NULL
                OR decisor_linkedin IS NOT NULL
            )
        WHERE decisor_telefone IS NOT NULL;
    """)

    after_novas = con.execute("""
        SELECT
            COUNT(*) FILTER (WHERE decisor_telefone IS NOT NULL AND TRIM(decisor_telefone) != ''),
            COUNT(*) FILTER (WHERE LENGTH(TRIM(decisor_telefone)) = 11),
            COUNT(DISTINCT id_externo) FILTER (WHERE decisor_telefone IS NOT NULL),
            COUNT(DISTINCT id_externo) FILTER (WHERE is_contato_acionavel)
        FROM validacao_decisores_obras_novas
    """).fetchone()

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

    print(f"[ANTES] Linhas com telefone: {before_novas[0]:,} | Celulares 11 digitos: {before_novas[1]:,}")
    print(f"[DEPOIS] Linhas com telefone: {after_novas[0]:,} | Celulares 11 digitos: {after_novas[1]:,} | Obras c/ tel: {after_novas[2]:,} | Obras acionaveis: {after_novas[3]:,}")

    subprocess.run(["python", os.path.join(BASE_DIR, "scripts", "gerar_dashboard_html.py")], check=True)
    subprocess.run(["python", os.path.join(BASE_DIR, "scripts", "exportar_planilha_prospeccao.py")], check=True)


if __name__ == "__main__":
    main()
