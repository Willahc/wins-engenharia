import os
import subprocess
import duckdb

BASE_DIR = r"C:\Users\kbadmin\Documents\Projetos\01_Ecossistema_WiNS\Engenharia"
MAIN_DB = os.path.join(BASE_DIR, "Banco_Dados", "wins_engenharia.duckdb")
SUB_DB = os.path.join(BASE_DIR, "Banco_Dados", "obras_civil_industrial_2026_2027_100k.duckdb")
OUT_DEC_CSV = os.path.join(BASE_DIR, "Arquivos_Tratados", "obras_novas_com_decisores.csv").replace("\\", "/")


def main() -> None:
    con = duckdb.connect(MAIN_DB)

    before_dec = con.execute("SELECT COUNT(*) FROM validacao_decisores_obras_novas").fetchone()[0]
    before_cnc_dec = con.execute("SELECT COUNT(*) FROM validacao_decisores_obras_novas WHERE fonte = 'convisao_cnc'").fetchone()[0]
    before_cnc_obras = con.execute("SELECT COUNT(*) FROM obras_oficiais_ativas WHERE fonte = 'convisao_cnc'").fetchone()[0]

    # 1. Deduplicar obras convisao_cnc por (empresa + UF + CAPEX aproximado em milhoes), mantendo a materia mais recente
    dup_ids = [
        r[0] for r in con.execute("""
            WITH ranked AS (
                SELECT
                    id_externo,
                    ROW_NUMBER() OVER (
                        PARTITION BY LOWER(TRIM(obra_empresa)), COALESCE(obra_uf, ''), COALESCE(ROUND(capex_estimado / 1000000.0), -1)
                        ORDER BY COALESCE(data_inicio_prevista, '') DESC, id_externo DESC
                    ) AS rn
                FROM obras_oficiais_ativas
                WHERE fonte = 'convisao_cnc'
            )
            SELECT id_externo FROM ranked WHERE rn > 1
        """).fetchall()
    ]

    if dup_ids:
        con.execute("DELETE FROM obras_oficiais_ativas WHERE id_externo IN (SELECT UNNEST(?))", [dup_ids])
        con.execute("DELETE FROM todas_obras_consolidadas WHERE obra_id IN (SELECT UNNEST(?))", [dup_ids])
        con.execute("DELETE FROM validacao_decisores_obras_novas WHERE id_externo IN (SELECT UNNEST(?))", [dup_ids])

    # 2. Deduplicar decisores em validacao_decisores_obras_novas por (id_externo, nome, email, linkedin)
    con.execute("""
        CREATE OR REPLACE TABLE validacao_decisores_obras_novas AS
        SELECT * EXCLUDE (rn)
        FROM (
            SELECT
                *,
                ROW_NUMBER() OVER (
                    PARTITION BY
                        id_externo,
                        LOWER(TRIM(decisor_nome)),
                        COALESCE(LOWER(TRIM(decisor_email)), ''),
                        COALESCE(LOWER(TRIM(decisor_linkedin)), '')
                    ORDER BY
                        perfil_decisor,
                        is_contato_acionavel DESC,
                        (decisor_telefone IS NOT NULL) DESC,
                        decisor_id
                ) AS rn
            FROM validacao_decisores_obras_novas
        )
        WHERE rn = 1;
    """)

    after_dec = con.execute("SELECT COUNT(*) FROM validacao_decisores_obras_novas").fetchone()[0]
    after_cnc_dec = con.execute("SELECT COUNT(*) FROM validacao_decisores_obras_novas WHERE fonte = 'convisao_cnc'").fetchone()[0]
    after_cnc_obras = con.execute("SELECT COUNT(*) FROM obras_oficiais_ativas WHERE fonte = 'convisao_cnc'").fetchone()[0]

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

    print(f"Obras ConVisao: {before_cnc_obras} -> {after_cnc_obras} (-{len(dup_ids)} materias duplicadas)")
    print(f"Decisores ConVisao: {before_cnc_dec:,} -> {after_cnc_dec:,} | Total validacao_decisores_obras_novas: {before_dec:,} -> {after_dec:,}")

    subprocess.run(["python", os.path.join(BASE_DIR, "scripts", "sincronizar_todas_obras_consolidadas.py")], check=True)


if __name__ == "__main__":
    main()
