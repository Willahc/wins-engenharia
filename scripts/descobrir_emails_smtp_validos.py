from concurrent.futures import ThreadPoolExecutor, as_completed
import os
import re
import unicodedata
import duckdb
from auditar_emails_smtp import check_domain_group

BASE_DIR = r"C:\Users\kbadmin\Documents\Projetos\01_Ecossistema_WiNS\Engenharia"
MAIN_DB = os.path.join(BASE_DIR, "Banco_Dados", "wins_engenharia.duckdb")

STOPWORDS = {"da", "de", "do", "das", "dos", "e", "jr", "junior", "filho", "neto", "sobrinho"}
FREE_DOMAINS = {
    "gmail.com", "hotmail.com", "hotmail.com.br", "outlook.com", "outlook.com.br",
    "live.com", "yahoo.com", "yahoo.com.br", "uol.com.br", "bol.com.br",
    "terra.com.br", "ig.com.br", "globo.com", "icloud.com", "msn.com", "zipmail.com.br",
}


def strip_acc(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s or "") if not unicodedata.combining(c))


def name_parts(nome: str) -> list[str]:
    clean = re.sub(r"[^a-z\s]", " ", strip_acc(nome).lower())
    parts = [p for p in clean.split() if len(p) >= 2 and p not in STOPWORDS]
    return parts


def detect_pattern(nome: str, email: str) -> str | None:
    if not email or "@" not in email:
        return None
    local = email.split("@")[0].lower().strip()
    parts = name_parts(nome)
    if len(parts) < 2:
        return None
    f, l = parts[0], parts[-1]
    if local == f"{f}.{l}":
        return "first.last"
    if local == f"{f}{l}":
        return "firstlast"
    if local == f"{f[0]}{l}":
        return "flast"
    if local == f"{f[0]}.{l}":
        return "f.last"
    if local == f"{f}_{l}":
        return "first_last"
    if local == f:
        return "first"
    return None


def make_candidate(nome: str, dom: str, pattern: str) -> str | None:
    parts = name_parts(nome)
    if len(parts) < 2:
        return None
    f, l = parts[0], parts[-1]
    if pattern == "first.last":
        return f"{f}.{l}@{dom}"
    if pattern == "firstlast":
        return f"{f}{l}@{dom}"
    if pattern == "flast":
        return f"{f[0]}{l}@{dom}"
    if pattern == "f.last":
        return f"{f[0]}.{l}@{dom}"
    if pattern == "first_last":
        return f"{f}_{l}@{dom}"
    return None


def main() -> None:
    con = duckdb.connect(MAIN_DB)

    # 1. Aprender padrao real por dominio a partir dos e-mails nominais ja validados na base
    known = con.execute("""
        SELECT decisor_nome, LOWER(TRIM(decisor_email)) AS em
        FROM validacao_decisores_obras_novas
        WHERE decisor_email IS NOT NULL AND decisor_email LIKE '%@%'
          AND decisor_nome IS NOT NULL
    """).fetchall()

    dom_patterns: dict[str, dict[str, int]] = {}
    for nome, em in known:
        dom = em.split("@")[1]
        if dom in FREE_DOMAINS:
            continue
        pat = detect_pattern(nome, em)
        if pat:
            dom_patterns.setdefault(dom, {})
            dom_patterns[dom][pat] = dom_patterns[dom].get(pat, 0) + 1

    best_pat_by_dom = {
        dom: max(pats.items(), key=lambda x: x[1])[0]
        for dom, pats in dom_patterns.items()
    }

    # 2. Selecionar decisores sem email em obras que ja possuem dominio_corporativo
    targets = con.execute("""
        SELECT DISTINCT
            v.id_externo,
            v.decisor_nome,
            LOWER(TRIM(t.dominio_corporativo)) AS dom
        FROM validacao_decisores_obras_novas v
        JOIN todas_obras_consolidadas t ON v.id_externo = t.obra_id
        WHERE (v.decisor_email IS NULL OR TRIM(v.decisor_email) = '')
          AND t.dominio_corporativo IS NOT NULL AND TRIM(t.dominio_corporativo) <> ''
          AND v.perfil_decisor IN ('1_COMPRADOR_SUPRIMENTOS', '2_ENGENHARIA_OBRAS_CAPEX', '2_GESTOR_TECNICO_OBRA', '3_DIRETORIA_EXECUTIVA', '4_SOCIO_QSA')
    """).fetchall()

    by_dom: dict[str, list[tuple[str, str, str]]] = {}
    for oid, nome, dom in targets:
        if dom in FREE_DOMAINS:
            continue
        pats = []
        if dom in best_pat_by_dom:
            pats.append(best_pat_by_dom[dom])
        else:
            pats.extend(["first.last", "flast"])
        for p in pats:
            cand = make_candidate(nome, dom, p)
            if cand:
                by_dom.setdefault(dom, []).append((oid, nome, cand))

    print(f"Dominios com candidatos para testar via SMTP: {len(by_dom)} | Total candidatos: {sum(len(v) for v in by_dom.values())}")

    # 3. Testar via SMTP real (aceitar SOMENTE SMTP_VALIDO em servidores nao-catchall)
    verified: dict[tuple[str, str], str] = {}
    status_counts: dict[str, int] = {}

    def run_dom(dom: str, items: list[tuple[str, str, str]]):
        unique_emails = sorted({x[2] for x in items})[:40]
        res = check_domain_group(dom, unique_emails)
        return dom, items, res

    with ThreadPoolExecutor(max_workers=12) as ex:
        futs = [ex.submit(run_dom, dom, items) for dom, items in by_dom.items()]
        for fut in as_completed(futs):
            dom, items, res = fut.result()
            valid_emails = set()
            for em, mx, st, detail in res:
                status_counts[st] = status_counts.get(st, 0) + 1
                if st == "SMTP_VALIDO":
                    valid_emails.add(em)
            if valid_emails:
                for oid, nome, cand in items:
                    if cand in valid_emails and (oid, nome) not in verified:
                        verified[(oid, nome)] = cand

    updated = 0
    for (oid, nome), em in verified.items():
        con.execute(
            """
            UPDATE validacao_decisores_obras_novas
            SET decisor_email = ?, is_contato_acionavel = TRUE
            WHERE id_externo = ? AND decisor_nome = ?
              AND (decisor_email IS NULL OR TRIM(decisor_email) = '')
            """,
            [em, oid, nome],
        )
        updated += 1

    con.execute("CHECKPOINT;")
    con.close()

    print("Distribuicao SMTP:", status_counts)
    print(f"E-mails SMTP_VALIDO (250 OK, nao-catchall) gravados no banco: {updated}")


if __name__ == "__main__":
    main()
