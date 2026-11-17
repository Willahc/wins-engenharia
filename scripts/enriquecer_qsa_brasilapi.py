import os
import re
import time
import requests
import duckdb

BASE_DIR = r"C:\Users\kbadmin\Documents\Projetos\01_Ecossistema_WiNS\Engenharia"
MAIN_DB = os.path.join(BASE_DIR, "Banco_Dados", "wins_engenharia.duckdb")
SUB_DB = os.path.join(BASE_DIR, "Banco_Dados", "obras_civil_industrial_2026_2027_100k.duckdb")
OUT_CSV = os.path.join(BASE_DIR, "Arquivos_Tratados", "obras_novas_com_decisores.csv")

GENERIC_PREFIXES = {
    "contato", "comercial", "vendas", "atendimento", "sac", "suporte", "info",
    "adm", "administrativo", "administracao", "financeiro", "faturamento",
    "fiscal", "contabil", "contabilidade", "rh", "dp", "recrutamento",
    "compras", "suprimentos", "licitacao", "licitacoes", "engenharia",
    "projetos", "obras", "orcamento", "orcamentos", "noreply", "no-reply",
    "naoresponda", "secretaria", "diretoria", "gerencia", "recepcao",
    "faleconosco", "ouvidoria", "juridico", "marketing", "ti", "geral",
    "escritorio", "matriz", "loja", "imprensa", "press", "hello", "contact",
    "abertura", "meucnpj", "societario", "legalizacao"
}


def clean_email(raw: str) -> str:
    em = (raw or "").strip().lower()
    if not em or "@" not in em or " " in em:
        return ""
    pref = em.split("@", 1)[0]
    pref_base = re.split(r"[._\-+]", pref)[0]
    if pref in GENERIC_PREFIXES or pref_base in GENERIC_PREFIXES:
        return ""
    return em


def clean_phone(raw: str) -> str:
    d = re.sub(r"\D", "", raw or "")
    if len(d) in (10, 11) and len(set(d)) > 2:
        return d
    return ""


def fetch_brasilapi(cnpj: str):
    url = f"https://brasilapi.com.br/api/cnpj/v1/{cnpj}"
    for attempt in range(3):
        try:
            r = requests.get(url, timeout=15, headers={"User-Agent": "WiNS-Engenharia-QSA/1.0"})
            if r.status_code == 200:
                return r.json()
            if r.status_code == 429:
                time.sleep(2 ** (attempt + 1))
                continue
            return None
        except requests.RequestException:
            time.sleep(1.5)
    return None


con = duckdb.connect(MAIN_DB)

# Obras privadas (ANEEL / BNDES) com CNPJ que ainda nao tem decisor
missing = con.execute("""
SELECT
    o.id_externo,
    o.fonte,
    o.obra_nome,
    o.obra_empresa,
    o.obra_cnpj,
    o.categoria_macro,
    o.obra_uf,
    o.capex_estimado,
    o.capex_tipo,
    o.url_origem
FROM obras_oficiais_ativas o
LEFT JOIN (SELECT DISTINCT id_externo FROM validacao_decisores_obras_novas) m
  ON o.id_externo = m.id_externo
WHERE m.id_externo IS NULL
  AND o.obra_cnpj IS NOT NULL
  AND o.fonte IN ('aneel_siga', 'bndes_financiamento');
""").fetchdf()

distinct_cnpjs = sorted(missing["obra_cnpj"].unique().tolist())
print(f"Obras privadas sem decisor: {len(missing)} | CNPJs distintos a consultar na BrasilAPI: {len(distinct_cnpjs)}")

