import csv
import os
import re
import duckdb

BASE_DIR = r"C:\Users\kbadmin\Documents\Projetos\01_Ecossistema_WiNS\Engenharia"
MAIN_DB = os.path.join(BASE_DIR, "Banco_Dados", "wins_engenharia.duckdb")
OUT_CSV = os.path.join(BASE_DIR, "Arquivos_Tratados", "fila_openbot_decisores_sem_linkedin.csv")

INST_OR_PJ_RE = re.compile(
    r"\b(setor|equipe|divis[aã]o|secretaria|prefeitura|licita[cç][oõ]es|departamento|comiss[aã]o|ltda|s\.?a\.?|s/a|s\.?l\.?|eireli|holding|participa[cç][oõ]es|energia\s+renov[aá]vel)\b",
    re.I,
)


def is_real_person_name(nome: str) -> bool:
    if not nome or INST_OR_PJ_RE.search(nome):
        return False
    parts = re.findall(r"[A-Za-zÀ-ÿ]{2,}", nome)
    return len(parts) >= 2


def main() -> None:
    con = duckdb.connect(MAIN_DB, read_only=True)
    rows = con.execute("""
        SELECT
            LOWER(TRIM(v.decisor_nome)) AS nome_key,
            ANY_VALUE(v.decisor_nome) AS decisor_nome,
            ANY_VALUE(v.decisor_cargo) AS decisor_cargo,
            MIN(v.perfil_decisor) AS perfil_decisor,
            ANY_VALUE(v.obra_empresa) AS obra_empresa,
            ANY_VALUE(v.obra_cnpj) AS obra_cnpj,
            MAX(CASE WHEN v.decisor_email IS NOT NULL AND TRIM(v.decisor_email) != '' THEN 1 ELSE 0 END) AS tem_email,
            MAX(CASE WHEN v.decisor_telefone IS NOT NULL AND TRIM(v.decisor_telefone) != '' THEN 1 ELSE 0 END) AS tem_tel,
            MAX(CASE WHEN v.decisor_linkedin IS NOT NULL AND TRIM(v.decisor_linkedin) != '' THEN 1 ELSE 0 END) AS tem_lk,
            COUNT(DISTINCT v.id_externo) AS qtd_obras,
            COALESCE(SUM(v.capex_estimado), 0) AS capex_total
        FROM validacao_decisores_obras_novas v
        WHERE v.decisor_nome IS NOT NULL AND TRIM(v.decisor_nome) != ''
          AND v.decisor_cargo IS NOT NULL AND TRIM(v.decisor_cargo) != ''
        GROUP BY 1
        HAVING tem_lk = 0
        ORDER BY
            CASE
                WHEN MIN(v.perfil_decisor) IN ('1_COMPRADOR_SUPRIMENTOS', '2_GESTOR_TECNICO_OBRA') THEN 1
                WHEN MIN(v.perfil_decisor) = '3_DIRETORIA_EXECUTIVA' THEN 2
                ELSE 3
            END,
            (tem_email = 0 AND tem_tel = 0) DESC,
            qtd_obras DESC,
            capex_total DESC
    """).fetchall()
    con.close()

    clean = [r for r in rows if is_real_person_name(r[1])]
    comp_eng = sum(1 for r in clean if r[3] in ("1_COMPRADOR_SUPRIMENTOS", "2_GESTOR_TECNICO_OBRA"))
    zero_ch = sum(1 for r in clean if r[6] == 0 and r[7] == 0)

    with open(OUT_CSV, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow([
            "prioridade",
            "cnpj",
            "empresa",
            "decisor_nome",
            "decisor_cargo",
            "perfil_decisor",
            "tem_email",
            "tem_telefone",
            "qtd_obras",
            "capex_total",
        ])
        for idx, r in enumerate(clean, 1):
            w.writerow([idx, r[5] or "", r[4] or "", r[1], r[2], r[3], r[6], r[7], r[9], round(r[10], 2)])

    print(f"Fila gerada: {OUT_CSV} ({len(clean):,} decisores PF sem LinkedIn | Compras/Eng: {comp_eng} | Zero canais: {zero_ch})")
    print("Top 10 da fila:")
    for idx, r in enumerate(clean[:10], 1):
        print(f"  #{idx} ({r[9]} obras, ch={r[6]+r[7]}) | {r[1]} | {r[2]} | {r[4]}")


if __name__ == "__main__":
    main()
