import csv
import os
import re
import duckdb

BASE_DIR = r"C:\Users\kbadmin\Documents\Projetos\01_Ecossistema_WiNS\Engenharia"
MAIN_DB = os.path.join(BASE_DIR, "Banco_Dados", "wins_engenharia.duckdb")
OUT_CSV = os.path.join(BASE_DIR, "Arquivos_Tratados", "fila_openbot_convisao_cimm_privadas.csv")

PUBLIC_RE = re.compile(
    r"\b(prefeitura|municipio|município|secretaria|governo\s+d[aeo]|estado\s+d[aeo]|der[\-\s]|dnit|sabesp|copasa|sanepar|embasa|compesa|seinf|seminf|delegacia|hospital\s+estadual|ministerio|ministério|exercito|exército)\b",
    re.I,
)
GENERIC_HEADLINE_RE = re.compile(
    r"^(obra\s+de|expans[aã]o\s+(industrial|hospitalar)|nova\s+(planta|f[aá]brica)|f[aá]brica\s+(pioneira|com)|fase\s+de|in[íi]cio\s+de|disputa\s+define|com\s+proposta|multinacional|metal[úu]rgica|mais\s+de|investimento)\b",
    re.I,
)


def main() -> None:
    con = duckdb.connect(MAIN_DB, read_only=True)
    rows = con.execute("""
        SELECT
            obra_id,
            fonte,
            obra_empresa,
            COALESCE(obra_cnpj, '') AS cnpj,
            COALESCE(obra_uf, '') AS uf,
            categoria_macro,
            COALESCE(capex_estimado, 0) AS capex,
            obra_nome,
            url_origem
        FROM todas_obras_consolidadas
        WHERE fonte IN ('convisao_cnc', 'cimm_investimentos')
          AND decisores_acionaveis = 0
        ORDER BY (fonte = 'cimm_investimentos') DESC, capex DESC, obra_id DESC
    """).fetchall()
    con.close()

    filtered = []
    seen_emp = set()
    for r in rows:
        emp = (r[2] or "").strip()
        txt = f"{emp} {r[7]}"
        if PUBLIC_RE.search(txt) or GENERIC_HEADLINE_RE.search(emp):
            continue
        key = emp.lower()
        if key in seen_emp:
            continue
        seen_emp.add(key)
        filtered.append(r)

    with open(OUT_CSV, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow([
            "prioridade",
            "obra_id",
            "fonte",
            "empresa",
            "cnpj",
            "uf",
            "categoria_macro",
            "capex_estimado",
            "obra_nome",
            "url_origem",
        ])
        for idx, r in enumerate(filtered, 1):
            w.writerow([idx, r[0], r[1], r[2], r[3], r[4], r[5], round(r[6], 2), r[7], r[8]])

    print(f"Fila ConVisao+CIMM gerada: {OUT_CSV} ({len(filtered)} empresas privadas nominais sem decisor)")
    print("Top 15:")
    for idx, r in enumerate(filtered[:15], 1):
        print(f"  #{idx} [{r[1]}] {r[2]} | UF={r[4]} | R$ {r[6]/1e6:,.1f}M | {r[7][:50]}")


if __name__ == "__main__":
    main()