qsa_by_cnpj = {}
ok_cnpjs = 0
for i, cnpj in enumerate(distinct_cnpjs, 1):
    data = fetch_brasilapi(cnpj)
    if data:
        ok_cnpjs += 1
        tel = clean_phone(data.get("ddd_telefone_1") or "")
        em = clean_email(data.get("email") or "")
        socios = []
        for s in (data.get("qsa") or []):
            # Se for PJ (identificador_de_socio == 1), tenta pegar representante_legal
            id_soc = s.get("identificador_de_socio")
            if id_soc == 1:
                nome = (s.get("nome_representante_legal") or "").strip()
                cargo = (s.get("qualificacao_representante_legal") or "Representante Legal").strip()
            else:
                nome = (s.get("nome_socio") or "").strip()
                cargo = (s.get("qualificacao_socio") or "Sócio/Administrador").strip()
            if nome and len(nome) >= 4:
                socios.append((nome, cargo))
        qsa_by_cnpj[cnpj] = {"tel": tel, "em": em, "socios": socios}
    if i % 50 == 0:
        print(f"  Progresso BrasilAPI: {i}/{len(distinct_cnpjs)} (sucesso={ok_cnpjs})")
    time.sleep(0.35)

print(f"BrasilAPI concluida: {ok_cnpjs}/{len(distinct_cnpjs)} CNPJs com retorno.")

new_rows = []
for _, o in missing.iterrows():
    info = qsa_by_cnpj.get(o["obra_cnpj"])
    if not info:
        continue
    for idx_s, (nome, cargo) in enumerate(info["socios"]):
        acionavel = bool(info["em"] or info["tel"])
        new_rows.append((
            o["id_externo"],
            o["fonte"],
            o["obra_nome"],
            o["obra_empresa"],
            o["obra_cnpj"],
            o["categoria_macro"],
            o["obra_uf"],
            float(o["capex_estimado"] or 0),
            o["capex_tipo"],
            o["url_origem"],
            "4_QSA_BRASILAPI",
            f"QSA-{o['obra_cnpj']}-{idx_s}",
            nome,
            cargo,
            info["em"] or None,
            info["tel"] or None,
            None,
            "amarelo" if acionavel else "vermelho",
            acionavel,
        ))

if new_rows:
    con.executemany("""
        INSERT INTO validacao_decisores_obras_novas VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, new_rows)
    # Deduplicar por seguranca
    con.execute("""
    CREATE OR REPLACE TABLE validacao_decisores_obras_novas AS
    SELECT DISTINCT ON (id_externo, LOWER(TRIM(decisor_nome)), COALESCE(decisor_email, ''), COALESCE(decisor_linkedin, ''))
        *
    FROM validacao_decisores_obras_novas
    ORDER BY id_externo, LOWER(TRIM(decisor_nome)), COALESCE(decisor_email, ''), COALESCE(decisor_linkedin, ''), tipo_match, is_contato_acionavel DESC;
    """)

resumo = con.execute("""
SELECT
    COUNT(DISTINCT o.id_externo) AS total_obras_novas,
    COUNT(DISTINCT m.id_externo) AS obras_com_decisor,
    COUNT(DISTINCT CASE WHEN m.is_contato_acionavel THEN o.id_externo END) AS obras_com_acionavel,
    COUNT(*) FILTER (WHERE m.id_externo IS NOT NULL) AS total_vinculos,
    COUNT(*) FILTER (WHERE m.is_contato_acionavel) AS vinculos_acionaveis
FROM obras_oficiais_ativas o
LEFT JOIN validacao_decisores_obras_novas m ON o.id_externo = m.id_externo;
""").fetchdf()

out_sql = OUT_CSV.replace("\\", "/")
con.execute(f"COPY validacao_decisores_obras_novas TO '{out_sql}' (HEADER, DELIMITER ',');")
con.execute("ANALYZE;")
con.execute("CHECKPOINT;")
con.close()

# Atualizar tambem o banco leve
sub = duckdb.connect(SUB_DB)
main_sql = MAIN_DB.replace("\\", "/")
sub.execute(f"ATTACH '{main_sql}' AS main_db (READ_ONLY);")
sub.execute("CREATE OR REPLACE TABLE decisores_obras_novas AS SELECT * FROM main_db.validacao_decisores_obras_novas;")
sub.execute("DETACH main_db;")
sub.execute("ANALYZE;")
sub.execute("CHECKPOINT;")
sub.close()

print(f"\nNovos vinculos QSA inseridos: {len(new_rows)}")
print("=== RESUMO FINAL APOS QSA BRASILAPI ===")
print(resumo.to_string(index=False))
