import os
from datetime import datetime
import duckdb

BASE_DIR = r"C:\Users\kbadmin\Documents\Projetos\01_Ecossistema_WiNS\Engenharia"
MAIN_DB = os.path.join(BASE_DIR, "Banco_Dados", "wins_engenharia.duckdb")
OUT_ALERTS_CSV = os.path.join(BASE_DIR, "Arquivos_Tratados", "alertas_mudanca_fase.csv")


def compute_lead_score(con: duckdb.DuckDBPyConnection) -> None:
    """Calcula score_prioridade (0-100) transparente para todas as obras em todas_obras_consolidadas."""
    con.execute("""
        CREATE OR REPLACE TABLE todas_obras_consolidadas AS
        WITH canais_obra AS (
            SELECT
                id_externo,
                BOOL_OR(decisor_linkedin IS NOT NULL AND TRIM(decisor_linkedin) <> '') AS tem_linkedin,
                BOOL_OR(decisor_email IS NOT NULL AND TRIM(decisor_email) <> '') AS tem_email,
                BOOL_OR(decisor_telefone IS NOT NULL AND TRIM(decisor_telefone) <> '') AS tem_telefone
            FROM validacao_decisores_obras_novas
            WHERE is_contato_acionavel = TRUE
            GROUP BY 1
        )
        SELECT
            t.* EXCLUDE (score_prioridade),
            LEAST(100, (
                CASE t.fase_obra
                    WHEN '3_LI_LIBERADA_CANTEIRO' THEN 30
                    WHEN '4_EM_EXECUCAO_ANDAMENTO' THEN 26
                    WHEN '5_FINANCIAMENTO_ATIVO' THEN 22
                    WHEN '2_NAO_INICIADA_INICIAL' THEN 15
                    WHEN '1_ANUNCIO_LICITACAO_LP' THEN 10
                    ELSE 10
                END
                + CASE
                    WHEN COALESCE(t.capex_estimado, 0) >= 500000000 THEN 25
                    WHEN COALESCE(t.capex_estimado, 0) >= 100000000 THEN 20
                    WHEN COALESCE(t.capex_estimado, 0) >= 20000000 THEN 15
                    WHEN COALESCE(t.capex_estimado, 0) >= 5000000 THEN 10
                    WHEN COALESCE(t.capex_estimado, 0) > 0 THEN 5
                    ELSE 0
                END
                + CASE
                    WHEN COALESCE(t.decisores_operacionais, 0) > 0 THEN 25
                    WHEN COALESCE(t.decisores_acionaveis, 0) > 0 THEN 15
                    ELSE 0
                END
                + CASE WHEN COALESCE(c.tem_linkedin, FALSE) THEN 8 ELSE 0 END
                + CASE WHEN COALESCE(c.tem_email, FALSE) THEN 7 ELSE 0 END
                + CASE WHEN COALESCE(c.tem_telefone, FALSE) OR (t.whatsapp_oficial IS NOT NULL AND TRIM(t.whatsapp_oficial) <> '') THEN 5 ELSE 0 END
            ))::INTEGER AS score_prioridade
        FROM todas_obras_consolidadas t
        LEFT JOIN canais_obra c ON t.obra_id = c.id_externo;
    """)


def ensure_score_column(con: duckdb.DuckDBPyConnection) -> None:
    cols = {r[0] for r in con.execute("DESCRIBE todas_obras_consolidadas").fetchall()}
    if "score_prioridade" not in cols:
        con.execute("ALTER TABLE todas_obras_consolidadas ADD COLUMN score_prioridade INTEGER DEFAULT 0;")


