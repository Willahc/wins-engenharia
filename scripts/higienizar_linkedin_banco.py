import os
import re
import subprocess
import unicodedata
import urllib.parse
import duckdb

BASE_DIR = r"C:\Users\kbadmin\Documents\Projetos\01_Ecossistema_WiNS\Engenharia"
MAIN_DB = os.path.join(BASE_DIR, "Banco_Dados", "wins_engenharia.duckdb")
SUB_DB = os.path.join(BASE_DIR, "Banco_Dados", "obras_civil_industrial_2026_2027_100k.duckdb")
OUT_CSV = os.path.join(BASE_DIR, "Arquivos_Tratados", "obras_novas_com_decisores.csv").replace("\\", "/")

LEGIT_INITIAL_EXCEPTIONS = {"mbtribeiro", "dancorfer"}
COMPANY_NOISE_REGEX = re.compile(r"\b(usina\s+laguna|montera\s+engenharia|axia\s+women)\b", re.I)
ROLE_AS_NAME_REGEX = re.compile(
    r"\b(diretor|gerente|coordenador|comprador|suprimentos|engenharia|compras|admin|contato|departamento)\b",
    re.I,
)
BROKEN_MISSING_ACCENT_SLUGS = {
    "arthur-galvo",
    "gilberto-loureno-feldman",
    "vincius-vanzella-de-souza",
    "caio-t",
}


def strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s or "") if not unicodedata.combining(c))


def validate_linkedin_url(url: str, nome: str) -> str:
    """Returns clean normalized URL if valid, or '' if broken/truncated/wrong."""
    if not url:
        return ""
    if ROLE_AS_NAME_REGEX.search(nome or ""):
        return ""
    u = url.strip()
    u_low = u.lower()
    if "linkedin.com" not in u_low:
        return ""
    if any(x in u_low for x in ("/posts/", "/company/", "/school/", "/pulse/")):
        return ""
    m = re.match(r"^https?://([a-z]{2,3}\.)?linkedin\.com/in/([^/?#]+)", u_low)
    if not m:
        return ""
    slug_raw = m.group(2)
    slug_dec = urllib.parse.unquote(slug_raw)
    slug_clean = re.sub(r"-[0-9a-f]{6,}$", "", slug_dec)
    slug_clean = re.sub(r"/(pt|en|es)$", "", slug_clean)

    # Reject synthetic role slugs or known broken slugs
    if re.match(r"^(diretor|gerente|coordenador|comprador|suprimentos|compras)-", slug_dec):
        return ""
    if slug_clean in BROKEN_MISSING_ACCENT_SLUGS or slug_dec in BROKEN_MISSING_ACCENT_SLUGS:
        return ""

    # Truncated slugs cut on accented char (e.g. /in/jo, /in/jos, /in/napole, /in/tain)
    if len(slug_dec) <= 4 or len(slug_clean) <= 3:
        return ""
    if slug_dec in ("napole", "patr", "andr", "horm", "tain"):
        return ""

    if slug_dec in LEGIT_INITIAL_EXCEPTIONS:
        return u

    nome_tokens = [
        t for t in re.findall(r"[a-z]{3,}", strip_accents(nome).lower())
        if t not in ("dos", "das", "del", "van", "von")
    ]
    slug_alpha = re.sub(r"[^a-z]", "", strip_accents(slug_dec).lower())
    if nome_tokens and not any(t in slug_alpha for t in nome_tokens):
        return ""

    # Reject slugs truncated mid-word at the end (e.g. rodrigo-corr, marcos-andr, valdir-gir)
    last_slug_tok = slug_clean.split("-")[-1] if "-" in slug_clean else ""
    if last_slug_tok and len(last_slug_tok) >= 3:
        for nt in nome_tokens:
            if nt.startswith(last_slug_tok) and 1 <= len(nt) - len(last_slug_tok) <= 3:
                return ""

    return u


def is_company_noise(nome: str) -> bool:
    return bool(COMPANY_NOISE_REGEX.search(nome or ""))


