import os
import re
import subprocess
import sys
import unicodedata
import duckdb
import requests
from rapidfuzz import fuzz

BASE_DIR = r"C:\Users\kbadmin\Documents\Projetos\01_Ecossistema_WiNS\Engenharia"
MAIN_DB = os.path.join(BASE_DIR, "Banco_Dados", "wins_engenharia.duckdb")

LEGAL_SUFFIX_RE = re.compile(
    r"\b(ltda|s\.?a\.?|s/a|eireli|me|epp|spe|cia|companhia|brasil|do\s+brasil|grupo)\b",
    re.I,
)
BAD_TITLE_NOISE_RE = re.compile(
    r"^(expansao|obra\s+de|inicio\s+de|nova\s+planta|fase\s+de|disputa\s+define|com\s+proposta|fabricante\s+de|investimento|construcao\s+de|ampliacao\s+de|duplicacao|prefeitura|governo|ministerio|secretaria|consorcio\s+estrutura|aporte\s+de|multinacional|complexo|tecnologia\s+da|com\s+r\$|r\$|maior\s+ponte)",
    re.I,
)
GENERIC_FIRST_TOKENS = {"GRUPO", "CONSTRUTORA", "ENGENHARIA", "CONSTRUCOES", "SERVICOS", "USINA", "EMPRESA", "COMPANHIA", "UNIDADE", "NOVA", "NOVO", "ENERGIA", "ALIMENTOS"}


def distinctive_tokens(core: str) -> list[str]:
    return [t for t in core.split() if len(t) >= 2 and t not in GENERIC_FIRST_TOKENS]


def strip_acc(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s or "") if not unicodedata.combining(c))


