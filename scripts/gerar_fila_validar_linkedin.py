import csv
import os
import duckdb

BASE_DIR = r"C:\Users\kbadmin\Documents\Projetos\01_Ecossistema_WiNS\Engenharia"
MAIN_DB = os.path.join(BASE_DIR, "Banco_Dados", "wins_engenharia.duckdb")
OUT_CSV = os.path.join(BASE_DIR, "Arquivos_Tratados", "fila_openbot_validar_linkedin.csv")


def main() -> None:
    con = duckdb.connect(MAIN_DB, read_only=True)

    stats = con.execute("""
        SELECT
            COUNT(DISTINCT id_externo) AS total_obras,
            COUNT(DISTINCT id_externo) FILTER (WHERE decisor_linkedin IS NOT NULL AND TRIM(decisor_linkedin) != '') AS obras_com_lk,
            COUNT(DISTINCT decisor_linkedin) FILTER (WHERE decisor_linkedin IS NOT NULL AND TRIM(decisor_linkedin) != '') AS lks_unicos
        FROM validacao_decisores_obras_novas
    """).fetchone()

    rows = con.execute("""
        WITH base AS (
            SELECT
                decisor_linkedin,
                ANY_VALUE(decisor_nome) AS decisor_nome,
                ANY_VALUE(decisor_cargo) AS decisor_cargo,
                ANY_VALUE(obra_empresa) AS obra_empresa,
                STRING_AGG(DISTINCT tipo_match, ',') AS origens,
                COUNT(DISTINCT id_externo) AS qtd_obras
            FROM validacao_decisores_obras_novas
            WHERE decisor_linkedin IS NOT NULL AND TRIM(decisor_linkedin) != ''
            GROUP BY decisor_linkedin
        )
        SELECT
            ROW_NUMBER() OVER (ORDER BY qtd_obras DESC, decisor_nome) AS prioridade,
            decisor_nome,
            decisor_cargo,
            obra_empresa,
            decisor_linkedin,
            qtd_obras,
            origens
        FROM base
        WHERE origens NOT LIKE '%OPENBOT%'
        ORDER BY qtd_obras DESC, decisor_nome
    """).fetchall()

    with open(OUT_CSV, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow([
            "prioridade",
            "decisor_nome",
            "decisor_cargo",
            "obra_empresa",
            "linkedin_atual",
            "qtd_obras",
            "origens",
            "status_validacao",
            "linkedin_validado",
            "observacao",
        ])
        for r in rows:
            writer.writerow([r[0], r[1], r[2], r[3], r[4], r[5], r[6], "", "", ""])

    con.close()
    print(f"Obras totais: {stats[0]:,} | Obras com LinkedIn: {stats[1]:,} | LinkedIns unicos: {stats[2]:,}")
    print(f"Fila gerada: {OUT_CSV} ({len(rows):,} LinkedIns nao-OpenBot para validar)")
    print("Top 10 por impacto (qtd_obras):")
    for r in rows[:10]:
        print(f"  #{r[0]} ({r[5]} obras) | {r[1]} | {r[3]} | {r[4]}")


if __name__ == "__main__":
    main()
