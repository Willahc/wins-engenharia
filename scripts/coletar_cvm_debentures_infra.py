import csv
import io
import os
import re
import zipfile
import duckdb
import requests

BASE_DIR = r"C:\Users\kbadmin\Documents\Projetos\01_Ecossistema_WiNS\Engenharia"
MAIN_DB = os.path.join(BASE_DIR, "Banco_Dados", "wins_engenharia.duckdb")

CVM_ZIP_URL = "https://dados.cvm.gov.br/dados/OFERTA/DISTRIB/DADOS/oferta_distribuicao.zip"
CVM_PAGE_URL = "https://dados.cvm.gov.br/dataset/oferta-distribuicao"

EXCLUDE_FUNDS_RE = re.compile(r"\b(fundo\s+de\s+investimento|fi-?infra|fidc|fip|fii)\b", re.I)


def main() -> None:
    resp = requests.get(CVM_ZIP_URL, timeout=60, headers={"User-Agent": "WiNS-Engenharia-Sync/1.0"})
    resp.raise_for_status()
    zf = zipfile.ZipFile(io.BytesIO(resp.content))

    items = []
    with zf.open("oferta_resolucao_160.csv") as raw_f:
        reader = csv.DictReader(io.TextIOWrapper(raw_f, encoding="latin1"), delimiter=";")
        for r in reader:
            dt = (r.get("Data_Registro") or r.get("Data_requerimento") or "")[:10]
            if not dt.startswith("2026") and not dt.startswith("2027"):
                continue
            if (r.get("Titulo_incentivado") or "").strip().upper() != "S":
                continue
            emissor = (r.get("Nome_Emissor") or "").strip()
            if not emissor or EXCLUDE_FUNDS_RE.search(emissor):
                continue
            cnpj = re.sub(r"\D", "", r.get("CNPJ_Emissor") or "")
            if len(cnpj) != 14:
                continue
            try:
                val = float((r.get("Valor_Total_Registrado") or "0").replace(",", "."))
            except ValueError:
                val = 0.0
            if val <= 100000:
                continue
            req_id = (r.get("Numero_Requerimento") or r.get("Numero_Processo") or "").strip()
            if not req_id:
                continue
            dest = re.sub(r"\s+", " ", (r.get("Destinacao_recursos") or "").strip())
            vm = (r.get("Valor_Mobiliario") or "Debentures Incentivadas").strip()
            items.append({
                "id_externo": f"CVM160-{req_id}",
                "obra_nome": f"{vm} — {emissor}: {dest[:260]}" if dest and dest != "N.A." else f"{vm} Incentivadas — {emissor}",
                "obra_empresa": emissor[:250],
                "obra_cnpj": cnpj,
                "capex_estimado": val,
                "dt_ini": dt,
                "situacao": (r.get("Status_Requerimento") or "Oferta Registrada")[:120],
            })

    print(f"[CVM Debentures Incentivadas] Ofertas 2026+ de empresas operacionais: {len(items)}")

    con = duckdb.connect(MAIN_DB)
    existing_ids = {r[0] for r in con.execute("SELECT id_externo FROM obras_oficiais_ativas").fetchall()}
    forn_info = {}
    cnpjs = sorted({it["obra_cnpj"] for it in items})
    if cnpjs:
        ph = ",".join("?" for _ in cnpjs)
        for c, uf, mun in con.execute(
            f"SELECT cnpj, uf, municipio_nome FROM fornecedores WHERE cnpj IN ({ph})", cnpjs
        ).fetchall():
            forn_info[c] = (uf, mun)

    inserted = 0
    for it in items:
        if it["id_externo"] in existing_ids:
            continue
        cnpj = it["obra_cnpj"]
        uf, mun = forn_info.get(cnpj, (None, None))
        if not uf:
            try:
                mr = requests.get(f"https://minhareceita.org/{cnpj}", timeout=8)
                if mr.status_code == 200:
                    md = mr.json()
                    uf = (md.get("uf") or "").strip().upper()[:2] or None
                    mun = (md.get("municipio") or "").strip()[:120] or None
            except Exception:
                pass
        if not uf:
            continue

        con.execute(
            """
            INSERT INTO obras_oficiais_ativas (
                fonte, id_externo, obra_nome, obra_empresa, obra_cnpj, obra_cnpj_raiz,
                categoria_macro, obra_uf, obra_municipio, capex_estimado, capex_tipo,
                data_inicio_prevista, data_fim_prevista, situacao, url_origem, tem_match_fornecedor
            ) VALUES ('debentures_infra', ?, ?, ?, ?, ?, 'INDUSTRIAL', ?, ?, ?, 'FINANCEIRO_REAL', TRY_CAST(? AS DATE), NULL, ?, ?, ?)
            """,
            [
                it["id_externo"],
                it["obra_nome"][:500],
                it["obra_empresa"],
                cnpj,
                cnpj[:8],
                uf,
                mun,
                it["capex_estimado"],
                it["dt_ini"],
                it["situacao"],
                CVM_PAGE_URL,
                cnpj in forn_info,
            ],
        )
        existing_ids.add(it["id_externo"])
        inserted += 1

    con.execute("CHECKPOINT;")
    con.close()
    print(f"[CVM Debentures Incentivadas] Novas obras inseridas: {inserted}")


if __name__ == "__main__":
    main()