def clean_core(s: str) -> str:
    s = strip_acc(s or "").upper()
    s = LEGAL_SUFFIX_RE.sub(" ", s)
    s = re.sub(r"[^A-Z0-9\s]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def pick_anchor_token(core: str) -> str | None:
    tokens = [t for t in core.split() if len(t) >= 4 and t not in GENERIC_FIRST_TOKENS]
    if not tokens:
        tokens = [t for t in core.split() if len(t) >= 4]
    return max(tokens, key=len) if tokens else None


def main() -> None:
    con = duckdb.connect(MAIN_DB)

    targets_raw = con.execute("""
        SELECT obra_id, obra_empresa, obra_uf, capex_estimado
        FROM todas_obras_consolidadas
        WHERE fonte = 'convisao_cnc'
          AND (obra_cnpj IS NULL OR TRIM(obra_cnpj) = '')
          AND obra_empresa IS NOT NULL AND TRIM(obra_empresa) <> ''
        ORDER BY COALESCE(capex_estimado, 0) DESC
    """).fetchall()

    targets = []
    for oid, emp, uf, capex in targets_raw:
        if len(emp.strip()) > 55:
            continue
        core = clean_core(emp)
        if len(core) < 5 or BAD_TITLE_NOISE_RE.search(core):
            continue
        tok = pick_anchor_token(core)
        if not tok:
            continue
        targets.append((oid, emp, uf or "", capex, core, tok))

    print(f"Alvos reais filtrados (sem CNPJ): {len(targets)}")

    # Unica varredura em fornecedores usando os tokens ancora
    unique_toks = sorted({t[5] for t in targets})
    con.execute("CREATE OR REPLACE TEMP TABLE tmp_toks (tok VARCHAR);")
    con.executemany("INSERT INTO tmp_toks VALUES (?)", [(tk,) for tk in unique_toks])

    cand_rows = con.execute("""
        SELECT DISTINCT
            t.tok,
            f.cnpj,
            f.razao_social,
            COALESCE(f.nome_fantasia, '') AS fantasia,
            COALESCE(f.uf, '') AS uf,
            COALESCE(f.capital_social, 0) AS cap_soc
        FROM tmp_toks t
        JOIN fornecedores f
          ON (UPPER(f.razao_social) LIKE '%' || t.tok || '%' OR UPPER(COALESCE(f.nome_fantasia, '')) LIKE '%' || t.tok || '%')
        WHERE (f.situacao = 'ATIVA' OR f.situacao IS NULL)
          AND SUBSTR(f.cnpj, 9, 4) = '0001'
    """).fetchall()

    by_tok: dict[str, list] = {}
    for tok, cnpj, rz, fant, f_uf, cap_soc in cand_rows:
        by_tok.setdefault(tok, []).append((cnpj, rz, fant, f_uf, cap_soc))

    resolved_cnpjs = []
    for oid, emp, uf, capex, core, tok in targets:
        dt_target = distinctive_tokens(core)
        if not dt_target or (len(dt_target) == 1 and len(dt_target[0]) < 4 and "GRUPO" in emp.upper()):
            continue
        cands = by_tok.get(tok, [])
        best_cnpj, best_rz, best_sc = None, None, 0.0
        for cnpj, rz, fant, f_uf, cap_soc in cands:
            c_rz = clean_core(rz)
            c_fa = clean_core(fant) if fant else ""
            # Exigir correspondencia exata dos tokens distintivos (evita Ala vs Aegla, Maria vs Garcia)
            ok_rz = distinctive_tokens(c_rz) == dt_target
            ok_fa = distinctive_tokens(c_fa) == dt_target if c_fa else False
            if not (ok_rz or ok_fa):
                continue
            sc = max(fuzz.token_sort_ratio(core, c_rz) if ok_rz else 0.0, fuzz.token_sort_ratio(core, c_fa) if ok_fa else 0.0)
            if f_uf == uf and uf:
                sc += 1.5
            if sc > best_sc:
                best_cnpj, best_rz, best_sc = cnpj, rz, sc
        if best_cnpj and best_sc >= 91.0:
            raiz = best_cnpj[:8]
            con.execute("UPDATE obras_oficiais_ativas SET obra_cnpj = ?, obra_cnpj_raiz = ? WHERE id_externo = ?", [best_cnpj, raiz, oid])
            con.execute("UPDATE todas_obras_consolidadas SET obra_cnpj = ?, obra_cnpj_raiz = ? WHERE obra_id = ?", [best_cnpj, raiz, oid])
            resolved_cnpjs.append((oid, emp, best_cnpj, best_rz, best_sc, uf, capex))

    print(f"CNPJs novos resolvidos via fornecedores (score >= 91): {len(resolved_cnpjs)}")
    for oid, emp, cnpj, rz, sc, uf, _ in resolved_cnpjs:
        print(f"  + {oid} | {emp} -> {rz} ({cnpj}) [score={sc:.1f}, UF={uf}]")

    # Buscar QSA PF + telefone + email reais na Receita Federal (minhareceita.org) para os CNPJs unicos resolvidos
    qsa_cache: dict[str, dict] = {}
    qsa_inserted = 0
    for oid, emp, cnpj, rz, sc, uf, capex in resolved_cnpjs:
        if cnpj not in qsa_cache:
            try:
                r = requests.get(f"https://minhareceita.org/{cnpj}", timeout=10)
                qsa_cache[cnpj] = r.json() if r.status_code == 200 else {}
            except Exception as e:
                print(f"  [WARN] minhareceita {cnpj}: {e}")
                qsa_cache[cnpj] = {}

        d = qsa_cache[cnpj]
        if not d:
            continue
        tel = (d.get("ddd_telefone_1") or "").strip() or None
        email = (d.get("email") or "").strip().lower() or None
        for s in d.get("qsa", []):
            nome = (s.get("nome_socio") or "").strip()
            cargo = (s.get("qualificacao_socio") or "Socio-Administrador").strip()
            if not nome or len(nome) < 4 or any(x in nome.upper() for x in ("LTDA", "S/A", "S.A.", "HOLDING", "EIRELI")):
                continue
            exists = con.execute(
                "SELECT COUNT(*) FROM validacao_decisores_obras_novas WHERE id_externo = ? AND UPPER(TRIM(decisor_nome)) = UPPER(TRIM(?))",
                [oid, nome],
            ).fetchone()[0]
            if exists:
                continue
            aci = bool(tel or email)
            con.execute(
                """
                INSERT INTO validacao_decisores_obras_novas (
                    id_externo, fonte, obra_empresa, obra_cnpj, obra_uf, capex_estimado,
                    tipo_match, decisor_nome, decisor_cargo, decisor_email, decisor_telefone,
                    is_contato_acionavel, perfil_decisor
                ) VALUES (?, 'convisao_cnc', ?, ?, ?, ?, 'QSA_MINHARECEITA_PF', ?, ?, ?, ?, ?, '4_SOCIO_QSA')
                """,
                [oid, emp, cnpj, uf or None, capex, nome, cargo, email, tel, aci],
            )
            qsa_inserted += 1

    con.execute("CHECKPOINT;")
    con.close()
    print(f"Socios QSA PF reais inseridos: {qsa_inserted}")

    if resolved_cnpjs or qsa_inserted:
        subprocess.run([sys.executable, os.path.join(BASE_DIR, "scripts", "normalizar_telefones_libphonenumber.py")], check=True)
        subprocess.run([sys.executable, os.path.join(BASE_DIR, "scripts", "gerar_fila_864_sem_linkedin.py")], check=True)


if __name__ == "__main__":
    main()
