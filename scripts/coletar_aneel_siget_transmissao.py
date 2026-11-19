import csv
import io
import os
import re
from datetime import datetime
import duckdb
import requests

BASE_DIR = r"C:\Users\kbadmin\Documents\Projetos\01_Ecossistema_WiNS\Engenharia"
MAIN_DB = os.path.join(BASE_DIR, "Banco_Dados", "wins_engenharia.duckdb")

URL_OBRAS = "https://dadosabertos.aneel.gov.br/dataset/beefe870-7452-4830-a7b0-6611e3d5eff6/resource/a1366325-1071-4eeb-94bd-27915747b177/download/siget-contrato-empreendimento-obra-modulo.csv"
URL_AGENTES = "https://dadosabertos.aneel.gov.br/dataset/beefe870-7452-4830-a7b0-6611e3d5eff6/resource/60e111c3-6ee1-412e-abe3-bc15af897537/download/siget-contrato-agente.csv"
URL_ORIGEM = "https://dadosabertos.aneel.gov.br/dataset/sistema-de-gestao-da-transmissao-siget"


def parse_br_date(s: str) -> str | None:
    s = (s or "").strip()
    m = re.match(r"^(\d{2})/(\d{2})/(\d{4})$", s)
    if m:
        return f"{m.group(3)}-{m.group(2)}-{m.group(1)}"
    if re.match(r"^\d{4}-\d{2}-\d{2}$", s):
        return s
    return None


def parse_br_float(s: str) -> float:
    s = (s or "").strip().replace(".", "").replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return 0.0


def main() -> None:
    r_ag = requests.get(URL_AGENTES, timeout=30, headers={"User-Agent": "WiNS-Engenharia-Sync/1.0"})
    r_ag.raise_for_status()
    ag_map: dict[str, dict] = {}
    for r in csv.DictReader(io.StringIO(r_ag.content.decode("utf-8-sig", errors="replace")), delimiter=";"):
        ccd = (r.get("IdeCcd") or "").strip()
        if not ccd:
            continue
        cnpj_raw = re.sub(r"\D", "", r.get("NumCNPJ") or "")
        cnpj = cnpj_raw.zfill(14) if 11 <= len(cnpj_raw) <= 14 else ""
        ag_map[ccd] = {
            "empresa": (r.get("DscRazaoSocial") or "").strip()[:250],
            "cnpj": cnpj if len(cnpj) == 14 else "",
            "uf": (r.get("SigUF") or "").strip().upper()[:2],
            "mun": (r.get("NomMunicipio") or "").strip()[:120],
        }

    r_ob = requests.get(URL_OBRAS, timeout=60, headers={"User-Agent": "WiNS-Engenharia-Sync/1.0"})
    r_ob.raise_for_status()

    # Agregar modulos ativos ("Em andamento" / "Planejado") por Empreendimento (IdeEpd)
    today_iso = datetime.now().strftime("%Y-%m-%d")
    epds: dict[str, dict] = {}
    for r in csv.DictReader(io.StringIO(r_ob.content.decode("utf-8-sig", errors="replace")), delimiter=";"):
        sit = (r.get("DscSituacaoEpd") or "").strip()
        if sit not in ("Em andamento", "Planejado"):
            continue
        ide_epd = (r.get("IdeEpd") or "").strip()
        if not ide_epd:
            continue
        dt_opr = parse_br_date(r.get("DatOprComEpd") or "")
        if dt_opr and dt_opr < "2026-01-01":
            continue
        ccd = (r.get("IdeCcdProprietario") or r.get("IdeCcd") or "").strip()
        ag = ag_map.get(ccd, {})
        rap = parse_br_float(r.get("VlrHisRct") or "0")

        if ide_epd not in epds:
            nom = (r.get("NomEpd") or "").strip()
            dsc = (r.get("DscEpd") or "").strip()
            epds[ide_epd] = {
                "id_externo": f"SIGET-{ide_epd}",
                "obra_nome": f"{nom} — {dsc}"[:500] if dsc else nom[:500],
                "obra_empresa": ag.get("empresa") or "",
                "obra_cnpj": ag.get("cnpj") or "",
                "obra_uf": ag.get("uf") or "",
                "obra_municipio": ag.get("mun") or "",
                "capex_estimado": max(rap * 8.0, 1000000.0) if rap > 0 else 0.0,
                "dt_ini": parse_br_date(r.get("DatCaoCgmAtoLgl") or "") or today_iso,
                "dt_fim": dt_opr,
                "situacao": sit,
                "modulos": 1,
            }
        else:
            epds[ide_epd]["modulos"] += 1

    print(f"[ANEEL SIGET] Empreendimentos de transmissao ativos (2026+): {len(epds)}")

    con = duckdb.connect(MAIN_DB)
    existing_ids = {r[0] for r in con.execute("SELECT id_externo FROM obras_oficiais_ativas").fetchall()}
    forn_cnpjs = {r[0] for r in con.execute("SELECT DISTINCT cnpj FROM fornecedores").fetchall()}

    inserted = 0
    for epd in epds.values():
        oid = epd["id_externo"]
        if oid in existing_ids or not epd["obra_uf"]:
            continue
        cnpj = epd["obra_cnpj"] or None
        raiz = cnpj[:8] if cnpj and len(cnpj) == 14 else None
        con.execute(
            """
            INSERT INTO obras_oficiais_ativas (
                fonte, id_externo, obra_nome, obra_empresa, obra_cnpj, obra_cnpj_raiz,
                categoria_macro, obra_uf, obra_municipio, capex_estimado, capex_tipo,
                data_inicio_prevista, data_fim_prevista, situacao, url_origem, tem_match_fornecedor
            ) VALUES ('aneel_transmissao', ?, ?, ?, ?, ?, 'INDUSTRIAL', ?, ?, ?, 'ESTIMATIVA_RAP_SIGET', TRY_CAST(? AS DATE), TRY_CAST(? AS DATE), ?, ?, ?)
            """,
            [
                oid,
                f"{epd['obra_nome']} ({epd['modulos']} modulos)"[:500],
                epd["obra_empresa"] or None,
                cnpj,
                raiz,
                epd["obra_uf"],
                epd["obra_municipio"] or None,
                epd["capex_estimado"],
                epd["dt_ini"],
                epd["dt_fim"],
                epd["situacao"],
                URL_ORIGEM,
                bool(cnpj and cnpj in forn_cnpjs),
            ],
        )
        inserted += 1

    con.execute("CHECKPOINT;")
    con.close()
    print(f"[ANEEL SIGET] Novos empreendimentos inseridos em obras_oficiais_ativas: {inserted}")


if __name__ == "__main__":
    main()
