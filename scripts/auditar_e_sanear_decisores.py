import csv
import os
import re
import subprocess
import sys
import unicodedata
import duckdb

BASE_DIR = r"C:\Users\kbadmin\Documents\Projetos\01_Ecossistema_WiNS\Engenharia"
MAIN_DB = os.path.join(BASE_DIR, "Banco_Dados", "wins_engenharia.duckdb")
OUT_AUDIT = os.path.join(BASE_DIR, "Arquivos_Tratados", "auditoria_cientista_dados_decisores.csv")

PJ_OR_NOISE_NAME_RE = re.compile(
    r"\b(ltda|eireli|epp|s\.a\.|s/a|participa[cç][oõ]es|investimentos|empreendimentos|holdings?|"
    r"prefeitura|secretaria|munic[ií]pio|departamento|setor|comiss[aã]o|licita[cç][oõ]es?|"
    r"governo|minist[eé]rio|tribunal|c[aâ]mara|autarquia|funda[cç][aã]o|associa[cç][aã]o|"
    r"instituto|universidade|hospital|cons[oó]rcio|falido|recupera[cç][aã]o|"
    r"diretor|gerente|coordenador|comprador|suprimentos|engenharia|contato|atendimento|teste)\b",
    re.I,
)
EMAIL_VALID_RE = re.compile(r"^[a-z0-9._%+\-]+@[a-z0-9.\-]+\.[a-z]{2,}$", re.I)
CONTAB_EMAIL_RE = re.compile(r"(contab|despach|assessoria|auditoria|cartorio|solucoesfisc|escritoriocont)", re.I)
NON_DECISOR_PREFIX_RE = re.compile(
    r"^(tax[_\-.]?|tax|fiscal|tributario|contabilidade|dp|rh|ouvidoria|protocolo|noreply|no-reply|sac|faleconosco|atendimento|licitacao|licitacoes|adm|admin|secretaria|gabinete|prefeito|prefeitura|info|contato|comercial|vendas)@",
    re.I,
)
ABBREV_LAST_NAME_RE = re.compile(r"\s+[A-Za-zÀ-ÿ]\.?$")


def strip_acc(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s or "") if not unicodedata.combining(c))


def norm_name(s: str) -> str:
    s = strip_acc(s or "").lower().strip()
    s = re.sub(r"\s+", " ", s)
    return s


def is_valid_proper_name(nome: str) -> tuple[bool, str]:
    n = re.sub(r"\s+", " ", (nome or "").strip())
    if not n:
        return False, "NOME_VAZIO"
    if re.search(r"\d", n):
        return False, "NOME_COM_DIGITO"
    if ABBREV_LAST_NAME_RE.search(n):
        return False, "SOBRENOME_ABREVIADO"
    if PJ_OR_NOISE_NAME_RE.search(n):
        return False, "NOME_PJ_OU_SETOR"
    # Checar S.A. / SA no fim (sem confundir com sobrenome 'Sá')
    if re.search(r"(?:,|\s)s\.?a\.?$", strip_acc(n), re.I) and " sa " not in f" {strip_acc(n).lower()} ".replace(" de sa ", " "):
        # Apenas se terminar literalmente em SA sem acento e sem ser 'de Sá'
        if not re.search(r"\bde\s+s[aá]$", n, re.I):
            return False, "NOME_PJ_SA_FINAL"
    words = re.findall(r"[A-Za-zÀ-ÿ]{2,}", n)
    if len(words) < 2:
        return False, "MENOS_DE_2_PALAVRAS"
    return True, "OK"


def clean_email(email: str) -> tuple[str | None, str]:
    e = (email or "").strip().lower()
    if not e:
        return None, "VAZIO"
    if not EMAIL_VALID_RE.match(e):
        return None, "FORMATO_INVALIDO"
    if CONTAB_EMAIL_RE.search(e):
        return None, "EMAIL_CONTABILIDADE_ASSESSORIA"
    if NON_DECISOR_PREFIX_RE.match(e):
        return None, "EMAIL_GENERICO_SETOR"
    return e, "OK"


