import csv
import os
import re
import smtplib
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
import dns.resolver
import duckdb

BASE_DIR = r"C:\Users\kbadmin\Documents\Projetos\01_Ecossistema_WiNS\Engenharia"
MAIN_DB = os.path.join(BASE_DIR, "Banco_Dados", "wins_engenharia.duckdb")
SUB_DB = os.path.join(BASE_DIR, "Banco_Dados", "obras_civil_industrial_2026_2027_100k.duckdb")
BOUNCE_CSV = os.path.join(BASE_DIR, "Arquivos_Tratados", "emails_bounce_confirmados.csv")
AUDIT_CSV = os.path.join(BASE_DIR, "Arquivos_Tratados", "auditoria_smtp_emails.csv")
OUT_CSV = os.path.join(BASE_DIR, "Arquivos_Tratados", "obras_novas_com_decisores.csv").replace("\\", "/")

CONFIRMED_BOUNCES = {
    "lrocha@jlc.com",
    "julio.silva@casadosventos.com.br",
    "marcio.bernardo@usinacaete.com",
    "fabio.mba@aguaeterra.com.br",
    "eduardo.ayres@bomjesus.com",
    "peterson.gomes@bomjesus.com",
    "rogerio.carvalho@inpasa.com.br",
    "douglas.gallo@raizen.com.br",
}

CREDENTIAL_NOISE_RE = re.compile(r"\.(mba|pmp|phd|eng|msc|cfo|ceo)@", re.I)


def get_mx(dom: str) -> str:
    try:
        recs = dns.resolver.resolve(dom, "MX", lifetime=6)
        return sorted([(r.preference, str(r.exchange).rstrip(".")) for r in recs])[0][1]
    except Exception:
        return ""


def check_domain_group(dom: str, emails: list[str]) -> list[tuple[str, str, str, str]]:
    """Return list of (email, mx, status, detail) for all emails on one domain."""
    mx = get_mx(dom)
    if not mx:
        return [(em, "", "NO_MX", "Sem registro MX") for em in emails]

    results = []
    try:
        s = smtplib.SMTP(mx, 25, timeout=8)
        s.ehlo("winsengenharia.com.br")
        s.mail("check@winsengenharia.com.br")
        code_fake, msg_fake = s.rcpt(f"zzzz_nonexistent_98765@{dom}")
        fake_msg = msg_fake.decode("utf-8", errors="ignore") if isinstance(msg_fake, bytes) else str(msg_fake)

        is_ip_block = code_fake == 550 and ("5.7.1" in fake_msg or "Client host" in fake_msg or "Spamhaus" in fake_msg)
        is_catchall = code_fake == 250

        if is_ip_block:
            s.quit()
            return [(em, mx, "BLOCKED_IP", fake_msg[:100]) for em in emails]

        for em in emails:
            try:
                code, msg = s.rcpt(em)
                mtxt = msg.decode("utf-8", errors="ignore") if isinstance(msg, bytes) else str(msg)
                if is_catchall:
                    st = "CATCH_ALL"
                elif code in (250, 251):
                    st = "SMTP_VALIDO"
                elif code == 550 and any(k in mtxt.lower() for k in ("5.1.1", "5.4.1", "does not exist", "user unknown", "no such user", "recipient address rejected", "unknown user", "not found")):
                    st = "SMTP_INVALIDO"
                elif code >= 500:
                    st = f"SMTP_{code}"
                else:
                    st = f"SMTP_{code}"
                results.append((em, mx, st, mtxt[:100]))
            except Exception as e:
                results.append((em, mx, "ERR_RCPT", str(e)[:100]))
        try:
            s.quit()
        except Exception:
            pass
    except Exception as e:
        return [(em, mx, "ERR_CONN", str(e)[:100]) for em in emails]
    return results