def detect_phase_changes(con: duckdb.DuckDBPyConnection) -> dict:
    now_ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    today_str = datetime.now().strftime("%Y-%m-%d")

    con.execute("""
        CREATE TABLE IF NOT EXISTS historico_fases_obras (
            obra_id VARCHAR PRIMARY KEY,
            fase_obra VARCHAR,
            capex_estimado DOUBLE,
            decisores_acionaveis BIGINT,
            primeira_captura TIMESTAMP,
            ultima_atualizacao TIMESTAMP
        );
    """)

    con.execute("""
        CREATE TABLE IF NOT EXISTS alertas_mudanca_fase (
            data_alerta VARCHAR,
            tipo_alerta VARCHAR,
            obra_id VARCHAR,
            obra_nome VARCHAR,
            obra_empresa VARCHAR,
            obra_uf VARCHAR,
            fonte VARCHAR,
            capex_estimado DOUBLE,
            fase_anterior VARCHAR,
            fase_nova VARCHAR,
            score_prioridade INTEGER,
            criado_em TIMESTAMP
        );
    """)

    hist_count = con.execute("SELECT COUNT(*) FROM historico_fases_obras").fetchone()[0]
    mudancas = 0
    novas_alto_valor = 0

    if hist_count > 0:
        # 1. Detectar transicoes de fase em obras ja conhecidas
        con.execute(f"""
            INSERT INTO alertas_mudanca_fase
            SELECT
                '{today_str}' AS data_alerta,
                'MUDANCA_FASE' AS tipo_alerta,
                t.obra_id,
                t.obra_nome,
                t.obra_empresa,
                t.obra_uf,
                t.fonte,
                t.capex_estimado,
                h.fase_obra AS fase_anterior,
                t.fase_obra AS fase_nova,
                COALESCE(t.score_prioridade, 0),
                TIMESTAMP '{now_ts}'
            FROM todas_obras_consolidadas t
            JOIN historico_fases_obras h ON t.obra_id = h.obra_id
            WHERE COALESCE(t.fase_obra, '') <> COALESCE(h.fase_obra, '')
              AND NOT EXISTS (
                  SELECT 1 FROM alertas_mudanca_fase a
                  WHERE a.obra_id = t.obra_id AND a.data_alerta = '{today_str}'
                    AND a.fase_nova = t.fase_obra AND a.tipo_alerta = 'MUDANCA_FASE'
              );
        """)
        mudancas = con.execute(f"SELECT COUNT(*) FROM alertas_mudanca_fase WHERE data_alerta='{today_str}' AND tipo_alerta='MUDANCA_FASE'").fetchone()[0]

        # 2. Detectar obras novas de alto CAPEX (>= 10M) ou ja acionaveis em fase quente
        con.execute(f"""
            INSERT INTO alertas_mudanca_fase
            SELECT
                '{today_str}' AS data_alerta,
                'NOVA_OBRA_PRIORITARIA' AS tipo_alerta,
                t.obra_id,
                t.obra_nome,
                t.obra_empresa,
                t.obra_uf,
                t.fonte,
                t.capex_estimado,
                NULL AS fase_anterior,
                t.fase_obra AS fase_nova,
                COALESCE(t.score_prioridade, 0),
                TIMESTAMP '{now_ts}'
            FROM todas_obras_consolidadas t
            LEFT JOIN historico_fases_obras h ON t.obra_id = h.obra_id
            WHERE h.obra_id IS NULL
              AND (COALESCE(t.capex_estimado, 0) >= 10000000 OR COALESCE(t.score_prioridade, 0) >= 65)
              AND NOT EXISTS (
                  SELECT 1 FROM alertas_mudanca_fase a
                  WHERE a.obra_id = t.obra_id AND a.data_alerta = '{today_str}' AND a.tipo_alerta = 'NOVA_OBRA_PRIORITARIA'
              );
        """)
        novas_alto_valor = con.execute(f"SELECT COUNT(*) FROM alertas_mudanca_fase WHERE data_alerta='{today_str}' AND tipo_alerta='NOVA_OBRA_PRIORITARIA'").fetchone()[0]

    # Atualizar snapshot atual (upsert)
    con.execute(f"""
        INSERT INTO historico_fases_obras
        SELECT
            obra_id,
            fase_obra,
            capex_estimado,
            decisores_acionaveis,
            TIMESTAMP '{now_ts}',
            TIMESTAMP '{now_ts}'
        FROM todas_obras_consolidadas
        ON CONFLICT (obra_id) DO UPDATE SET
            fase_obra = EXCLUDED.fase_obra,
            capex_estimado = EXCLUDED.capex_estimado,
            decisores_acionaveis = EXCLUDED.decisores_acionaveis,
            ultima_atualizacao = EXCLUDED.ultima_atualizacao;
    """)

    # Exportar CSV de alertas (ultimos 30 dias / todos)
    con.execute("""
        SELECT * FROM alertas_mudanca_fase
        ORDER BY criado_em DESC, score_prioridade DESC
    """).fetchdf().to_csv(OUT_ALERTS_CSV, index=False, encoding="utf-8-sig")

    return {
        "historico_anterior": hist_count,
        "mudancas_hoje": mudancas,
        "novas_prioritarias_hoje": novas_alto_valor,
        "total_snapshot": con.execute("SELECT COUNT(*) FROM historico_fases_obras").fetchone()[0],
    }


def main() -> None:
    con = duckdb.connect(MAIN_DB)
    ensure_score_column(con)
    compute_lead_score(con)
    stats = detect_phase_changes(con)

    dist = con.execute("""
        SELECT
            CASE
                WHEN score_prioridade >= 80 THEN 'A_80_100_MUITO_QUENTE'
                WHEN score_prioridade >= 60 THEN 'B_60_79_QUENTE'
                WHEN score_prioridade >= 40 THEN 'C_40_59_MEDIO'
                ELSE 'D_0_39_BAIXO'
            END AS faixa_score,
            COUNT(*) AS qtd,
            ROUND(AVG(score_prioridade), 1) AS media
        FROM todas_obras_consolidadas
        GROUP BY 1
        ORDER BY 1
    """).fetchall()

    con.execute("CHECKPOINT;")
    con.close()

    print("=== LEAD SCORING (score_prioridade 0-100) ===")
    for faixa, qtd, media in dist:
        print(f"  {faixa}: {qtd:,} obras (media {media})")
    print("=== SNAPSHOT & ALERTAS DE FASE ===")
    print(f"  Historico anterior: {stats['historico_anterior']:,} | Snapshot atual: {stats['total_snapshot']:,}")
    print(f"  Mudancas de fase hoje: {stats['mudancas_hoje']:,} | Novas obras prioritarias hoje: {stats['novas_prioritarias_hoje']:,}")


if __name__ == "__main__":
    main()
