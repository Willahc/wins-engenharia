import csv
import os
import re
import unicodedata
from collections import Counter, defaultdict

BASE_DIR = r"C:\Users\kbadmin\Documents\Projetos\01_Ecossistema_WiNS\Engenharia"
INPUT_DIR = os.path.join(BASE_DIR, "Arquivos")
OUTPUT_DIR = os.path.join(BASE_DIR, "Arquivos_Tratados")
os.makedirs(OUTPUT_DIR, exist_ok=True)

UFS_BR = {
    "AC", "AL", "AP", "AM", "BA", "CE", "DF", "ES", "GO", "MA", "MT", "MS",
    "MG", "PA", "PB", "PR", "PE", "PI", "RJ", "RN", "RS", "RO", "RR", "SC",
    "SP", "SE", "TO"
}

GENERIC_EMAIL_PREFIXES = {
    "contato", "comercial", "vendas", "atendimento", "sac", "suporte", "info",
    "adm", "administrativo", "administracao", "financeiro", "faturamento",
    "fiscal", "contabil", "contabilidade", "rh", "dp", "recrutamento",
    "compras", "suprimentos", "licitacao", "licitacoes", "engenharia",
    "projetos", "obras", "orcamento", "orcamentos", "noreply", "no-reply",
    "naoresponda", "secretaria", "diretoria", "gerencia", "recepcao",
    "faleconosco", "ouvidoria", "juridico", "marketing", "ti", "geral",
    "escritorio", "matriz", "loja", "imprensa", "press", "hello", "contact",
    "abertura", "meucnpj", "societario", "legalizacao", "operacoesrodoviarias",
    "cadastro", "cobranca", "tesouraria", "expedicao", "logistica", "almoxarifado"
}

ACCOUNTING_DOMAINS = {
    "contabilizei.com.br", "maismei.com.br", "agilize.com.br", "senhorcontabil.com.br"
}

EMAIL_REGEX = re.compile(r"^[a-z0-9._%+\-]+@[a-z0-9.\-]+\.[a-z]{2,}$")
SYNTHETIC_NAME_REGEX = re.compile(r"^contato\s+comercial\s+[0-9a-f]{4,}$", re.I)
GENERIC_ROLE_AS_NAME_REGEX = re.compile(
    r"^(equipe\s+compras|processo\s+administrativo|in\s+secretaria|"
    r"dir\.\s*engenharia|diretoria\s+de\s+engenharia|diretor\s+de\s+licitacoes|"
    r"ger[eê]ncia\s+engenharia|contato\s+comercial|sem\s+nome|n[aã]o\s+informado|"
    r"desconhecido|departamento\s+.*|setor\s+.*)$",
    re.I
)
COMPANY_AS_NAME_REGEX = re.compile(
    r"\b(ltda|eireli|s\.?a\.?|s/a|participacoes|participações|comercializadora|servicos\s+de\s+gerenciamento)\b",
    re.I
)

CNAE_DIV_TO_SETOR = {
    "01": "AGROPECUARIA",
    "02": "FLORESTAL",
    "05": "MINERACAO",
    "06": "PETROLEO_GAS",
    "07": "MINERACAO",
    "08": "MINERACAO",
    "09": "MINERACAO_PETROLEO_APOIO",
    "19": "PETROLEO_GAS",
    "20": "QUIMICA_INDUSTRIAL",
    "22": "INDUSTRIAL",
    "23": "MATERIAIS_CONSTRUCAO",
    "24": "SIDERURGIA_METALURGIA",
    "25": "METALURGIA_ESTRUTURAS",
    "26": "ELETRONICA_AUTOMACAO",
    "27": "EQUIPAMENTOS_ELETRICOS",
    "28": "MAQUINAS_EQUIPAMENTOS",
    "33": "MANUTENCAO_INDUSTRIAL",
    "35": "ENERGIA",
    "36": "SANEAMENTO",
    "37": "SANEAMENTO",
    "38": "RESIDUOS_AMBIENTAL",
    "39": "RESIDUOS_AMBIENTAL",
    "41": "CONSTRUCAO_EDIFICIOS",
    "42": "INFRAESTRUTURA",
    "43": "CONSTRUCAO_ESPECIALIZADA",
    "46": "COMERCIO_ATACADISTA",
    "47": "COMERCIO_VAREJISTA",
    "49": "LOGISTICA_TRANSPORTE",
    "50": "TRANSPORTE_AQUAVIARIO",
    "52": "LOGISTICA_ARMAZENAGEM",
    "61": "TELECOMUNICACOES",
    "62": "TECNOLOGIA_TI",
    "71": "ENGENHARIA_ARQUITETURA",
    "74": "SERVICOS_TECNICOS",
    "77": "LOCACAO_MAQUINAS_EQUIPAMENTOS",
    "81": "FACILITIES_MANUTENCAO",
    "82": "SERVICOS_ADMINISTRATIVOS",
}