con = duckdb.connect(MAIN_DB)
con.create_function("validate_linkedin_url", validate_linkedin_url, ["VARCHAR", "VARCHAR"], "VARCHAR")
con.create_function("is_company_noise", is_company_noise, ["VARCHAR"], "BOOLEAN")

# Auditar antes
before_lk_novas = con.execute("SELECT COUNT(*) FROM validacao_decisores_obras_novas WHERE decisor_linkedin IS NOT NULL AND decisor_linkedin <> ''").fetchone()[0]
before_lk_hist = con.execute("SELECT COUNT(*) FROM decisores WHERE linkedin_url IS NOT NULL AND linkedin_url <> ''").fetchone()[0]

# 1. Limpar decisores (historico)
con.execute("""
UPDATE decisores
SET
    linkedin_url = NULLIF(validate_linkedin_url(linkedin_url, nome), ''),
    tem_linkedin = (NULLIF(validate_linkedin_url(linkedin_url, nome), '') IS NOT NULL),
    is_contato_acionavel = (
        email IS NOT NULL
        OR telefone IS NOT NULL
        OR NULLIF(validate_linkedin_url(linkedin_url, nome), '') IS NOT NULL
    )
WHERE linkedin_url IS NOT NULL;
""")

# 2. Limpar dim_decisores_empresa
con.execute("""
DELETE FROM dim_decisores_empresa WHERE is_company_noise(nome);
""")
con.execute("""
UPDATE dim_decisores_empresa
SET
    linkedin_url = NULLIF(validate_linkedin_url(linkedin_url, nome), ''),
    is_contato_acionavel = (
        email IS NOT NULL
        OR telefone IS NOT NULL
        OR NULLIF(validate_linkedin_url(linkedin_url, nome), '') IS NOT NULL
    )
WHERE linkedin_url IS NOT NULL;
""")

# 3. Limpar validacao_decisores_obras_novas
con.execute("""
DELETE FROM validacao_decisores_obras_novas WHERE is_company_noise(decisor_nome);
""")
con.execute("""
UPDATE validacao_decisores_obras_novas
SET
    decisor_linkedin = NULLIF(validate_linkedin_url(decisor_linkedin, decisor_nome), ''),
    is_contato_acionavel = (
        decisor_email IS NOT NULL
        OR decisor_telefone IS NOT NULL
        OR NULLIF(validate_linkedin_url(decisor_linkedin, decisor_nome), '') IS NOT NULL
    )
WHERE decisor_linkedin IS NOT NULL;
""")

after_lk_novas = con.execute("SELECT COUNT(*) FROM validacao_decisores_obras_novas WHERE decisor_linkedin IS NOT NULL").fetchone()[0]
after_lk_hist = con.execute("SELECT COUNT(*) FROM decisores WHERE linkedin_url IS NOT NULL").fetchone()[0]

con.execute(f"COPY validacao_decisores_obras_novas TO '{OUT_CSV}' (HEADER, DELIMITER ',');")
con.execute("ANALYZE;")
con.execute("CHECKPOINT;")
con.close()

# Atualizar banco leve
sub = duckdb.connect(SUB_DB)
main_sql = MAIN_DB.replace("\\", "/")
sub.execute(f"ATTACH '{main_sql}' AS main_db (READ_ONLY);")
sub.execute("CREATE OR REPLACE TABLE decisores_obras_novas AS SELECT * FROM main_db.validacao_decisores_obras_novas;")
sub.execute("DETACH main_db;")
sub.execute("CHECKPOINT;")
sub.close()

print(f"[LINKEDIN HISTORICO] {before_lk_hist:,} -> {after_lk_hist:,} (-{before_lk_hist - after_lk_hist:,} links invalidos/truncados removidos)")
print(f"[LINKEDIN OBRAS NOVAS] {before_lk_novas:,} -> {after_lk_novas:,} (-{before_lk_novas - after_lk_novas:,} links invalidos/truncados/errados removidos)")

subprocess.run(["python", os.path.join(BASE_DIR, "scripts", "gerar_dashboard_html.py")], check=True)
