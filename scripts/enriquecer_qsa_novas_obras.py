from concurrent.futures import ThreadPoolExecutor, as_completed
import os
import subprocess
import sys
import duckdb
import requests

BASE_DIR = r"C:\Users\kbadmin\Documents\Projetos\01_Ecossistema_WiNS\Engenharia"
MAIN_DB = os.path.join(BASE_DIR, "Banco_Dados", "wins_engenharia.duckdb")

PUBLIC_ORG_RE_TOKENS = ("PREFEITURA", "MUNICIPIO DE", "SECRETARIA DE", "ESTADO DE", "FUNDO MUNICIPAL", "CAMARA MUNICIPAL")


def fetch_minhareceita(cnpj: str) -> tuple[str, dict]:
    try:
        r = requests.get(f"https://minhareceita.org/{cnpj}", timeout=10)
        if r.status_code == 200:
            return cnpj, r.json()
    except Exception:
        pass
    return cnpj, {}


def main() -> None:
    con = duckdb.connect(MAIN_DB)

    targets = con.execute("""
        SELECT obra_id, fonte, obra_empresa, obra_cnpj, obra_uf, capex_estimado
        FROM todas_obras_consolidadas
        WHERE COALESCE(decisores_acionaveis, 0) = 0
          AND obra_cnpj IS NOT NULL AND LENGTH(TRIM(obra_cnpj)) = 14
        ORDER BY
            CASE
                WHEN fonte IN ('aneel_transmissao', 'aneel_siga', 'bndes_financiamento', 'convisao_cnc', 'ibama_sislic', 'cimm_investimentos') THEN 1
                ELSE 2
            END,
            COALESCE(capex_estimado, 0) DESC
    """).fetchall()

    # Filtrar orgaos publicos municipais/estaduais sem QSA societario privado
    filtered = []
    for row in targets:
        emp_up = (row[2] or "").upper()
        if any(tok in emp_up for tok in PUBLIC_ORG_RE_TOKENS):
            continue
        filtered.append(row)

    unique_cnpjs = sorted({r[3] for r in filtered})
    print(f"Obras alvo (sem decisor acionavel, com CNPJ nao-prefeitura): {len(filtered)} | CNPJs unicos: {len(unique_cnpjs)}")

    # Carregar emails/telefones ja existentes na tabela fornecedores como fallback
    forn_map = {}
    if unique_cnpjs:
        ph = ",".join("?" for _ in unique_cnpjs)
        for cnpj, em, tel in con.execute(
            f"SELECT cnpj, email, telefone_1 FROM fornecedores WHERE cnpj IN ({ph})", unique_cnpjs
        ).fetchall():
            forn_map[cnpj] = (em, tel)

    rf_cache: dict[str, dict] = {}
    with ThreadPoolExecutor(max_workers=6) as ex:
        futs = [ex.submit(fetch_minhareceita, c) for c in unique_cnpjs]
        for fut in as_completed(futs):
            c, data = fut.result()
            rf_cache[c] = data

    inserted = 0
    obras_enriquecidas = set()
    for oid, fonte, emp, cnpj, uf, capex in filtered:
        d = rf_cache.get(cnpj) or {}
        forn_em, forn_tel = forn_map.get(cnpj, (None, None))
        tel = (d.get("ddd_telefone_1") or "").strip() or (forn_tel or "").strip() or None
        email = (d.get("email") or "").strip().lower() or (forn_em or "").strip().lower() or None

        qsa = d.get("qsa") or []
        for s in qsa:
            nome = (s.get("nome_socio") or "").strip()
            cargo = (s.get("qualificacao_socio") or "Socio-Administrador").strip()
            if not nome or len(nome) < 4:
                continue
            if any(x in nome.upper() for x in ("LTDA", "S/A", "S.A.", "HOLDING", "EIRELI", "FUNDO", "BANCO", "PARTICIPACOES")):
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
                ) VALUES (?, ?, ?, ?, ?, ?, 'QSA_MINHARECEITA_PF', ?, ?, ?, ?, ?, '4_SOCIO_QSA')
                """,
                [oid, fonte, emp, cnpj, uf, capex, nome, cargo, email, tel, aci],
            )
            inserted += 1
            if aci:
                obras_enriquecidas.add(oid)

    con.execute("CHECKPOINT;")
    con.close()

    print(f"Socios QSA PF reais inseridos: {inserted} | Obras enriquecidas com contato acionavel: {len(obras_enriquecidas)}")

    if inserted > 0:
        subprocess.run([sys.executable, os.path.join(BASE_DIR, "scripts", "mapear_dominios_verificados.py")], check=True)
        subprocess.run([sys.executable, os.path.join(BASE_DIR, "scripts", "normalizar_telefones_libphonenumber.py")], check=True)
        subprocess.run([sys.executable, os.path.join(BASE_DIR, "scripts", "gerar_fila_864_sem_linkedin.py")], check=True)


if __name__ == "__main__":
    main()