def main() -> None:
    con = duckdb.connect(MAIN_DB)

    # 1. Remover bounces confirmados + ruido .mba@ + corrigir douglas.gallo@raizen.com.br -> .com
    for tbl, col in [
        ("decisores", "email"),
        ("dim_decisores_empresa", "email"),
        ("validacao_decisores_obras_novas", "decisor_email"),
    ]:
        con.execute(f"UPDATE {tbl} SET {col} = 'douglas.gallo@raizen.com' WHERE LOWER(TRIM({col})) = 'douglas.gallo@raizen.com.br';")

    # 2. Listar todos emails unicos restantes para auditoria SMTP
    rows = con.execute("""
        SELECT DISTINCT LOWER(TRIM(decisor_email))
        FROM validacao_decisores_obras_novas
        WHERE decisor_email IS NOT NULL AND TRIM(decisor_email) != ''
    """).fetchall()
    all_emails = [r[0] for r in rows if "@" in r[0]]

    by_dom: dict[str, list[str]] = {}
    for em in all_emails:
        dom = em.split("@", 1)[1]
        by_dom.setdefault(dom, []).append(em)

    print(f"Auditando {len(all_emails)} emails unicos em {len(by_dom)} dominios via SMTP...")
    audit_rows = []
    with ThreadPoolExecutor(max_workers=12) as ex:
        futs = [ex.submit(check_domain_group, dom, ems) for dom, ems in by_dom.items()]
        for fut in as_completed(futs):
            audit_rows.extend(fut.result())

    with open(AUDIT_CSV, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["email", "mx", "status_smtp", "detalhe"])
        for r in sorted(audit_rows):
            w.writerow(r)

    counts = {}
    to_remove = set(CONFIRMED_BOUNCES) - {"douglas.gallo@raizen.com.br"}
    for em, mx, st, det in audit_rows:
        counts[st] = counts.get(st, 0) + 1
        if st in ("SMTP_INVALIDO", "NO_MX") or CREDENTIAL_NOISE_RE.search(em):
            to_remove.add(em)

    print("Resumo SMTP:", counts)
    print(f"Total emails marcados para remocao (bounces + SMTP_INVALIDO + NO_MX + .mba/.pmp): {len(to_remove)}")

    with open(BOUNCE_CSV, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["email", "motivo"])
        for em in sorted(to_remove):
            mot = "BOUNCE_CONFIRMADO_USUARIO" if em in CONFIRMED_BOUNCES else "SMTP_INVALIDO_OU_NO_MX"
            w.writerow([em, mot])

    if to_remove:
        rem_list = list(to_remove)
        for tbl, col in [
            ("decisores", "email"),
            ("dim_decisores_empresa", "email"),
            ("validacao_decisores_obras_novas", "decisor_email"),
        ]:
            con.execute(f"UPDATE {tbl} SET {col} = NULL WHERE LOWER(TRIM({col})) IN (SELECT UNNEST(?))", [rem_list])

    con.execute("""
        UPDATE validacao_decisores_obras_novas
        SET is_contato_acionavel = (
            decisor_email IS NOT NULL
            OR decisor_telefone IS NOT NULL
            OR decisor_linkedin IS NOT NULL
        );
    """)

    after = con.execute("""
        SELECT
            COUNT(DISTINCT id_externo) AS total_obras,
            COUNT(DISTINCT id_externo) FILTER (WHERE decisor_email IS NOT NULL) AS obras_email,
            COUNT(DISTINCT LOWER(TRIM(decisor_email))) FILTER (WHERE decisor_email IS NOT NULL) AS emails_unicos,
            COUNT(DISTINCT id_externo) FILTER (WHERE is_contato_acionavel) AS acionaveis
        FROM validacao_decisores_obras_novas
    """).fetchone()

    con.execute(f"COPY validacao_decisores_obras_novas TO '{OUT_CSV}' (HEADER, DELIMITER ',');")
    con.execute("ANALYZE;")
    con.execute("CHECKPOINT;")
    con.close()

    sub = duckdb.connect(SUB_DB)
    main_sql = MAIN_DB.replace("\\", "/")
    sub.execute(f"ATTACH '{main_sql}' AS main_db (READ_ONLY);")
    sub.execute("CREATE OR REPLACE TABLE decisores_obras_novas AS SELECT * FROM main_db.validacao_decisores_obras_novas;")
    sub.execute("DETACH main_db;")
    sub.execute("CHECKPOINT;")
    sub.close()

    print(f"[DEPOIS] Obras: {after[0]:,} | Obras c/ email: {after[1]:,} | Emails unicos: {after[2]:,} | Acionaveis: {after[3]:,}")
    subprocess.run(["python", os.path.join(BASE_DIR, "scripts", "gerar_dashboard_html.py")], check=True)
    subprocess.run(["python", os.path.join(BASE_DIR, "scripts", "exportar_planilha_prospeccao.py")], check=True)


if __name__ == "__main__":
    main()
