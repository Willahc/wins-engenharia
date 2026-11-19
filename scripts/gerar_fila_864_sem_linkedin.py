import csv
import os
import re
import duckdb

BASE_DIR = r"C:\Users\kbadmin\Documents\Projetos\01_Ecossistema_WiNS\Engenharia"
MAIN_DB = os.path.join(BASE_DIR, "Banco_Dados", "wins_engenharia.duckdb")
OUT_OBRAS_CSV = os.path.join(BASE_DIR, "Arquivos_Tratados", "fila_864_obras_sem_linkedin.csv")
OUT_EMP_CSV = os.path.join(BASE_DIR, "Arquivos_Tratados", "fila_empresas_unicas_sem_linkedin.csv")
OUT_PRIV_CSV = os.path.join(BASE_DIR, "Arquivos_Tratados", "fila_empresas_privadas_sem_linkedin.csv")

PUBLIC_ORG_RE = re.compile(
    r"\b(prefeitura|munic[ií]pio|secretaria|estado\s+de|estado\s+do|fundo\s+municipal|"
    r"c[aâ]mara\s+municipal|minist[eé]rio|governo\s+do|governo\s+de|departamento\s+de\s+estradas|"
    r"der-|dnit|defensoria|tribunal|universidade\s+federal|instituto\s+federal|autarquia)\b",
    re.I,
)
NEWS_HEADLINE_RE = re.compile(
    r"^(investimento\s+de|duplica[cç][aã]o|obra\s+de|obra\s+industrial|proposta\s+industrial|"
    r"expans[aã]o\s+industrial|aporte\s+de|multinacional|complexo\s+multiuso|cons[oó]rcio\s+estrutura|"
    r"r\$\s*\d|tecnologia\s+da|maior\s+ponte|nova\s+planta|projetos?\s+de\s+inova)",
    re.I,
)


def main() -> None:
    con = duckdb.connect(MAIN_DB, read_only=True)

    obras = con.execute("""
        WITH sem_lk AS (
            SELECT t.*
            FROM todas_obras_consolidadas t
            WHERE t.obra_id NOT IN (
                SELECT DISTINCT id_externo
                FROM validacao_decisores_obras_novas
                WHERE decisor_linkedin IS NOT NULL AND TRIM(decisor_linkedin) <> ''
            )
        ),
        dec_atual AS (
            SELECT
                id_externo,
                STRING_AGG(DISTINCT decisor_nome || ' (' || COALESCE(decisor_cargo, 'N/I') || ')', ' | ') AS nomes_sem_lk
            FROM validacao_decisores_obras_novas
            GROUP BY 1
        )
        SELECT
            s.obra_id,
            s.fonte,
            s.fase_obra,
            COALESCE(s.score_prioridade, 0) AS score,
            s.obra_empresa,
            s.obra_cnpj,
            s.obra_uf,
            s.obra_municipio,
            ROUND(COALESCE(s.capex_estimado, 0), 2) AS capex,
            s.obra_nome,
            COALESCE(d.nomes_sem_lk, '') AS decisores_atuais_sem_lk,
            s.url_origem
        FROM sem_lk s
        LEFT JOIN dec_atual d ON s.obra_id = d.id_externo
        ORDER BY COALESCE(s.score_prioridade, 0) DESC, COALESCE(s.capex_estimado, 0) DESC, s.obra_id;
    """).fetchall()

    empresas = con.execute("""
        WITH sem_lk AS (
            SELECT t.*
            FROM todas_obras_consolidadas t
            WHERE t.obra_id NOT IN (
                SELECT DISTINCT id_externo
                FROM validacao_decisores_obras_novas
                WHERE decisor_linkedin IS NOT NULL AND TRIM(decisor_linkedin) <> ''
            )
        )
        SELECT
            COALESCE(NULLIF(TRIM(obra_cnpj), ''), UPPER(TRIM(obra_empresa))) AS chave_empresa,
            ANY_VALUE(obra_empresa) AS empresa,
            ANY_VALUE(obra_cnpj) AS cnpj,
            STRING_AGG(DISTINCT obra_uf, ', ' ORDER BY obra_uf) AS ufs,
            STRING_AGG(DISTINCT fonte, ', ' ORDER BY fonte) AS fontes,
            COUNT(*) AS qtd_obras,
            ROUND(SUM(COALESCE(capex_estimado, 0)), 2) AS capex_total,
            MAX(COALESCE(score_prioridade, 0)) AS max_score,
            STRING_AGG(obra_id, ' | ') AS obra_ids
        FROM sem_lk
        WHERE obra_empresa IS NOT NULL AND TRIM(obra_empresa) <> ''
        GROUP BY 1
        ORDER BY max_score DESC, capex_total DESC, qtd_obras DESC;
    """).fetchall()

    con.close()

    with open(OUT_OBRAS_CSV, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow([
            "prioridade", "obra_id", "fonte", "fase_obra", "score_prioridade",
            "obra_empresa", "obra_cnpj", "obra_uf", "obra_municipio",
            "capex_estimado", "obra_nome", "decisores_atuais_sem_lk", "url_origem"
        ])
        for i, r in enumerate(obras, 1):
            w.writerow([i, *r])

    with open(OUT_EMP_CSV, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow([
            "prioridade", "chave_empresa", "empresa", "cnpj", "ufs",
            "fontes", "qtd_obras", "capex_total", "max_score", "obra_ids"
        ])
        for i, r in enumerate(empresas, 1):
            w.writerow([i, *r])

    privadas = [
        r for r in empresas
        if r[1]
        and not PUBLIC_ORG_RE.search(r[1])
        and not NEWS_HEADLINE_RE.search(r[1].strip())
        and len(r[1].strip()) <= 80
    ]
    with open(OUT_PRIV_CSV, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow([
            "prioridade", "chave_empresa", "empresa", "cnpj", "ufs",
            "fontes", "qtd_obras", "capex_total", "max_score", "obra_ids"
        ])
        for i, r in enumerate(privadas, 1):
            w.writerow([i, *r])

    print(f"Fila por obra gerada: {OUT_OBRAS_CSV} ({len(obras):,} obras)")
    print(f"Fila por empresa unica gerada: {OUT_EMP_CSV} ({len(empresas):,} empresas unicas)")
    print(f"Fila PRIVADA limpa (sem orgaos publicos/manchetes): {OUT_PRIV_CSV} ({len(privadas):,} empresas privadas)")
    print("\nTop 10 empresas PRIVADAS sem LinkedIn:")
    for i, r in enumerate(privadas[:10], 1):
        print(f"  #{i:02d} | Score {r[7]} | {r[5]} obra(s) | R$ {r[6]/1e6:,.1f}M | {r[1]} (CNPJ: {r[2] or 'N/D'}) | {r[3]}")


if __name__ == "__main__":
    main()
