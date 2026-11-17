# WiNS Engenharia — Base Consolidada de Obras & Decisores (2026–2027)

## Resumo do Estado Atual (2026-11-17)

- **Escopo**: Obras civis e industriais ativas (2026–2027), CAPEX > R$ 100 mil, Brasil, com fontes oficiais (`ANEEL SIGA`, `BNDES`, `PNCP`) + portais industriais (`ConVisão CNC`, `CIMM Investimentos`) e radar setorial (`BVMI 2026`).
- **Total de Obras Consolidadas (`todas_obras_consolidadas`)**: **3.106**
  - Base oficial (`ANEEL`, `BNDES`, `PNCP`): **2.604**
  - **ConVisão CNC (`convisao_cnc`)**: **488** obras deduplicadas
  - **CIMM Investimentos (`cimm_investimentos`)**: **14** investimentos industriais
  - **Obras com decisor acionável**: **2.602** (**83,8%**)
  - **Obras com Compras / Engenharia / CAPEX**: **2.004**
- **Decisores Únicos Acionáveis (`campanha_por_decisor_unico`)**: **1.882 pessoas únicas**
  - **Com LinkedIn auditado**: **881** (620 perfis validados na web + 234 de diretoria + 199 de ConVisão/CIMM)
  - **Com telefone validado (`google/libphonenumber`)**: **1.344** (`815` linhas recuperadas para celular 11 dígitos)
  - **Com e-mail corporativo pós-auditoria SMTP**: **711** (`72` bounces/inválidos/no-MX removidos; `raizen.com` corrigido)
- **Radar BVMI (`bvmi_radar_2026` / `bvmi_match_obras_wins`)**: **189** projetos industriais de 2026, com **51** alertas cruzados em **178** pares de obras nominais no WiNS.
- **Base de Fornecedores Integrada**: **4.090.553 CNPJs** saneados e indexados no DuckDB.
- **GitHub & Render**: `https://github.com/Willahc/wins-engenharia` (Static Site Blueprint em `render.yaml`).

---

## Principais Entregáveis

- **Dashboard Interativo (4,60+ MB)**: `Dashboard/wins_engenharia_validacao.html`
- **Planilha Multi-Abas para Prospecção**: `Arquivos_Tratados/WiNS_Prospeccao_Obras_2026_2027.xlsx`
- **CSV Anti-Spam (1 linha por pessoa)**: `Arquivos_Tratados/WiNS_Prospeccao_Por_Decisor_Unico.csv`
- **Banco DuckDB Principal**: `Banco_Dados/wins_engenharia.duckdb`
- **Banco DuckDB Leve (2026–2027)**: `Banco_Dados/obras_civil_industrial_2026_2027_100k.duckdb`
- **Entregas Especiais (Riteke)**: `Entregas/01_Analise_Executiva_Riteke_WiNS.pdf` e `Entregas/02_Mapeamento_10_Obras_Riteke_WiNS.pdf`
- **Fila pendente para amanhã**: `Arquivos_Tratados/fila_openbot_convisao_cimm_privadas.csv` (`332` obras privadas restantes do ConVisão)

---

## Principais Scripts (`scripts/`)

1. `tratar_bases_wins.py` & `criar_banco_duckdb.py` — Saneamento inicial e construção do DuckDB normalizado.
2. `captar_todas_fontes_2026_2027.py`, `coletar_convisao_obras.py`, `coletar_cimm_investimentos.py`, `coletar_bvmi_radar.py` — Coleta em APIs oficiais (`PNCP`, `BNDES`, `ANEEL`) e portais (`ConVisão`, `CIMM`, `BVMI`).
3. `resolver_cnpjs_aneel.py`, `resolver_cnpjs_convisao_rapidfuzz.py`, `enriquecer_qsa_brasilapi.py`, `substituir_diretor_suprimentos_qsa.py` — Resolução de CNPJs e QSA (`BrasilAPI` / `MinhaReceita`).
4. `normalizar_telefones_libphonenumber.py`, `auditar_emails_smtp.py`, `higienizar_linkedin_banco.py` — Validação de telefones (`google/libphonenumber`), auditoria SMTP de e-mails e higiene de LinkedIns.
5. `ingerir_cargos_e_diretoria.py`, `ingerir_validacao_linkedin.py`, `ingerir_convisao_cimm_decisores.py`, `limpar_duplicidades_cnc.py`, `sincronizar_todas_obras_consolidadas.py` — Ingestão, deduplicação e sincronização.
6. `gerar_dashboard_html.py`, `exportar_planilha_prospeccao.py`, `gerar_pdfs_riteke.py`, `pipeline_diario.py` — Dashboard HTML, Excel/CSV, PDFs e orquestração.
