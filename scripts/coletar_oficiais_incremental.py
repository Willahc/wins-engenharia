import os
import re
import duckdb
from captar_todas_fontes_2026_2027 import (
    fetch_aneel_siga,
    fetch_bndes,
    fetch_obrasgov,
    fetch_pncp,
    fetch_recife_licenciamento,
)

BASE_DIR = r"C:\Users\kbadmin\Documents\Projetos\01_Ecossistema_WiNS\Engenharia"
MAIN_DB = os.path.join(BASE_DIR, "Banco_Dados", "wins_engenharia.duckdb")


def norm_title(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().lower())


def main() -> None:
    all_rows = []
    all_rows.extend(fetch_bndes())
    all_rows.extend(fetch_aneel_siga())
    all_rows.extend(fetch_pncp())
    all_rows.extend(fetch_obrasgov())
    all_rows.extend(fetch_recife_licenciamento())

    con = duckdb.connect(MAIN_DB)
    existing_ids = {r[0] for r in con.execute("SELECT id_externo FROM obras_oficiais_ativas").fetchall()}
    existing_pairs = {
        (r[0] or "", norm_title(r[1]))
        for r in con.execute("SELECT obra_cnpj, obra_nome FROM obras_oficiais_ativas").fetchall()
    }
    forn_cnpjs = {r[0] for r in con.execute("SELECT DISTINCT cnpj FROM fornecedores").fetchall()}

    inserted_by_source: dict[str, int] = {}
    for row in all_rows:
        oid = (row.get("id_externo") or "").strip()
        if not oid or oid in existing_ids:
            continue
        cnpj = (row.get("obra_cnpj") or "").strip() or None
        pair = (cnpj or "", norm_title(row.get("obra_nome") or ""))
        if pair in existing_pairs:
            continue

        raiz = cnpj[:8] if cnpj and len(cnpj) == 14 else None
        cap_tipo = "PROXY_POTENCIA_KW" if row["fonte"] == "aneel_siga" else "FINANCEIRO_REAL"
        tem_forn = bool(cnpj and cnpj in forn_cnpjs)

        con.execute(
            """
            INSERT INTO obras_oficiais_ativas (
                fonte, id_externo, obra_nome, obra_empresa, obra_cnpj, obra_cnpj_raiz,
                categoria_macro, obra_uf, obra_municipio, capex_estimado, capex_tipo,
                data_inicio_prevista, data_fim_prevista, situacao, url_origem, tem_match_fornecedor
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, TRY_CAST(? AS DATE), TRY_CAST(? AS DATE), ?, ?, ?)
            """,
            [
                row["fonte"],
                oid,
                row["obra_nome"],
                row["obra_empresa"] or None,
                cnpj,
                raiz,
                row["categoria_macro"],
                row["obra_uf"],
                row["obra_municipio"] or None,
                float(row["capex_estimado"] or 0),
                cap_tipo,
                row["data_inicio_prevista"] or None,
                row["data_fim_prevista"] or None,
                row["situacao"] or None,
                row["url_origem"],
                tem_forn,
            ],
        )
        existing_ids.add(oid)
        existing_pairs.add(pair)
        inserted_by_source[row["fonte"]] = inserted_by_source.get(row["fonte"], 0) + 1

    total_after = con.execute("SELECT COUNT(*) FROM obras_oficiais_ativas").fetchone()[0]
    con.execute("CHECKPOINT;")
    con.close()

    total_new = sum(inserted_by_source.values())
    print(f"\n[OFICIAIS INCREMENTAL] Novas obras inseridas: {total_new} | Total obras_oficiais_ativas: {total_after:,}")
    for src, cnt in sorted(inserted_by_source.items(), key=lambda x: -x[1]):
        print(f"  + {src}: {cnt}")


if __name__ == "__main__":
    main()
