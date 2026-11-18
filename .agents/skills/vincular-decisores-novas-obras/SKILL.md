---
name: vincular-decisores-novas-obras
description: >-
  Regra obrigatória do projeto WiNS Engenharia: sempre que uma nova obra entrar no banco
  DuckDB (obras_oficiais_ativas / todas_obras_consolidadas), validar automaticamente se já
  existe decisor mapeado e higienizado no banco consolidado (decisores_por_empresa_consolidado)
  antes de enviar para busca externa ou OpenBot.
---

# Regra: Validar Decisores Existentes ao Inserir Novas Obras

Sempre que uma nova obra for coletada ou inserida em `Banco_Dados/wins_engenharia.duckdb`:

1. **Nunca considerar uma obra nova como "sem decisor" antes de cruzar com o banco interno:**
   - Cruzar `obra_cnpj`, `obra_cnpj_raiz` (8 dígitos) e `UPPER(TRIM(obra_empresa))` com `decisores_por_empresa_consolidado`.
   - Aceitar **somente** vínculos com `linkedin_valido = 'sim'`, `linkedin_confere_nome = 'sim'` e validados por `validate_linkedin_url()` em `scripts/higienizar_linkedin_banco.py`.
   - Nunca inventar URLs de LinkedIn, nomes genéricos de cargo ou e-mails não verificados.

2. **Execução Automática na Sincronização:**
   - A função `vincular_decisores_existentes(con)` de `scripts/vincular_decisores_consolidados_faltantes.py` está acoplada diretamente em `scripts/sincronizar_todas_obras_consolidadas.py` (executado por `scripts/pipeline_diario.py`).
   - Sempre que novos coletores inserirem obras em `obras_oficiais_ativas`, rodar `python scripts/sincronizar_todas_obras_consolidadas.py` (ou `python scripts/pipeline_diario.py --skip-api`) para vincular decisores existentes, recalcular `score_prioridade`, detectar mudanças de fase e regenerar o Dashboard/Excel.

3. **Geração de Fila Residual (somente após o cruzamento interno):**
   - Após a sincronização, rodar `python scripts/gerar_fila_864_sem_linkedin.py` para gerar `Arquivos_Tratados/fila_864_obras_sem_linkedin.csv` e `Arquivos_Tratados/fila_empresas_unicas_sem_linkedin.csv` apenas com o que realmente não existe no banco.
