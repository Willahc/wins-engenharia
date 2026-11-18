import os
import duckdb

BASE_DIR = r"C:\Users\kbadmin\Documents\Projetos\01_Ecossistema_WiNS\Engenharia"
MAIN_DB = os.path.join(BASE_DIR, "Banco_Dados", "wins_engenharia.duckdb")


def apply_fase_classification(con: duckdb.DuckDBPyConnection) -> list[tuple[str, int]]:
    cols = [r[0] for r in con.execute("DESCRIBE todas_obras_consolidadas").fetchall()]
    base_select = "t.* EXCLUDE (fase_obra)" if "fase_obra" in cols else "t.*"

    con.execute(f"""
        CREATE OR REPLACE TABLE todas_obras_consolidadas AS
        SELECT
            {base_select},
            CASE
                WHEN t.fonte = 'ibama_sislic' AND t.situacao ILIKE '%Pr%via%' THEN '1_ANUNCIO_LICITACAO_LP'
                WHEN t.fonte = 'ibama_sislic' THEN '3_LI_LIBERADA_CANTEIRO'
                WHEN t.fonte = 'cimm_investimentos' THEN '1_ANUNCIO_LICITACAO_LP'
                WHEN t.fonte LIKE 'pncp_%' THEN '1_ANUNCIO_LICITACAO_LP'
                WHEN t.fonte = 'bndes_financiamento' THEN '5_FINANCIAMENTO_ATIVO'
                WHEN t.fonte = 'portal_obras_mg' AND t.situacao = 'Andamento' THEN '4_EM_EXECUCAO_ANDAMENTO'
                WHEN t.fonte = 'portal_obras_mg' THEN '2_NAO_INICIADA_INICIAL'
                WHEN t.fonte = 'aneel_siga' AND t.situacao = 'Construção' THEN '4_EM_EXECUCAO_ANDAMENTO'
                WHEN t.fonte = 'aneel_siga' THEN '2_NAO_INICIADA_INICIAL'
                WHEN t.fonte = 'convisao_cnc' AND (
                    t.situacao ILIKE '%Execu%'
                    OR REGEXP_MATCHES(LOWER(t.obra_nome), '(em execu|funda[cç]|terraplenagem|canteiro|inicia obras|come[cç]a obra|mobiliza|em andamento)')
                ) THEN '4_EM_EXECUCAO_ANDAMENTO'
                ELSE '2_NAO_INICIADA_INICIAL'
            END AS fase_obra
        FROM todas_obras_consolidadas t;
    """)

    return con.execute("""
        SELECT fase_obra, COUNT(*) AS qtd
        FROM todas_obras_consolidadas
        GROUP BY 1
        ORDER BY 1
    """).fetchall()


def main() -> None:
    con = duckdb.connect(MAIN_DB)
    res = apply_fase_classification(con)
    con.execute("ANALYZE;")
    con.execute("CHECKPOINT;")
    con.close()
    print("Distribuicao por fase_obra em todas_obras_consolidadas:")
    for fase, qtd in res:
        print(f"  {fase}: {qtd:,}")


if __name__ == "__main__":
    main()