def strip_accents(text: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFKD", text)
        if not unicodedata.combining(c)
    )


def normalize_name(name: str) -> str:
    s = strip_accents(name.strip().lower())
    s = re.sub(r"\s+", " ", s)
    return s


def classify_and_clean_email(raw_email: str, filter_accounting_domains: bool = False):
    """Returns (clean_email, status) where status is 'VALID', 'EMPTY', 'INVALID', or 'GENERIC'."""
    em = raw_email.strip().lower()
    if not em:
        return "", "EMPTY"
    if not EMAIL_REGEX.match(em):
        return "", "INVALID"
    pref, dom = em.split("@", 1)
    if filter_accounting_domains and dom in ACCOUNTING_DOMAINS:
        return "", "GENERIC"
    pref_base = re.split(r"[._\-+]", pref)[0]
    if pref in GENERIC_EMAIL_PREFIXES or pref_base in GENERIC_EMAIL_PREFIXES:
        return "", "GENERIC"
    return em, "VALID"


def clean_phone(raw_phone: str):
    """Returns digits-only BR phone if valid, else ''."""
    digits = re.sub(r"\D", "", raw_phone or "")
    if not digits:
        return ""
    if digits.startswith("55") and len(digits) in (12, 13):
        digits = digits[2:]
    if digits.startswith("0800") or digits.startswith("0300"):
        return ""
    if digits.startswith("0") and len(digits) in (11, 12):
        digits = digits[1:]
    if len(digits) < 10 or len(digits) > 11:
        return ""
    if len(set(digits)) <= 2 or len(set(digits[2:])) <= 2:
        return ""
    return digits


def normalize_linkedin(url: str) -> str:
    u = (url or "").strip().lower()
    if not u:
        return ""
    u = u.split("?")[0].rstrip("/")
    u = u.replace("http://", "https://")
    u = re.sub(r"https://[a-z]{2}\.linkedin\.com", "https://www.linkedin.com", u)
    return u


# ---------------------------------------------------------------------------
# 1. TRATAMENTO: fontes_obras_2026-10-26.csv
# ---------------------------------------------------------------------------
def process_fontes():
    in_path = os.path.join(INPUT_DIR, "fontes_obras_2026-10-26.csv")
    out_path = os.path.join(OUTPUT_DIR, "fontes_obras_tratado.csv")

    tipo_priority = {"OFICIAL": 1, "NOTICIA": 2, "MANUAL": 3, "(nulo)": 4, "": 5}

    def norm_fonte(f_raw: str) -> str:
        f = f_raw.strip()
        if "cimm.com.br" in f:
            return "cimm_noticia"
        if "agfeed.com.br" in f:
            return "agfeed_noticia"
        return f.lower().replace(" ", "_") if f.startswith("http") else f

    grouped = {}
    raw_count = 0
    with open(in_path, "r", encoding="utf-8", newline="") as fin:
        for r in csv.DictReader(fin):
            raw_count += 1
            fn = norm_fonte(r["fonte"])
            t = r["tipo"].strip() or "(nulo)"
            obras = int(r["obras"] or 0)
            com_url = int(r["com_url"] or 0)
            capt = int(r["via_captador_novo"] or 0)
            capex = float(r["capex_bi"] or 0.0)
            p1 = r["primeira_publicacao"].strip()
            p2 = r["ultima_publicacao"].strip()

            if fn not in grouped:
                grouped[fn] = {
                    "fonte": fn,
                    "tipo": t,
                    "obras": obras,
                    "com_url": com_url,
                    "via_captador_novo": capt,
                    "capex_bi": capex,
                    "primeira_publicacao": p1,
                    "ultima_publicacao": p2,
                    "linhas_consolidadas": 1,
                }
            else:
                g = grouped[fn]
                if tipo_priority.get(t, 9) < tipo_priority.get(g["tipo"], 9):
                    g["tipo"] = t
                g["obras"] += obras
                g["com_url"] += com_url
                g["via_captador_novo"] += capt
                g["capex_bi"] = round(g["capex_bi"] + capex, 2)
                g["linhas_consolidadas"] += 1
                if p1 and (not g["primeira_publicacao"] or p1 < g["primeira_publicacao"]):
                    g["primeira_publicacao"] = p1
                if p2 and (not g["ultima_publicacao"] or p2 > g["ultima_publicacao"]):
                    g["ultima_publicacao"] = p2

    rows_out = sorted(grouped.values(), key=lambda x: -x["obras"])
    fieldnames = [
        "fonte", "tipo", "obras", "com_url", "pct_com_url", "via_captador_novo",
        "capex_bi", "capex_medio_obra_mi", "flag_capex_outlier",
        "primeira_publicacao", "ultima_publicacao", "linhas_consolidadas"
    ]
    with open(out_path, "w", encoding="utf-8", newline="") as fout:
        w = csv.DictWriter(fout, fieldnames=fieldnames)
        w.writeheader()
        for g in rows_out:
            pct_url = round(g["com_url"] / g["obras"] * 100, 1) if g["obras"] else 0.0
            capex_med_mi = round((g["capex_bi"] * 1000.0) / g["obras"], 2) if g["obras"] else 0.0
            flag_outlier = "t" if capex_med_mi > 10000 else "f"
            g["pct_com_url"] = pct_url
            g["capex_medio_obra_mi"] = capex_med_mi
            g["flag_capex_outlier"] = flag_outlier
            g["capex_bi"] = round(g["capex_bi"], 1)
            w.writerow(g)

    print(f"[FONTES] Original: {raw_count} linhas -> Tratado: {len(rows_out)} fontes consolidadas.")


