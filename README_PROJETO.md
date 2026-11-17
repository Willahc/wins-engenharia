# WiNS Engenharia — Base Consolidada de Obras & Decisores (2026–2027)

## Resumo do Estado Atual (2026-11-16)

- **Escopo**: Obras civis e industriais ativas (2026–2027), CAPEX > R$ 100 mil, Brasil, **100% com fonte oficial comprovada** (`ANEEL SIGA`, `BNDES`, `PNCP`) e sem duplicidade.
- **Total de Obras Validadas**: **2.604**
  - **CNPJ mapeado**: **2.604 (100,0%)**
  - **Contato acionável**: **2.505 (96,2%)**
  - **Telefone válido**: **2.348 (90,2%)**
  - **LinkedIn `/in/` válido**: **2.193 (84,2%)**
  - **Decisor Compras / Engenharia / CAPEX**: **2.091 (80,3%)**
  - **Domínio corporativo mapeado**: **2.011 (77,2%)** (**1.782** com servidor `MX` ativo)
  - **E-mail real (sem genéricos/chute)**: **1.768 (67,9%)**
  - **WhatsApp Business oficial do site**: **327 (12,6%)**
- **Decisores Únicos Acionáveis (Anti-Spam)**: **1.696 pessoas únicas**
- **Base de Fornecedores Integrada**: **4.090.553 CNPJs** saneados e indexados no DuckDB.

---

## Principais Entregáveis

- **Dashboard Interativo (4,49 MB)**: `Dashboard/wins_engenharia_validacao.html`
  - Menu lateral (`☰`), gráficos Chart.js (2×2), filtros em tempo real, página completa de **Obra**, página completa de **Fornecedor**, aba **Decisores Únicos (Anti-Spam)** e exportação CSV.
- **Planilha Multi-Abas para Prospecção**: `Arquivos_Tratados/WiNS_Prospeccao_Obras_2026_2027.xlsx`
- **CSV Anti-Spam (1 linha por pessoa)**: `Arquivos_Tratados/WiNS_Prospeccao_Por_Decisor_Unico.csv`
- **Banco DuckDB Principal**: `Banco_Dados/wins_engenharia.duckdb`
- **Banco DuckDB Leve (2026–2027)**: `Banco_Dados/obras_civil_industrial_2026_2027_100k.duckdb`
- **Lista de Telefones para Evolution API**: `Arquivos_Tratados/telefones_para_validar_evolution.csv` (`505` telefones únicos)

---

## Estrutura de Scripts (`scripts/`)

1. `tratar_bases_wins.py` — Saneamento inicial dos CSVs brutos (`Arquivos/` → `Arquivos_Tratados/`).
2. `criar_banco_duckdb.py` — Criação do banco DuckDB normalizado e indexado.
3. `captar_todas_fontes_2026_2027.py` — Coleta oficial nas APIs (`PNCP`, `ObrasGov`, `BNDES`, `ANEEL SIGA`, `Recife`) com filtro negativo anti-TI/serviços.
4. `resolver_cnpjs_aneel.py` & `enriquecer_qsa_brasilapi.py` & `fechar_lacunas_automatico.py` — Resolução de CNPJs, domínios corporativos e QSA.
5. `varrer_whatsapp_sites.py` & `validar_whatsapp_evolution.py` — Extração de `wa.me/` nos sites oficiais e validação via Evolution API.
6. `ingerir_retorno_openbot.py`, `ingerir_lacunas_openbot.py` & `ingerir_cargos_e_diretoria.py` — Ingestão deduplicada dos retornos dos agentes OpenBot (`OpenBot/`).
7. `limpar_cargos_decisores.py`, `auditar_e_limpar_ruido_cargos.py`, `higienizar_linkedin_banco.py`, `otimizar_cobertura_compras_eng.py`, `propagar_por_socio_qsa.py` — Higienização contínua e propagação societária.
8. `aplicar_otimizacoes_completas.py` & `gerar_dashboard_html.py` — Verificação DNS `MX`, visão anti-spam, Excel e regeneração do HTML.
9. `pipeline_diario.py` — Orquestrador único (`python scripts/pipeline_diario.py` ou `--skip-api`).
