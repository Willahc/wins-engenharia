# WiNS Engenharia — Base Consolidada de Obras & Decisores (2026–2027)

## Resumo do Estado Atual (2026-11-19)

- **Escopo**: Obras civis e industriais ativas (2026–2027), CAPEX > R$ 100 mil, Brasil, combinando fontes oficiais (`ANEEL SIGA`, `ANEEL SIGET Transmissão`, `BNDES`, `PNCP`, `CVM Debêntures Incentivadas`, `IBAMA SISLIC`, `Portal de Obras MG`) + portais industriais (`ConVisão CNC`, `CIMM Investimentos`) e radar setorial (`BVMI 2026`).
- **Total de Obras Consolidadas (`todas_obras_consolidadas`)**: **4.490**
  - **ConVisão CNC (`convisao_cnc`)**: **490** obras deduplicadas (**157** com CNPJ, **306** com decisor acionável)
  - **ANEEL Transmissão (`aneel_transmissao` / SIGET)**: **756** empreendimentos de transmissão e subestações
  - **CVM Debêntures Incentivadas (`debentures_infra`)**: **53** ofertas de infraestrutura 2026+
  - **Portal de Obras MG (`portal_obras_mg`)**: **168** obras em andamento/a iniciar (**81** acionáveis, **693** vínculos técnicos/fiscais)
  - **IBAMA SISLIC (`ibama_sislic`)**: **42** licenças `LP`/`LI` de 2026 (**36** com CNPJ resolvido)
  - **CIMM Investimentos (`cimm_investimentos`)**: **14** investimentos industriais (**10** acionáveis)
  - **Obras com decisor acionável**: **3.794** (**84,5%**)
  - **Obras com Compras / Engenharia / CAPEX**: **2.576**
  - **Obras sem nenhum LinkedIn (fila pendente)**: **1.366** (`996` empresas únicas em `Arquivos_Tratados/fila_empresas_unicas_sem_linkedin.csv`)
- **Classificação por Fase da Obra (`fase_obra`)**:
  - `1_ANUNCIO_LICITACAO_LP`: **236**
  - `2_NAO_INICIADA_INICIAL`: **2.462**
  - `3_LI_LIBERADA_CANTEIRO`: **33**
  - `4_EM_EXECUCAO_ANDAMENTO`: **409**
  - `5_FINANCIAMENTO_ATIVO`: **176**
- **Decisores Únicos Acionáveis (`campanha_por_decisor_unico`)**: **3.118 pessoas únicas**
  - **Com LinkedIn validado**: **1.410**
  - **Com telefone validado (`google/libphonenumber`)**: **2.257**
  - **Com e-mail corporativo**: **1.178**
- **Radar BVMI (`bvmi_radar_2026` / `bvmi_match_obras_wins`)**: **189** projetos industriais de 2026, com **51** alertas cruzados em **178** pares de obras nominais no WiNS.
- **Base de Fornecedores Integrada**: **4.090.553 CNPJs** saneados e indexados no DuckDB.
- **GitHub & Render**: `https://github.com/Willahc/wins-engenharia` (Static Site Blueprint em `render.yaml`).

---

## Principais Entregáveis

- **Dashboard Interativo**: `Dashboard/wins_engenharia_validacao.html` (`66,9 KB`) + `Dashboard/data/wins_data.js` (`7,20 MB`)
  - Aba **Alertas & Radar BVMI**, filtro global por **Fase da Obra (`fase_obra`)** e **Status CRM** (`Novo`, `Em Contato`, `Proposta`, `Descartado` persistidos em `localStorage` com exportação/importação JSON), **Lead Score (`score_prioridade` 0–100)**, botão **Copiar Abordagem**, **Top 8 Fornecedores Aderentes** na página da Obra, barra de filtros dedicada para **Fornecedores** e aba **Decisores Únicos (Anti-Spam)**.
- **Planilha Multi-Abas para Prospecção**: `Arquivos_Tratados/WiNS_Prospeccao_Obras_2026_2027.xlsx` (`3,11 MB` — `7.756` prioritários Compras/Eng, `4.490` obras, `14.059` decisores acionáveis)
- **CSV Anti-Spam (1 linha por pessoa)**: `Arquivos_Tratados/WiNS_Prospeccao_Por_Decisor_Unico.csv`
- **Banco DuckDB Principal**: `Banco_Dados/wins_engenharia.duckdb`
- **Banco DuckDB Leve (2026–2027)**: `Banco_Dados/obras_civil_industrial_2026_2027_100k.duckdb`
- **Dossiês Executivos em PDF (`Entregas/`)**:
  - `Entregas/01_Analise_Executiva_Riteke_WiNS.pdf` e `Entregas/02_Mapeamento_10_Obras_Riteke_WiNS.pdf`
  - `Entregas/03_Analise_Executiva_Singapura_WiNS.pdf` e `Entregas/04_Mapeamento_10_Obras_Singapura_WiNS.pdf`

---

## Principais Scripts (`scripts/`)

1. `tratar_bases_wins.py` & `criar_banco_duckdb.py` — Saneamento inicial e construção do DuckDB normalizado.
2. `captar_todas_fontes_2026_2027.py`, `coletar_convisao_obras.py`, `coletar_cimm_investimentos.py`, `coletar_ibama_sislic.py`, `coletar_mg_obras.py`, `coletar_bvmi_radar.py` — Coletores oficiais e preditivos.
3. `resolver_cnpjs_aneel.py`, `resolver_cnpjs_convisao_rapidfuzz.py`, `enriquecer_qsa_brasilapi.py`, `substituir_diretor_suprimentos_qsa.py` — Resolução de CNPJs e QSA (`BrasilAPI` / `MinhaReceita`).
4. `normalizar_telefones_libphonenumber.py`, `auditar_emails_smtp.py`, `higienizar_linkedin_banco.py` — Validação de telefones (`google/libphonenumber`), auditoria SMTP e higiene de LinkedIns.
5. `classificar_fases_obras.py`, `detectar_mudancas_fase.py`, `vincular_decisores_consolidados_faltantes.py`, `enriquecer_convisao_cnpjs_qsa.py`, `limpar_duplicidades_cnc.py`, `sincronizar_todas_obras_consolidadas.py` — Classificação canônica de fases, Lead Scoring (`score_prioridade`), vínculo automático de decisores existentes (Skill `.agents/skills/vincular-decisores-novas-obras`), resolução CNPJ+QSA e sincronização.
6. `gerar_dashboard_html.py`, `exportar_planilha_prospeccao.py`, `gerar_dossie_cliente.py`, `gerar_fila_864_sem_linkedin.py`, `gerar_pdfs_riteke.py`, `gerar_pdfs_singapura.py`, `pipeline_diario.py` — Dashboard HTML+JS, Excel/CSV, dossiês PDF, filas OpenBot e orquestrador diário incremental (`--skip-api`, `--full`, `--publish`).