# ---------------------------------------------------------------------------
# 2. TRATAMENTO: wins_eng_comercial_decisores.csv
# ---------------------------------------------------------------------------
def decisor_quality_rank(row: dict) -> tuple:
    """Higher tuple = better record to keep during deduplication."""
    lead_rank = {"verde": 3, "amarelo": 2, "vermelho": 1}.get(row["qualidade_lead"], 0)
    obra_rank = {"OURO": 3, "PRATA": 2, "NAO_VALIDADO": 1}.get(row["obra_classificacao"], 0)
    has_val_email = 1 if row["email_corporativo_validado"] == "t" else 0
    has_email = 1 if row["email"] else 0
    has_linkedin = 1 if row["linkedin_url"] else 0
    has_phone = 1 if row["telefone"] else 0
    has_verif = 1 if row["verificado_em"] else 0
    try:
        score = float(row["confianca_score"] or 0)
    except ValueError:
        score = 0.0
    return (
        has_val_email,
        has_email + has_linkedin + has_phone,
        lead_rank,
        obra_rank,
        has_verif,
        score,
        row["registrado_em"],
    )


def process_decisores():
    in_path = os.path.join(INPUT_DIR, "wins_eng_comercial_decisores.csv")
    out_path = os.path.join(OUTPUT_DIR, "wins_eng_comercial_decisores_tratado.csv")

    stats = Counter()
    best_by_key = {}
    records = []

    with open(in_path, "r", encoding="utf-8", newline="") as fin:
        reader = csv.DictReader(fin)
        in_fields = reader.fieldnames
        for row in reader:
            stats["total_lido"] += 1
            nome = row["nome"].strip()

            if SYNTHETIC_NAME_REGEX.match(nome):
                stats["rem_nome_sintetico"] += 1
                continue
            if GENERIC_ROLE_AS_NAME_REGEX.match(nome):
                stats["rem_nome_generico_cargo"] += 1
                continue
            if COMPANY_AS_NAME_REGEX.search(nome):
                stats["rem_nome_empresa"] += 1
                continue

            # Clean contacts
            clean_em, em_stat = classify_and_clean_email(row["email"], filter_accounting_domains=False)
            if em_stat == "GENERIC":
                stats["emails_genericos_limpos"] += 1
            elif em_stat == "INVALID":
                stats["emails_invalidos_limpos"] += 1
            row["email"] = clean_em

            clean_ph = clean_phone(row["telefone"])
            if row["telefone"] and not clean_ph:
                stats["telefones_invalidos_0800_limpos"] += 1
            row["telefone"] = clean_ph

            clean_lk = normalize_linkedin(row["linkedin_url"])
            row["linkedin_url"] = clean_lk
            row["tem_linkedin"] = "t" if clean_lk else "f"

            if row["obra_uf"] and row["obra_uf"] not in UFS_BR:
                stats["uf_invalida_limpa"] += 1
                row["obra_uf"] = ""

            row["is_contato_acionavel"] = "t" if (clean_em or clean_ph or clean_lk) else "f"

            # Deduplication keys within same obra_id
            oid = row["obra_id"]
            nome_n = normalize_name(nome)
            keys = [("nome", oid, nome_n)]
            if clean_em:
                keys.append(("email", oid, clean_em))
            if clean_lk:
                keys.append(("lk", oid, clean_lk))

            rank = decisor_quality_rank(row)
            idx = len(records)
            records.append((rank, row, keys))

    # Resolve duplicates greedily from highest rank to lowest
    records.sort(key=lambda x: x[0], reverse=True)
    seen_keys = set()
    kept_rows = []
    for rank, row, keys in records:
        if any(k in seen_keys for k in keys):
            stats["rem_duplicado_obra"] += 1
            continue
        for k in keys:
            seen_keys.add(k)
        kept_rows.append(row)

    out_fields = in_fields + ["is_contato_acionavel"]
    with open(out_path, "w", encoding="utf-8", newline="") as fout:
        w = csv.DictWriter(fout, fieldnames=out_fields)
        w.writeheader()
        w.writerows(kept_rows)

    stats["total_final"] = len(kept_rows)
    stats["acionaveis_final"] = sum(1 for r in kept_rows if r["is_contato_acionavel"] == "t")
    print("[DECISORES]", dict(stats))


