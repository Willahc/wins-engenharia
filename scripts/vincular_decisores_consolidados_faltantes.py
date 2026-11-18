import os
import re
import subprocess
import sys
import duckdb
from higienizar_linkedin_banco import validate_linkedin_url

BASE_DIR = r"C:\Users\kbadmin\Documents\Projetos\01_Ecossistema_WiNS\Engenharia"
MAIN_DB = os.path.join(BASE_DIR, "Banco_Dados", "wins_engenharia.duckdb")


def classify_perfil(cargo: str, funcao: str) -> str:
    txt = f"{cargo or ''} {funcao or ''}".lower()
    if re.search(r"\b(compra|suprimento|procurement|sourcing|aquisi|supply|material|contrato)\b", txt):
        return "1_COMPRADOR_SUPRIMENTOS"
    if re.search(r"\b(engenheir|obra|capex|projeto|manuten|planta|opera[cç][oõ]es|industrial|constru|infraestrutura|t[eé]cnico|implanta)\b", txt):
        return "2_ENGENHARIA_OBRAS_CAPEX"
    if re.search(r"\b(diretor|ceo|cfo|coo|vp|vice|presidente|superintendente|head|gerente geral)\b", txt):
        return "3_DIRETORIA_EXECUTIVA"
    if re.search(r"\b(s[oó]cio|administrador|titular|propriet[aá]rio)\b", txt):
        return "4_SOCIO_QSA"
    return "5_OUTRO_NAO_CLASSIFICADO"


def vincular_decisores_existentes(con: duckdb.DuckDBPyConnection) -> tuple[int, int]:
    """Vincula automaticamente decisores ja mapeados (com LinkedIn validado) para obras novas sem LinkedIn."""
    candidates = con.execute("""
        WITH sem_lk AS (
            SELECT obra_id, fonte, obra_empresa, obra_cnpj, obra_cnpj_raiz, obra_uf, capex_estimado
            FROM todas_obras_consolidadas
            WHERE obra_id NOT IN (
                SELECT DISTINCT id_externo
                FROM validacao_decisores_obras_novas
                WHERE decisor_linkedin IS NOT NULL AND TRIM(decisor_linkedin) <> ''
            )
        )
        SELECT DISTINCT
            s.obra_id,
            s.fonte,
            s.obra_empresa,
            s.obra_cnpj,
            s.obra_uf,
            s.capex_estimado,
            d.decisor_nome,
            d.decisor_cargo,
            d.funcao_canonica,
            d.email,
            d.telefone,
            d.linkedin_url,
            CASE
                WHEN s.obra_cnpj IS NOT NULL AND TRIM(s.obra_cnpj) <> '' AND s.obra_cnpj = d.cnpj THEN 'CONSOLIDADO_CNPJ_EXATO'
                WHEN s.obra_cnpj_raiz IS NOT NULL AND LENGTH(TRIM(s.obra_cnpj_raiz)) = 8 AND s.obra_cnpj_raiz = SUBSTR(d.cnpj, 1, 8) THEN 'CONSOLIDADO_CNPJ_RAIZ'
                ELSE 'CONSOLIDADO_EMPRESA_EXATA'
            END AS tipo_match
        FROM sem_lk s
        JOIN decisores_por_empresa_consolidado d
          ON (
              (s.obra_cnpj IS NOT NULL AND TRIM(s.obra_cnpj) <> '' AND s.obra_cnpj = d.cnpj)
              OR (s.obra_cnpj_raiz IS NOT NULL AND LENGTH(TRIM(s.obra_cnpj_raiz)) = 8 AND s.obra_cnpj_raiz = SUBSTR(d.cnpj, 1, 8))
              OR (s.obra_empresa IS NOT NULL AND LENGTH(TRIM(s.obra_empresa)) >= 6 AND UPPER(TRIM(s.obra_empresa)) = UPPER(TRIM(d.empresa)))
          )
        WHERE d.linkedin_url IS NOT NULL AND TRIM(d.linkedin_url) <> ''
          AND LOWER(COALESCE(d.linkedin_valido, '')) IN ('sim', 'true', '1')
          AND LOWER(COALESCE(d.linkedin_confere_nome, '')) = 'sim'
          AND d.decisor_nome IS NOT NULL AND TRIM(d.decisor_nome) <> ''
    """).fetchall()

    inserted = 0
    obras_atingidas = set()
    rejected = 0

    for (
        obra_id, fonte, emp, cnpj, uf, capex,
        nome, cargo, funcao, email, tel, lk_raw, tipo_match
    ) in candidates:
        lk_clean = validate_linkedin_url(lk_raw, nome)
        if not lk_clean:
            rejected += 1
            continue

        exists = con.execute(
            "SELECT COUNT(*) FROM validacao_decisores_obras_novas WHERE id_externo = ? AND LOWER(TRIM(decisor_nome)) = LOWER(TRIM(?))",
            [obra_id, nome],
        ).fetchone()[0]

        if exists > 0:
            # Atualiza o LinkedIn caso o registro ja exista sem LinkedIn
            updated = con.execute(
                """
                UPDATE validacao_decisores_obras_novas
                SET decisor_linkedin = ?, is_contato_acionavel = TRUE
                WHERE id_externo = ?
                  AND LOWER(TRIM(decisor_nome)) = LOWER(TRIM(?))
                  AND (decisor_linkedin IS NULL OR TRIM(decisor_linkedin) = '')
                """,
                [lk_clean, obra_id, nome],
            ).rowcount
            if updated:
                inserted += updated
                obras_atingidas.add(obra_id)
            continue

        perfil = classify_perfil(cargo, funcao)
        email_clean = (email or "").strip().lower() or None
        tel_clean = (tel or "").strip() or None
        con.execute(
            """
            INSERT INTO validacao_decisores_obras_novas (
                id_externo, fonte, obra_empresa, obra_cnpj, obra_uf, capex_estimado,
                tipo_match, decisor_nome, decisor_cargo, decisor_email, decisor_telefone,
                decisor_linkedin, is_contato_acionavel, perfil_decisor
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, TRUE, ?)
            """,
            [obra_id, fonte, emp, cnpj, uf, capex, tipo_match, nome.strip(), (cargo or "").strip() or None, email_clean, tel_clean, lk_clean, perfil],
        )
        inserted += 1
        obras_atingidas.add(obra_id)

    print(f"Candidatos avaliados: {len(candidates)} | Rejeitados por higiene LinkedIn: {rejected}")
    print(f"Vinculos inseridos/atualizados: {inserted} | Obras recuperadas com LinkedIn valido: {len(obras_atingidas)}")
    return inserted, len(obras_atingidas)


def main() -> None:
    con = duckdb.connect(MAIN_DB)
    inserted, obras_rec = vincular_decisores_existentes(con)
    con.execute("CHECKPOINT;")
    con.close()

    if obras_rec > 0 or inserted > 0:
        subprocess.run([sys.executable, os.path.join(BASE_DIR, "scripts", "normalizar_telefones_libphonenumber.py")], check=True)
        subprocess.run([sys.executable, os.path.join(BASE_DIR, "scripts", "gerar_fila_864_sem_linkedin.py")], check=True)


if __name__ == "__main__":
    main()
