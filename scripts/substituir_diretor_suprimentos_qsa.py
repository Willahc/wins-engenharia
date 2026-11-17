import os
import re
import subprocess
import time
import duckdb
import phonenumbers
from phonenumbers import PhoneNumberType
import requests

BASE_DIR = r"C:\Users\kbadmin\Documents\Projetos\01_Ecossistema_WiNS\Engenharia"
MAIN_DB = os.path.join(BASE_DIR, "Banco_Dados", "wins_engenharia.duckdb")
SUB_DB = os.path.join(BASE_DIR, "Banco_Dados", "obras_civil_industrial_2026_2027_100k.duckdb")
OUT_CSV = os.path.join(BASE_DIR, "Arquivos_Tratados", "obras_novas_com_decisores.csv").replace("\\", "/")

TARGET_IDS = [
    ("CGH.PH.GO.075540-0.1", "63660715000190", "62991127791"),
    ("BNDES-25203541", "48990728000134", "6434336371"),
    ("PCH.PH.SC.035782-0.1", "13799554000142", "4933589959"),
    ("PCH.PH.PR.040826-3.1", "27780961000112", "4131237300"),
    ("PCH.PH.RS.031016-6.1", "30002768000165", "5435110200"),
    ("PCH.PH.SC.037248-0.1", "49486827000146", "5435205200"),
    ("CGH.PH.MG.075539-7.1", "63671186000120", "1130400632"),
    ("PCH.PH.RJ.029515-9.1", "05288986000160", "2433651441"),
    ("PCH.PH.RS.037658-2.2", "42772409000176", "5434491499"),
    ("PCH.PH.MT.034468-0.1", "10187932000149", "6732919200"),
    ("PCH.PH.SC.032659-3.1", "36282940000168", None),
    ("BNDES-25901911", "19777075000101", "5433210082"),
]


def norm_phone(raw: str) -> str:
    d = re.sub(r"\D", "", str(raw or ""))
    if d.startswith("55") and len(d) in (12, 13):
        d = d[2:]
    if len(d) not in (10, 11) or len(set(d)) <= 2:
        return ""
    try:
        p = phonenumbers.parse(d, "BR")
        if phonenumbers.is_valid_number(p):
            return d
        if len(d) == 10 and d[0] != "0" and d[2] in "6789":
            cand = d[:2] + "9" + d[2:]
            p2 = phonenumbers.parse(cand, "BR")
            if phonenumbers.is_valid_number(p2) and phonenumbers.number_type(p2) == PhoneNumberType.MOBILE:
                return cand
    except Exception:
        pass
    return ""


def fetch_cnpj(cnpj: str):
    for url in (f"https://minhareceita.org/{cnpj}", f"https://brasilapi.com.br/api/cnpj/v1/{cnpj}"):
        try:
            r = requests.get(url, timeout=12, headers={"User-Agent": "WiNS-Engenharia/1.0"})
            if r.status_code == 200:
                return r.json()
        except Exception:
            pass
    return None


def main() -> None:
    con = duckdb.connect(MAIN_DB)
    inserted = 0

    for id_ext, cnpj_clean, tel_atual in TARGET_IDS:
        exists = con.execute("SELECT COUNT(*) FROM validacao_decisores_obras_novas WHERE id_externo = ?", [id_ext]).fetchone()[0]
        if exists > 0:
            continue

        data = fetch_cnpj(cnpj_clean)
        if not data:
            print(f"  [WARN] Sem retorno API para {cnpj_clean}")
            continue

        qsa = data.get("qsa") or []
        tel_api = norm_phone(data.get("ddd_telefone_1") or "")
        tel_final = norm_phone(tel_atual) or tel_api or None
        email_api = (data.get("email") or "").strip().lower()
        if not email_api or "@" not in email_api:
            email_api = None

        socios = []
        for s in qsa:
            nome_s = (s.get("nome_socio") or "").strip()
            qual = (s.get("qualificacao_socio") or "Sócio-Administrador").strip()
            if nome_s and not re.search(r"\b(ltda|s/a|s\.a|eireli|spe|energia|holding|participa)\b", nome_s, re.I):
                socios.append((nome_s, qual))

        if not socios:
            print(f"  [INFO] {cnpj_clean} sem socio PF direto no QSA")
            continue

        obra_row = con.execute("""
            SELECT fonte, obra_nome, obra_empresa, obra_cnpj, categoria_macro, obra_uf,
                   capex_estimado, capex_tipo, url_origem
            FROM obras_oficiais_ativas
            WHERE id_externo = ?
            LIMIT 1
        """, [id_ext]).fetchone()
        if not obra_row:
            continue

        for idx, (nome_s, qual) in enumerate(socios[:3]):
            dec_id = f"qsa_{cnpj_clean}_{idx+1}"
            acionavel = bool(tel_final or email_api)
            con.execute("""
                INSERT INTO validacao_decisores_obras_novas (
                    id_externo, fonte, obra_nome, obra_empresa, obra_cnpj, categoria_macro,
                    obra_uf, capex_estimado, capex_tipo, url_origem, tipo_match,
                    decisor_id, decisor_nome, decisor_cargo, decisor_email, decisor_telefone,
                    decisor_linkedin, qualidade_lead, is_contato_acionavel, perfil_decisor
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '4_QSA_BRASILAPI', ?, ?, ?, ?, ?, NULL, 'QSA_OFICIAL', ?, '3_DIRETORIA_EXECUTIVA')
            """, [
                id_ext, obra_row[0], obra_row[1], obra_row[2], obra_row[3], obra_row[4],
                obra_row[5], obra_row[6], obra_row[7], obra_row[8],
                dec_id, nome_s, qual, email_api, tel_final, acionavel
            ])
            inserted += 1
            print(f"  [OK] {cnpj_clean} -> {nome_s} ({qual}) | tel={tel_final}")
        time.sleep(0.5)

    con.execute(f"COPY validacao_decisores_obras_novas TO '{OUT_CSV}' (HEADER, DELIMITER ',');")
    con.execute("ANALYZE;")
    con.execute("CHECKPOINT;")
    con.close()

    if inserted > 0:
        sub = duckdb.connect(SUB_DB)
        main_sql = MAIN_DB.replace("\\", "/")
        sub.execute(f"ATTACH '{main_sql}' AS main_db (READ_ONLY);")
        sub.execute("CREATE OR REPLACE TABLE decisores_obras_novas AS SELECT * FROM main_db.validacao_decisores_obras_novas;")
        sub.execute("DETACH main_db;")
        sub.execute("CHECKPOINT;")
        sub.close()
        subprocess.run(["python", os.path.join(BASE_DIR, "scripts", "gerar_dashboard_html.py")], check=True)
        subprocess.run(["python", os.path.join(BASE_DIR, "scripts", "exportar_planilha_prospeccao.py")], check=True)

    print(f"Total socios PF inseridos: {inserted}")


if __name__ == "__main__":
    main()
