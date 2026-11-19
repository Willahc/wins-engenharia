import argparse
import csv
import os
import re
import subprocess
import sys
import duckdb
from auditar_e_sanear_decisores import is_valid_proper_name, norm_name
from higienizar_linkedin_banco import validate_linkedin_url

BASE_DIR = r"C:\Users\kbadmin\Documents\Projetos\01_Ecossistema_WiNS\Engenharia"
MAIN_DB = os.path.join(BASE_DIR, "Banco_Dados", "wins_engenharia.duckdb")


def classify_perfil(cargo: str) -> str:
    txt = (cargo or "").lower()
    if re.search(r"\b(compra|suprimento|procurement|sourcing|aquisi|supply|material|contrato|frota)\b", txt):
        return "1_COMPRADOR_SUPRIMENTOS"
    if re.search(r"\b(engenheir|obra|capex|projeto|manuten|planta|opera[cç][oõ]es|industrial|constru|infraestrutura|t[eé]cnico|implanta|site\s+manager|pmo)\b", txt):
        return "2_ENGENHARIA_OBRAS_CAPEX"
    if re.search(r"\b(diretor|ceo|cfo|coo|vp|vice|presidente|superintendente|head|gerente\s+geral)\b", txt):
        return "3_DIRETORIA_EXECUTIVA"
    if re.search(r"\b(s[oó]cio|administrador|titular|propriet[aá]rio)\b", txt):
        return "4_SOCIO_QSA"
    return "5_OUTRO_NAO_CLASSIFICADO"


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingestor validado de retornos OpenBot")
    parser.add_argument("--csv", required=True, help="Caminho do CSV de retorno do OpenBot")
    parser.add_argument("--tag", default="OPENBOT_LINKEDIN_LOTE", help="Etiqueta tipo_match")
    args = parser.parse_args()

    csv_path = args.csv if os.path.isabs(args.csv) else os.path.join(BASE_DIR, args.csv)
    with open(csv_path, "r", encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))

    con = duckdb.connect(MAIN_DB)
    obras_meta = {
        r[0]: r[1:]
        for r in con.execute(
            "SELECT obra_id, fonte, obra_empresa, obra_cnpj, obra_uf, capex_estimado FROM todas_obras_consolidadas"
        ).fetchall()
    }

    inserted = 0
    updated = 0
    rejected = 0
    obras_atingidas = set()

    for r in rows:
        oid = (r.get("obra_id") or "").strip()
        if oid not in obras_meta:
            rejected += 1
            continue
        nome = re.sub(r"\s+", " ", (r.get("decisor_nome") or "").strip())
        ok_name, _ = is_valid_proper_name(nome)
        lk = validate_linkedin_url(r.get("decisor_linkedin") or "", nome)
        if not ok_name or not lk:
            rejected += 1
            continue

        fonte, emp, cnpj, uf, capex = obras_meta[oid]
        cargo = (r.get("decisor_cargo") or "").strip() or None
        email = (r.get("decisor_email") or "").strip().lower() or None
        tel = (r.get("decisor_telefone") or "").strip() or None

        existing = con.execute(
            "SELECT rowid, decisor_linkedin FROM validacao_decisores_obras_novas WHERE id_externo = ? AND LOWER(TRIM(decisor_nome)) = LOWER(TRIM(?))",
            [oid, nome],
        ).fetchall()

        if existing:
            con.execute(
                """
                UPDATE validacao_decisores_obras_novas
                SET decisor_linkedin = COALESCE(NULLIF(TRIM(decisor_linkedin), ''), ?),
                    decisor_cargo = COALESCE(NULLIF(TRIM(decisor_cargo), ''), ?),
                    is_contato_acionavel = TRUE
                WHERE id_externo = ? AND LOWER(TRIM(decisor_nome)) = LOWER(TRIM(?))
                """,
                [lk, cargo, oid, nome],
            )
            updated += 1
            obras_atingidas.add(oid)
            continue

        perfil = classify_perfil(cargo)
        con.execute(
            """
            INSERT INTO validacao_decisores_obras_novas (
                id_externo, fonte, obra_empresa, obra_cnpj, obra_uf, capex_estimado,
                tipo_match, decisor_nome, decisor_cargo, decisor_email, decisor_telefone,
                decisor_linkedin, is_contato_acionavel, perfil_decisor
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, TRUE, ?)
            """,
            [oid, fonte, emp, cnpj, uf, capex, args.tag, nome, cargo, email, tel, lk, perfil],
        )
        inserted += 1
        obras_atingidas.add(oid)

    con.execute("CHECKPOINT;")
    con.close()

    print(f"[INGESTAO OPENBOT] Lidas: {len(rows)} | Inseridas: {inserted} | Atualizadas: {updated} | Rejeitadas: {rejected} | Obras atingidas: {len(obras_atingidas)}")

    subprocess.run([sys.executable, os.path.join(BASE_DIR, "scripts", "descobrir_emails_smtp_validos.py")], check=True)
    subprocess.run([sys.executable, os.path.join(BASE_DIR, "scripts", "auditar_e_sanear_decisores.py")], check=True)
    subprocess.run([sys.executable, os.path.join(BASE_DIR, "scripts", "gerar_fila_864_sem_linkedin.py")], check=True)


if __name__ == "__main__":
    main()
