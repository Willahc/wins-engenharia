import csv
import os
import re
import duckdb

BASE_DIR = r"C:\Users\kbadmin\Documents\Projetos\01_Ecossistema_WiNS\Engenharia"
MAIN_DB = os.path.join(BASE_DIR, "Banco_Dados", "wins_engenharia.duckdb")
OUT_CSV = os.path.join(BASE_DIR, "Arquivos_Tratados", "fila_openbot_descoberta_cargos_linkedin.csv")

PUBLIC_RE = re.compile(
    r"\b(municipio|prefeitura|secretaria|tribunal|ministerio|comando\s+da|comando\s+do|instituto\s+federal|universidade\s+federal|camara\s+municipal|estado\s+d[aeo]|fundacao\s+hospitalar|conselho\s+regional)\b",
    re.I,
)


def main() -> None:
    con = duckdb.connect(MAIN_DB, read_only=True)
    rows = con.execute("""
        WITH por_emp AS (
            SELECT
                o.obra_cnpj,
                ANY_VALUE(o.obra_empresa) AS obra_empresa,
                ANY_VALUE(o.obra_uf) AS uf,
                ANY_VALUE(o.categoria_macro) AS categoria,
                COUNT(DISTINCT o.id_externo) AS qtd_obras,
                MAX(o.capex_estimado) AS max_capex,
                STRING_AGG(DISTINCT v.decisor_nome, ' | ') FILTER (WHERE v.decisor_nome IS NOT NULL) AS decisores_atuais,
                BOOL_OR(v.decisor_linkedin IS NOT NULL) AS tem_lk,
                BOOL_OR(v.perfil_decisor IN ('1_COMPRADOR_SUPRIMENTOS', '2_ENGENHARIA_OBRAS_CAPEX')) AS tem_comp_eng
            FROM obras_oficiais_ativas o
            LEFT JOIN validacao_decisores_obras_novas v ON o.id_externo = v.id_externo
            WHERE o.obra_cnpj IS NOT NULL
              AND o.fonte NOT IN ('PNCP', 'TRANSFEREGOV')
            GROUP BY o.obra_cnpj
        )
        SELECT
            obra_cnpj,
            obra_empresa,
            uf,
            categoria,
            qtd_obras,
            COALESCE(max_capex, 0) AS max_capex,
            COALESCE(decisores_atuais, '') AS decisores_atuais,
            tem_comp_eng
        FROM por_emp
        WHERE NOT tem_lk
        ORDER BY max_capex DESC, qtd_obras DESC
    """).fetchall()
    con.close()

    priv = [r for r in rows if not PUBLIC_RE.search(r[1] or "")]
    with open(OUT_CSV, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow([
            "prioridade",
            "cnpj",
            "empresa",
            "uf",
            "categoria",
            "qtd_obras",
            "max_capex",
            "decisores_atuais_qsa",
            "ja_tem_compras_eng",
        ])
        for idx, r in enumerate(priv, 1):
            w.writerow([idx, r[0], r[1], r[2], r[3], r[4], round(r[5], 2), r[6], "t" if r[7] else "f"])

    vac_pos = next((i for i, r in enumerate(priv, 1) if r[0] == "19777075000101"), None)
    print(f"Fila gerada: {OUT_CSV} ({len(priv)} empresas privadas sem LinkedIn; {len(rows)-len(priv)} orgaos publicos filtrados)")
    print(f"Posicao da VACCARO (19777075000101): #{vac_pos}")


if __name__ == "__main__":
    main()