# ---------------------------------------------------------------------------
# 3. TRATAMENTO: wins_eng_fornecedores.csv (streaming 1.2 GB)
# ---------------------------------------------------------------------------
def process_fornecedores():
    in_path = os.path.join(INPUT_DIR, "wins_eng_fornecedores.csv")
    out_path = os.path.join(OUTPUT_DIR, "wins_eng_fornecedores_tratado.csv")

    stats = Counter()
    seen_cnpj = set()

    with open(in_path, "r", encoding="utf-8", newline="") as fin, \
         open(out_path, "w", encoding="utf-8", newline="") as fout:
        reader = csv.reader(fin)
        headers = next(reader)
        idx = {h: i for i, h in enumerate(headers)}

        out_headers = headers + ["setor_consolidado", "porte_consolidado", "is_contato_acionavel"]
        writer = csv.writer(fout)
        writer.writerow(out_headers)

        i_cnpj = idx["cnpj"]
        i_sit = idx["situacao"]
        i_uf = idx["uf"]
        i_email = idx["email"]
        i_tel1 = idx["telefone_1"]
        i_tel2 = idx["telefone_2"]
        i_tipo = idx["tipo_estabelecimento"]
        i_porte = idx["porte"]
        i_porte_inf = idx["porte_inferido"]
        i_setor = idx["setor"]
        i_div = idx["divisao_cnae"]

        for row in reader:
            stats["total_lido"] += 1
            sit = row[i_sit].strip().upper()
            uf = row[i_uf].strip().upper()
            cnpj = row[i_cnpj].strip()

            if sit in ("BAIXADA", "INAPTA", "SUSPENSA"):
                stats["rem_inativa"] += 1
                continue
            if uf not in UFS_BR:
                stats["rem_uf_exterior_ou_invalida"] += 1
                continue
            if cnpj in seen_cnpj:
                stats["rem_cnpj_duplicado"] += 1
                continue
            seen_cnpj.add(cnpj)

            # Clean emails & phones
            clean_em, em_stat = classify_and_clean_email(row[i_email], filter_accounting_domains=True)
            if em_stat == "INVALID":
                stats["emails_invalidos_limpos"] += 1
            elif em_stat == "GENERIC":
                stats["emails_genericos_contabeis_limpos"] += 1
            row[i_email] = clean_em

            p1 = clean_phone(row[i_tel1])
            if row[i_tel1] and not p1:
                stats["tel1_invalidos_limpos"] += 1
            row[i_tel1] = p1

            p2 = clean_phone(row[i_tel2])
            if row[i_tel2] and not p2:
                stats["tel2_invalidos_limpos"] += 1
            if p2 == p1:
                p2 = ""
            row[i_tel2] = p2

            # Normalize tipo_estabelecimento
            tp = row[i_tipo].strip().upper()
            if tp == "1":
                row[i_tipo] = "MATRIZ"
            elif tp == "2":
                row[i_tipo] = "FILIAL"

            # Normalize porte
            pt = row[i_porte].strip().upper()
            if pt == "MICRO EMPRESA":
                pt = "ME"
            elif pt == "EMPRESA DE PEQUENO PORTE":
                pt = "EPP"
            row[i_porte] = pt

            porte_cons = pt if pt else row[i_porte_inf].strip().upper()

            # Consolidate setor
            st = row[i_setor].strip().upper()
            if not st:
                st = CNAE_DIV_TO_SETOR.get(row[i_div].strip(), "OUTROS")

            acionavel = "t" if (clean_em or p1 or p2) else "f"
            if acionavel == "t":
                stats["acionaveis_final"] += 1

            writer.writerow(row + [st, porte_cons, acionavel])
            stats["total_final"] += 1

    print("[FORNECEDORES]", dict(stats))


if __name__ == "__main__":
    process_fontes()
    process_decisores()
    process_fornecedores()