def main() -> None:
    con = duckdb.connect(MAIN_DB)
    rows = con.execute("""
        SELECT
            rowid, id_externo, fonte, obra_empresa, obra_cnpj, obra_uf, capex_estimado,
            tipo_match, decisor_nome, decisor_cargo, decisor_email, decisor_telefone,
            decisor_linkedin, is_contato_acionavel, perfil_decisor
        FROM validacao_decisores_obras_novas
    """).fetchall()

    print(f"[ANTES] Linhas em validacao_decisores_obras_novas: {len(rows):,}")

    audit_log = []
    removed_bad_names = 0
    cleaned_emails = 0
    merged_dups = 0

    # 1. Filtrar nomes proprios validos e limpar emails invalidos/contabeis/genericos
    grouped: dict[tuple[str, str], list[dict]] = {}
    for r in rows:
        (
            rowid, oid, fonte, emp, cnpj, uf, capex,
            tmatch, nome, cargo, email, tel, lk, aci, perfil
        ) = r

        ok_name, reason_name = is_valid_proper_name(nome)
        if not ok_name:
            removed_bad_names += 1
            audit_log.append(["REMOVIDO_NOME", reason_name, oid, emp or "", nome or "", email or "", lk or ""])
            continue

        nome_clean = re.sub(r"\s+", " ", nome.strip())
        em_clean, reason_em = clean_email(email)
        if email and not em_clean:
            cleaned_emails += 1
            audit_log.append(["EMAIL_LIMPO", reason_em, oid, emp or "", nome_clean, email, lk or ""])

        tel_clean = (tel or "").strip() or None
        lk_clean = (lk or "").strip() or None
        aci_new = bool(em_clean or tel_clean or lk_clean)

        key = (oid, norm_name(nome_clean))
        grouped.setdefault(key, []).append({
            "id_externo": oid,
            "fonte": fonte,
            "obra_empresa": emp,
            "obra_cnpj": cnpj,
            "obra_uf": uf,
            "capex_estimado": capex,
            "tipo_match": tmatch,
            "decisor_nome": nome_clean,
            "decisor_cargo": (cargo or "").strip() or None,
            "decisor_email": em_clean,
            "decisor_telefone": tel_clean,
            "decisor_linkedin": lk_clean,
            "is_contato_acionavel": aci_new,
            "perfil_decisor": perfil or "5_OUTRO_NAO_CLASSIFICADO",
        })

    # 2. Deduplicar (id_externo, nome_normalizado) preservando o melhor registro e fundindo canais
    final_rows = []
    for key, items in grouped.items():
        if len(items) > 1:
            merged_dups += len(items) - 1
            audit_log.append(["DEDUP_OBRA_PESSOA", f"MERGED_{len(items)}", items[0]["id_externo"], items[0]["obra_empresa"] or "", items[0]["decisor_nome"], "", ""])

        # Ordenar pelo melhor perfil + mais canais
        items.sort(key=lambda x: (
            x["perfil_decisor"],
            -(1 if x["decisor_linkedin"] else 0),
            -(1 if x["decisor_email"] else 0),
            -(1 if x["decisor_telefone"] else 0),
        ))
        best = dict(items[0])
        for other in items[1:]:
            if not best["decisor_linkedin"] and other["decisor_linkedin"]:
                best["decisor_linkedin"] = other["decisor_linkedin"]
            if not best["decisor_email"] and other["decisor_email"]:
                best["decisor_email"] = other["decisor_email"]
            if not best["decisor_telefone"] and other["decisor_telefone"]:
                best["decisor_telefone"] = other["decisor_telefone"]
            if not best["decisor_cargo"] and other["decisor_cargo"]:
                best["decisor_cargo"] = other["decisor_cargo"]
        best["is_contato_acionavel"] = bool(best["decisor_email"] or best["decisor_telefone"] or best["decisor_linkedin"])
        final_rows.append(best)

    # 3. Reescrever validacao_decisores_obras_novas de forma atomica
    con.execute("CREATE OR REPLACE TEMP TABLE tmp_dec_clean AS SELECT * FROM validacao_decisores_obras_novas LIMIT 0;")
    con.executemany(
        """
        INSERT INTO tmp_dec_clean (
            id_externo, fonte, obra_empresa, obra_cnpj, obra_uf, capex_estimado,
            tipo_match, decisor_nome, decisor_cargo, decisor_email, decisor_telefone,
            decisor_linkedin, is_contato_acionavel, perfil_decisor
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                x["id_externo"], x["fonte"], x["obra_empresa"], x["obra_cnpj"], x["obra_uf"],
                x["capex_estimado"], x["tipo_match"], x["decisor_nome"], x["decisor_cargo"],
                x["decisor_email"], x["decisor_telefone"], x["decisor_linkedin"],
                x["is_contato_acionavel"], x["perfil_decisor"],
            )
            for x in final_rows
        ],
    )
    con.execute("DELETE FROM validacao_decisores_obras_novas;")
    con.execute("INSERT INTO validacao_decisores_obras_novas SELECT * FROM tmp_dec_clean;")
    con.execute("CHECKPOINT;")
    con.close()

    with open(OUT_AUDIT, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["acao", "motivo", "obra_id", "empresa", "nome", "email", "linkedin"])
        w.writerows(audit_log)

    print(f"[DEPOIS] Linhas limpas em validacao_decisores_obras_novas: {len(final_rows):,}")
    print(f"  - Nomes nao-proprios / PJs / setores removidos: {removed_bad_names:,}")
    print(f"  - E-mails contabeis / genericos / invalidos limpos: {cleaned_emails:,}")
    print(f"  - Duplicados (obra + nome) fundidos com preservacao de canais: {merged_dups:,}")
    print(f"  - Log de auditoria salvo em: {OUT_AUDIT}")

    # Ressincronizar todas_obras_consolidadas, campanha_por_decisor_unico, Dashboard e Excel
    subprocess.run([sys.executable, os.path.join(BASE_DIR, "scripts", "sincronizar_todas_obras_consolidadas.py")], check=True)


if __name__ == "__main__":
    main()
