import json
import os
import duckdb

BASE_DIR = r"C:\Users\kbadmin\Documents\Projetos\01_Ecossistema_WiNS\Engenharia"
MAIN_DB = os.path.join(BASE_DIR, "Banco_Dados", "wins_engenharia.duckdb")
OUT_DIR = os.path.join(BASE_DIR, "Dashboard")
os.makedirs(OUT_DIR, exist_ok=True)
OUT_HTML = os.path.join(OUT_DIR, "wins_engenharia_validacao.html")

con = duckdb.connect(MAIN_DB, read_only=True)

summary = {
    "obras_antigas": con.execute("SELECT COUNT(*) FROM obras").fetchone()[0],
    "decisores_acionaveis": con.execute("SELECT COUNT(*) FROM decisores WHERE is_contato_acionavel").fetchone()[0],
    "fornecedores_total": con.execute("SELECT COUNT(*) FROM fornecedores").fetchone()[0],
}

# Formato colunar compacto (arrays em vez de objetos com chaves repetidas)
obras_cols = [
    "id", "fonte", "nome", "empresa", "cnpj", "cat", "uf", "mun",
    "capex", "capTipo", "dtIni", "dtFim", "sit", "url", "matchForn", "dom", "mx", "wa", "telSite",
    "fornUf", "qDec", "qAci", "qOp", "score"
]
obras_rows = con.execute("""
SELECT
    o.obra_id,
    o.fonte,
    SUBSTR(COALESCE(o.obra_nome, ''), 1, 220),
    COALESCE(SUBSTR(o.obra_empresa, 1, 100), ''),
    COALESCE(o.obra_cnpj, ''),
    COALESCE(o.categoria_macro, ''),
    COALESCE(o.obra_uf, ''),
    COALESCE(o.obra_municipio, ''),
    ROUND(COALESCE(o.capex_estimado, 0), 0),
    CASE WHEN o.capex_tipo = 'PROXY_POTENCIA_KW' THEN 1 ELSE 0 END,
    COALESCE(CAST(o.data_inicio_prevista AS VARCHAR), ''),
    COALESCE(CAST(o.data_fim_prevista AS VARCHAR), ''),
    COALESCE(SUBSTR(o.situacao, 1, 60), ''),
    o.url_origem,
    CASE WHEN o.tem_match_fornecedor THEN 1 ELSE 0 END,
    COALESCE(o.dominio_corporativo, ''),
    CASE WHEN COALESCE(o.mx_ativo, FALSE) THEN 1 ELSE 0 END,
    COALESCE(SPLIT_PART(o.whatsapp_oficial, ';', 1), ''),
    COALESCE(SPLIT_PART(o.telefones_site, ';', 1), ''),
    COALESCE(f.fornecedores_locais_acionaveis_uf, 0),
    COALESCE(o.total_decisores, 0),
    COALESCE(o.decisores_acionaveis, 0),
    COALESCE(o.decisores_operacionais, 0),
    (
        CASE WHEN COALESCE(o.decisores_operacionais, 0) > 0 THEN 40 WHEN COALESCE(o.decisores_acionaveis, 0) > 0 THEN 20 ELSE 0 END
        + CASE WHEN COALESCE(o.mx_ativo, FALSE) THEN 20 WHEN o.dominio_corporativo IS NOT NULL THEN 10 ELSE 0 END
        + CASE WHEN o.whatsapp_oficial IS NOT NULL THEN 15 ELSE 0 END
        + CASE WHEN o.capex_estimado >= 10000000 THEN 15 WHEN o.capex_estimado >= 1000000 THEN 10 ELSE 5 END
        + CASE WHEN o.tem_match_fornecedor THEN 10 ELSE 0 END
    ) AS icp_score
FROM todas_obras_consolidadas o
LEFT JOIN vw_obra_fornecedores_elegiveis f ON o.obra_id = f.obra_id
ORDER BY icp_score DESC, o.capex_estimado DESC;
""").fetchall()

dec_cols = [
    "id", "fonte", "empresa", "cnpj", "uf", "match", "perfil",
    "nome", "cargo", "email", "tel", "lk", "aci"
]
dec_rows = con.execute("""
SELECT
    id_externo,
    fonte,
    COALESCE(SUBSTR(obra_empresa, 1, 80), ''),
    COALESCE(obra_cnpj, ''),
    obra_uf,
    tipo_match,
    COALESCE(perfil_decisor, '5_OUTRO_NAO_CLASSIFICADO'),
    decisor_nome,
    COALESCE(SUBSTR(decisor_cargo, 1, 90), ''),
    COALESCE(decisor_email, ''),
    COALESCE(decisor_telefone, ''),
    COALESCE(decisor_linkedin, ''),
    CASE WHEN is_contato_acionavel THEN 1 ELSE 0 END
FROM validacao_decisores_obras_novas
ORDER BY perfil_decisor, is_contato_acionavel DESC, decisor_nome;
""").fetchall()

uni_cols = [
    "nome", "perfil", "cargo", "email", "tel", "lk", "dom", "wa",
    "qObras", "capex", "ufs", "obraPrinc", "urlPrinc", "score"
]
uni_rows = con.execute("""
SELECT
    decisor_nome,
    perfil_prioritario,
    COALESCE(SUBSTR(decisor_cargo, 1, 90), ''),
    COALESCE(decisor_email, ''),
    COALESCE(decisor_telefone, ''),
    COALESCE(decisor_linkedin, ''),
    COALESCE(dominio_corporativo, ''),
    COALESCE(SPLIT_PART(whatsapp_oficial_empresa, ';', 1), ''),
    qtd_obras_sob_gestao,
    ROUND(COALESCE(capex_total_sob_gestao, 0), 0),
    COALESCE(SUBSTR(ufs_atuacao, 1, 40), ''),
    COALESCE(SUBSTR(obra_principal_maior_capex, 1, 140), ''),
    COALESCE(url_obra_principal, ''),
    (
        CASE perfil_prioritario WHEN '1_COMPRADOR_SUPRIMENTOS' THEN 40 WHEN '2_GESTOR_TECNICO_OBRA' THEN 35 WHEN '3_DIRETORIA_EXECUTIVA' THEN 25 ELSE 10 END
        + CASE WHEN decisor_email IS NOT NULL THEN 25 ELSE 0 END
        + CASE WHEN decisor_linkedin IS NOT NULL THEN 15 ELSE 0 END
        + CASE WHEN COALESCE(dominio_mx_ativo, FALSE) THEN 10 ELSE 0 END
        + CASE WHEN whatsapp_oficial_empresa IS NOT NULL THEN 10 ELSE 0 END
    ) AS icp_score
FROM campanha_por_decisor_unico
ORDER BY icp_score DESC, capex_total_sob_gestao DESC;
""").fetchall()

fontes = con.execute("""
SELECT fonte, tipo, obras, com_url, pct_com_url, capex_bi, flag_capex_outlier
FROM fontes_obras ORDER BY obras DESC;
""").fetchall()

# 5. Fornecedores: resumo por UF/Setor + Top 1.500 estruturados/relevantes de engenharia/construcao/energia
forn_resumo = con.execute("""
SELECT uf, setor_consolidado, total_fornecedores, fornecedores_acionaveis, fornecedores_estruturados
FROM resumo_fornecedores_uf_setor
ORDER BY fornecedores_acionaveis DESC;
""").fetchall()

forn_cols = [
    "cnpj", "razao", "fantasia", "cnae", "cnaeDesc", "setor", "porte",
    "capSocial", "tipoEstab", "uf", "mun", "end", "cep", "tel1", "tel2", "email", "matches"
]
forn_rows = con.execute("""
SELECT
    cnpj,
    COALESCE(SUBSTR(razao_social, 1, 100), ''),
    COALESCE(SUBSTR(nome_fantasia, 1, 70), ''),
    cnae_principal,
    COALESCE(SUBSTR(cnae_descricao, 1, 90), ''),
    setor_consolidado,
    COALESCE(porte_consolidado, ''),
    ROUND(COALESCE(capital_social, 0), 0),
    COALESCE(tipo_estabelecimento, ''),
    uf,
    COALESCE(municipio_nome, ''),
    COALESCE(TRIM(COALESCE(logradouro,'') || ' ' || COALESCE(numero,'') || ' - ' || COALESCE(bairro,'')), ''),
    COALESCE(cep, ''),
    COALESCE(telefone_1, ''),
    COALESCE(telefone_2, ''),
    COALESCE(email, ''),
    COALESCE(matches_count, 0)
FROM fornecedores
WHERE is_contato_acionavel = TRUE
  AND razao_social IS NOT NULL
  AND setor_consolidado IN (
      'CONSTRUCAO_ESPECIALIZADA', 'CONSTRUCAO_EDIFICIOS', 'INFRAESTRUTURA',
      'ENGENHARIA_ARQUITETURA', 'ENERGIA', 'SANEAMENTO', 'LOCACAO_MAQUINAS_EQUIPAMENTOS', 'METALURGIA_ESTRUTURAS'
  )
  AND (porte_consolidado IN ('GRANDE', 'MEDIA') OR matches_count > 0)
ORDER BY matches_count DESC, COALESCE(capital_social, 0) DESC
LIMIT 1500;
""").fetchall()

con.close()

data_json = json.dumps({
    "summary": summary,
    "obrasCols": obras_cols,
    "obras": [list(r) for r in obras_rows],
    "decCols": dec_cols,
    "dec": [list(r) for r in dec_rows],
    "uniCols": uni_cols,
    "uni": [list(r) for r in uni_rows],
    "fornCols": forn_cols,
    "forn": [list(r) for r in forn_rows],
    "fornResumo": [list(r) for r in forn_resumo],
    "fontes": [list(r) for r in fontes],
}, ensure_ascii=False, separators=(",", ":"))

html_template = """<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>WiNS Engenharia — Dashboard de Validação & Prospecção</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.4/dist/chart.umd.min.js"></script>
<style>
  :root {
    --bg: #0f172a; --surface: #1e293b; --surface-2: #263348; --border: #334155;
    --text: #f1f5f9; --muted: #94a3b8; --accent: #38bdf8; --accent-2: #818cf8;
    --green: #22c55e; --amber: #f59e0b; --sidebar-w: 270px;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: var(--bg); color: var(--text); line-height: 1.45; }
  .topbar { position: sticky; top: 0; z-index: 40; display: flex; align-items: center; justify-content: space-between; height: 58px; padding: 0 20px; background: rgba(15, 23, 42, 0.96); backdrop-filter: blur(8px); border-bottom: 1px solid var(--border); }
  .topbar-left { display: flex; align-items: center; gap: 14px; }
  .hamburger { width: 38px; height: 38px; border-radius: 8px; border: 1px solid var(--border); background: var(--surface); color: var(--text); cursor: pointer; font-size: 20px; display: flex; align-items: center; justify-content: center; }
  .hamburger:hover { border-color: var(--accent); color: var(--accent); }
  .brand { font-weight: 700; font-size: 16px; }
  .brand span { color: var(--accent); }
  .topbar-right { display: flex; align-items: center; gap: 10px; }
  .btn { padding: 7px 13px; border-radius: 8px; border: 1px solid var(--border); background: var(--surface); color: var(--text); cursor: pointer; font-size: 13px; font-weight: 500; }
  .btn:hover { border-color: var(--accent); color: var(--accent); }
  .btn-primary { background: var(--accent); color: #0f172a; border-color: var(--accent); font-weight: 600; }
  .overlay { position: fixed; inset: 0; background: rgba(0,0,0,0.55); z-index: 45; display: none; }
  .overlay.open { display: block; }
  .sidebar { position: fixed; top: 0; left: 0; bottom: 0; width: var(--sidebar-w); background: var(--surface); border-right: 1px solid var(--border); z-index: 50; transform: translateX(-100%); transition: transform 0.2s ease; display: flex; flex-direction: column; padding: 18px 14px; }
  .sidebar.open { transform: translateX(0); }
  .sidebar-header { display: flex; align-items: center; justify-content: space-between; padding-bottom: 14px; margin-bottom: 14px; border-bottom: 1px solid var(--border); }
  .nav-item { display: flex; align-items: center; justify-content: space-between; padding: 10px 12px; border-radius: 8px; cursor: pointer; color: var(--muted); font-size: 13.5px; font-weight: 500; margin-bottom: 4px; }
  .nav-item:hover { background: var(--surface-2); color: var(--text); }
  .nav-item.active { background: rgba(56, 189, 248, 0.14); color: var(--accent); }
  .badge { font-size: 11px; padding: 2px 7px; border-radius: 999px; background: var(--surface-2); color: var(--text); border: 1px solid var(--border); }
  .sidebar-footer { margin-top: auto; padding-top: 12px; border-top: 1px solid var(--border); font-size: 12px; color: var(--muted); }
  .main { max-width: 1500px; margin: 0 auto; padding: 18px; }
  .filters-card { background: var(--surface); border: 1px solid var(--border); border-radius: 12px; padding: 14px; margin-bottom: 18px; }
  .filters-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 185px), 1fr)); gap: 10px; align-items: end; }
  .field label { display: block; font-size: 11px; text-transform: uppercase; letter-spacing: 0.4px; color: var(--muted); margin-bottom: 4px; }
  .field input, .field select { width: 100%; padding: 8px 10px; border-radius: 8px; border: 1px solid var(--border); background: var(--bg); color: var(--text); font-size: 13px; }
  .field input:focus, .field select:focus { outline: none; border-color: var(--accent); }
  .kpis { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 14px; margin-bottom: 18px; }
  .kpi { background: var(--surface); border: 1px solid var(--border); border-radius: 12px; padding: 14px; }
  .kpi-label { font-size: 12px; color: var(--muted); margin-bottom: 4px; }
  .kpi-val { font-size: clamp(18px, 2.2vw, 24px); font-weight: 700; }
  .kpi-sub { font-size: 12px; color: var(--accent); margin-top: 3px; }
  .charts-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px; margin-bottom: 20px; }
  .card { background: linear-gradient(180deg, rgba(30,41,59,0.96), rgba(22,31,48,0.98)); border: 1px solid rgba(148,163,184,0.16); border-radius: 14px; padding: 16px; box-shadow: 0 10px 28px rgba(2,6,23,0.35); min-width: 0; }
  .card-title { font-size: 14px; font-weight: 600; margin-bottom: 12px; display: flex; flex-wrap: wrap; gap: 6px; align-items: center; justify-content: space-between; color: #e2e8f0; }
  .card-sub { font-size: 11px; color: var(--muted); font-weight: 400; }
  .chart-box { position: relative; height: 280px; width: 100%; }
  .table-wrap { overflow-x: auto; -webkit-overflow-scrolling: touch; }
  .pagination { display: flex; flex-wrap: wrap; gap: 10px; align-items: center; justify-content: space-between; margin-top: 12px; font-size: 13px; color: var(--muted); }
  @media (max-width: 960px) {
    .kpis { grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; }
    .charts-grid { grid-template-columns: 1fr; }
  }
  @media (max-width: 768px) {
    .topbar { padding: 0 12px; height: auto; min-height: 56px; flex-wrap: wrap; gap: 8px; padding-top: 8px; padding-bottom: 8px; }
    .brand { font-size: 14px; }
    .btn { padding: 6px 10px; font-size: 12px; }
    .main { padding: 12px; }
    .chart-box { height: 230px; }
    .modal { padding: 14px; max-height: 90vh; }
  }
  @media (max-width: 460px) {
    .kpis { grid-template-columns: 1fr; }
    .topbar-right { width: 100%; justify-content: flex-end; }
  }
  .bar-row { display: flex; align-items: center; gap: 10px; margin-bottom: 8px; font-size: 12px; }
  .bar-label { width: 155px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; color: var(--muted); }
  .bar-track { flex: 1; height: 9px; background: var(--bg); border-radius: 999px; overflow: hidden; }
  .bar-fill { height: 100%; background: linear-gradient(90deg, var(--accent), var(--accent-2)); border-radius: 999px; }
  .bar-val { width: 75px; text-align: right; font-variant-numeric: tabular-nums; }
  .table-wrap { overflow-x: auto; }
  table { width: 100%; border-collapse: collapse; font-size: 12.5px; }
  th, td { padding: 9px 8px; text-align: left; border-bottom: 1px solid var(--border); vertical-align: top; }
  th { font-size: 11px; text-transform: uppercase; letter-spacing: 0.4px; color: var(--muted); background: var(--surface-2); position: sticky; top: 0; cursor: pointer; }
  tr:hover td { background: rgba(56, 189, 248, 0.05); }
  .pill { display: inline-block; padding: 2px 7px; border-radius: 999px; font-size: 11px; font-weight: 600; }
  .pill-civil { background: rgba(56, 189, 248, 0.15); color: #38bdf8; }
  .pill-ind { background: rgba(129, 140, 248, 0.18); color: #a5b4fc; }
  .pill-ok { background: rgba(34, 197, 94, 0.16); color: #4ade80; }
  .pill-warn { background: rgba(245, 158, 11, 0.18); color: #fbbf24; }
  .pill-muted { background: var(--surface-2); color: var(--muted); }
  a { color: var(--accent); text-decoration: none; }
  a:hover { text-decoration: underline; }
  .pagination { display: flex; align-items: center; justify-content: space-between; margin-top: 12px; font-size: 13px; color: var(--muted); }
  .section { display: none; }
  .section.active { display: block; }
  .modal-bg { position: fixed; inset: 0; background: rgba(0,0,0,0.7); z-index: 60; display: none; align-items: center; justify-content: center; padding: 20px; }
  .modal-bg.open { display: flex; }
  .modal { background: var(--surface); border: 1px solid var(--border); border-radius: 14px; max-width: 920px; width: 100%; max-height: 85vh; overflow-y: auto; padding: 20px; }
  .modal-head { display: flex; justify-content: space-between; align-items: start; gap: 12px; margin-bottom: 14px; }
</style>
</head>
<body>
<div class="overlay" id="overlay" onclick="toggleSidebar(false)"></div>

<aside class="sidebar" id="sidebar">
  <div class="sidebar-header">
    <div class="brand">WiNS <span>Engenharia</span></div>
    <button class="hamburger" onclick="toggleSidebar(false)">✕</button>
  </div>
  <div class="nav-item active" onclick="switchSection('overview', this)"><span>📊 Visão Geral & KPIs</span></div>
  <div class="nav-item" onclick="switchSection('obras', this)"><span>🏗️ Obras Validadas</span><span class="badge" id="nav-cnt-obras">0</span></div>
  <div class="nav-item" onclick="switchSection('unicos', this)"><span>🎯 Decisores Únicos (Anti-Spam)</span><span class="badge" id="nav-cnt-unicos">0</span></div>
  <div class="nav-item" onclick="switchSection('decisores', this)"><span>👤 Todos os Vínculos</span><span class="badge" id="nav-cnt-dec">0</span></div>
  <div class="nav-item" onclick="switchSection('fornecedores', this)"><span>🏭 Fornecedores (Top / UF)</span><span class="badge" id="nav-cnt-forn">0</span></div>
  <div class="nav-item" onclick="switchSection('fontes', this)"><span>🗂️ Auditoria de Fontes</span><span class="badge" id="nav-cnt-fontes">0</span></div>
  <div class="sidebar-footer">
    Base: <code>wins_engenharia.duckdb</code><br>
    100% CNPJ · Fontes Comprovadas<br>
    DNS MX &amp; WhatsApp Oficial
  </div>
</aside>

<header class="topbar">
  <div class="topbar-left">
    <button class="hamburger" onclick="toggleSidebar(true)">☰</button>
    <div class="brand">WiNS <span>Engenharia</span> · Validação &amp; Prospecção</div>
  </div>
  <div class="topbar-right">
    <button class="btn" onclick="resetFilters()">Limpar Filtros</button>
    <button class="btn btn-primary" onclick="exportFilteredCSV()">⬇ Exportar Obras CSV</button>
  </div>
</header>

<main class="main">
  <div class="filters-card">
    <div class="filters-grid">
      <div class="field"><label>Busca (Obra, Empresa, CNPJ, Pessoa)</label><input type="text" id="f-search" placeholder="Ex: Eneva, Subestação, Ana Luiza..." oninput="debouncedFilter()"></div>
      <div class="field"><label>Fonte Oficial</label><select id="f-fonte" onchange="applyFilters()"><option value="">Todas as fontes</option></select></div>
      <div class="field"><label>Categoria</label><select id="f-cat" onchange="applyFilters()"><option value="">Todas (Civil + Industrial)</option><option value="CIVIL">CIVIL</option><option value="INDUSTRIAL">INDUSTRIAL</option></select></div>
      <div class="field"><label>UF (Brasil)</label><select id="f-uf" onchange="applyFilters()"><option value="">Todas as UFs</option></select></div>
      <div class="field"><label>Tipo de CAPEX</label><select id="f-capex-tipo" onchange="applyFilters()"><option value="">Todos</option><option value="0">FINANCEIRO_REAL (PNCP/BNDES)</option><option value="1">PROXY_POTENCIA_KW (ANEEL)</option></select></div>
      <div class="field"><label>Filtro de Qualificação</label><select id="f-decisor" onchange="applyFilters()">
        <option value="">Todas as obras</option>
        <option value="COM_OPERACIONAL">Com Comprador / Engenharia / Diretoria</option>
        <option value="COM_ACIONAVEL">Com contato acionável</option>
        <option value="COM_WHATSAPP">Com WhatsApp Oficial no site</option>
        <option value="COM_MX">Com Domínio MX ativo</option>
        <option value="MATCH_FORN">Com match em fornecedores</option>
      </select></div>
    </div>
  </div>

  <section class="section active" id="sec-overview">
    <div class="kpis">
      <div class="kpi"><div class="kpi-label">Obras Validadas Filtradas</div><div class="kpi-val" id="kpi-obras">0</div><div class="kpi-sub" id="kpi-obras-sub"></div></div>
      <div class="kpi"><div class="kpi-label">CAPEX Financeiro Real (PNCP+BNDES)</div><div class="kpi-val" id="kpi-capex-real">R$ 0</div><div class="kpi-sub" id="kpi-capex-proxy"></div></div>
      <div class="kpi"><div class="kpi-label">Acionáveis / Operacionais</div><div class="kpi-val" id="kpi-com-aci">0</div><div class="kpi-sub" id="kpi-com-op"></div></div>
      <div class="kpi"><div class="kpi-label">Decisores Únicos / Base Total</div><div class="kpi-val" id="kpi-unicos">0</div><div class="kpi-sub" id="kpi-hist-sub"></div></div>
    </div>
    <div class="charts-grid">
      <div class="card"><div class="card-title"><span>Cobertura dos Pilares</span><span class="card-sub">% sobre obras filtradas</span></div><div class="chart-box"><canvas id="c-pilares"></canvas></div><div id="chart-pilares"></div></div>
      <div class="card"><div class="card-title"><span>Distribuição por Fonte</span><span class="card-sub">Participação &amp; CAPEX</span></div><div class="chart-box"><canvas id="c-fontes"></canvas></div><div id="chart-fontes"></div></div>
      <div class="card"><div class="card-title"><span>Decisores Únicos (Anti-Spam)</span><span class="card-sub">Por poder de contratação</span></div><div class="chart-box"><canvas id="c-perfis"></canvas></div><div id="chart-perfis"></div></div>
      <div class="card"><div class="card-title"><span>Top 10 UFs — Obras × CAPEX</span><span class="card-sub">Barras: Obras | Linha: CAPEX (bi)</span></div><div class="chart-box"><canvas id="c-ufs"></canvas></div><div id="chart-ufs"></div></div>
    </div>
  </section>

  <section class="section" id="sec-obras">
    <div class="card">
      <div class="card-title">Obras Ativas com Fonte Comprovada (<span id="lbl-obras-count">0</span>)</div>
      <div class="table-wrap"><table><thead><tr>
        <th onclick="sortBy('score')">Score</th>
        <th onclick="sortBy('fonte')">Fonte</th>
        <th onclick="sortBy('cat')">Cat.</th>
        <th onclick="sortBy('uf')">UF</th>
        <th onclick="sortBy('nome')">Obra / Objeto</th>
        <th onclick="sortBy('empresa')">Empresa / Domínio / WhatsApp</th>
        <th onclick="sortBy('capex')">CAPEX (R$)</th>
        <th onclick="sortBy('qAci')">Decisores</th>
        <th>Auditoria</th>
      </tr></thead><tbody id="tbody-obras"></tbody></table></div>
      <div class="pagination"><span id="pag-info-obras"></span><div style="display:flex;gap:8px;"><button class="btn" onclick="changePage('obras', -1)">← Anterior</button><button class="btn" onclick="changePage('obras', 1)">Próxima →</button></div></div>
    </div>
  </section>

  <section class="section" id="sec-unicos">
    <div class="card">
      <div class="card-title">Decisores Únicos Acionáveis — Anti-Spam (<span id="lbl-unicos-count">0</span> pessoas)</div>
      <div class="table-wrap"><table><thead><tr>
        <th>Score</th><th>Perfil</th><th>Decisor / Cargo</th><th>Contatos</th><th>Obras / CAPEX Sob Gestão</th><th>Obra Principal</th>
      </tr></thead><tbody id="tbody-unicos"></tbody></table></div>
      <div class="pagination"><span id="pag-info-unicos"></span><div style="display:flex;gap:8px;"><button class="btn" onclick="changePage('unicos', -1)">← Anterior</button><button class="btn" onclick="changePage('unicos', 1)">Próxima →</button></div></div>
    </div>
  </section>

  <section class="section" id="sec-decisores">
    <div class="card">
      <div class="card-title">Todos os Vínculos Obra × Decisor (<span id="lbl-dec-count">0</span>)</div>
      <div class="table-wrap"><table><thead><tr>
        <th>Perfil / Match</th><th>Fonte</th><th>Empresa / CNPJ</th><th>Decisor</th><th>Cargo</th><th>Contatos</th><th>Status</th>
      </tr></thead><tbody id="tbody-dec"></tbody></table></div>
      <div class="pagination"><span id="pag-info-dec"></span><div style="display:flex;gap:8px;"><button class="btn" onclick="changePage('dec', -1)">← Anterior</button><button class="btn" onclick="changePage('dec', 1)">Próxima →</button></div></div>
    </div>
  </section>

  <section class="section" id="sec-obra-detalhe">
    <div style="display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:10px;margin-bottom:14px;">
      <button class="btn" onclick="backFromObra()">← Voltar para Obras</button>
      <a id="det-url-btn" class="btn btn-primary" href="#" target="_blank" rel="noopener">Abrir Fonte Oficial ↗</a>
    </div>
    <div class="card" style="margin-bottom:16px;">
      <div style="display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin-bottom:8px;" id="det-badges"></div>
      <h2 id="det-nome" style="font-size:20px;line-height:1.35;margin-bottom:6px;"></h2>
      <div id="det-sub" style="font-size:13px;color:var(--muted);"></div>
    </div>
    <div class="kpis" id="det-kpis"></div>
    <div class="charts-grid" style="margin-bottom:16px;">
      <div class="card">
        <div class="card-title"><span>Empresa Titular &amp; Canais Oficiais</span></div>
        <div id="det-empresa-info" style="font-size:13.5px;display:grid;gap:8px;"></div>
      </div>
      <div class="card">
        <div class="card-title"><span>Checklist de Qualidade &amp; Cobertura</span></div>
        <div id="det-checklist" style="display:flex;flex-wrap:wrap;gap:8px;"></div>
      </div>
    </div>
    <div class="card">
      <div class="card-title"><span>Decisores Vinculados à Obra (<span id="det-dec-cnt">0</span>)</span></div>
      <div class="table-wrap">
        <table>
          <thead><tr><th>Perfil / Match</th><th>Nome</th><th>Cargo</th><th>E-mail</th><th>Telefone</th><th>LinkedIn</th><th>Status</th></tr></thead>
          <tbody id="det-tbody-dec"></tbody>
        </table>
      </div>
    </div>
  </section>

  <section class="section" id="sec-fornecedores">
    <div class="kpis" id="forn-kpis"></div>
    <div class="card" style="margin-bottom:16px;">
      <div class="card-title"><span>Fornecedores Principais — Engenharia, Construção, Energia &amp; Locação (<span id="lbl-forn-count">0</span>)</span><span class="card-sub">Top 1.500 estruturados (Média/Grande + Matches) de 4,09M totais</span></div>
      <div class="table-wrap"><table><thead><tr>
        <th>CNPJ</th><th>Empresa</th><th>Setor / CNAE</th><th>Porte</th><th>UF / Município</th><th>Capital Social</th><th>Contatos</th><th>Ação</th>
      </tr></thead><tbody id="tbody-forn"></tbody></table></div>
      <div class="pagination"><span id="pag-info-forn"></span><div style="display:flex;gap:8px;"><button class="btn" onclick="changePage('forn', -1)">← Anterior</button><button class="btn" onclick="changePage('forn', 1)">Próxima →</button></div></div>
    </div>
  </section>

  <section class="section" id="sec-forn-detalhe">
    <div style="margin-bottom:14px;"><button class="btn" onclick="switchSection('fornecedores', null)">← Voltar para Fornecedores</button></div>
    <div class="card" style="margin-bottom:16px;">
      <div style="display:flex;flex-wrap:wrap;gap:8px;margin-bottom:8px;" id="fdet-badges"></div>
      <h2 id="fdet-nome" style="font-size:20px;margin-bottom:4px;"></h2>
      <div id="fdet-sub" style="font-size:13px;color:var(--muted);"></div>
    </div>
    <div class="kpis" id="fdet-kpis"></div>
    <div class="charts-grid">
      <div class="card"><div class="card-title"><span>Localização &amp; Atividade</span></div><div id="fdet-info" style="font-size:13.5px;display:grid;gap:8px;"></div></div>
      <div class="card"><div class="card-title"><span>Canais de Contato Direto</span></div><div id="fdet-contatos" style="font-size:13.5px;display:grid;gap:8px;"></div></div>
    </div>
  </section>

  <section class="section" id="sec-fontes">
    <div class="card">
      <div class="card-title">Auditoria do Inventário Consolidado de Fontes (<span id="lbl-fontes-count">0</span>)</div>
      <div class="table-wrap"><table><thead><tr>
        <th>Fonte</th><th>Tipo</th><th>Obras</th><th>Com URL</th><th>% URL</th><th>CAPEX (R$ Bi)</th><th>Outlier?</th>
      </tr></thead><tbody id="tbody-fontes"></tbody></table></div>
    </div>
  </section>
</main>

<div class="modal-bg" id="modal-bg" onclick="if(event.target===this)closeModal()">
  <div class="modal">
    <div class="modal-head"><div><h3 id="modal-title" style="font-size:16px;margin-bottom:4px;"></h3><div id="modal-sub" style="font-size:12px;color:var(--muted);"></div></div><button class="btn" onclick="closeModal()">✕ Fechar</button></div>
    <div class="table-wrap"><table><thead><tr><th>Nome</th><th>Perfil / Cargo</th><th>E-mail</th><th>Telefone</th><th>LinkedIn</th><th>Match</th></tr></thead><tbody id="modal-tbody"></tbody></table></div>
  </div>
</div>

<script>
const RAW = __DATA_JSON__;

// Unpack compact columnar arrays into lightweight objects once at load
function unpack(cols, rows) {
  return rows.map(r => { const o = {}; for (let i = 0; i < cols.length; i++) o[cols[i]] = r[i]; return o; });
}
const OBRAS = unpack(RAW.obrasCols, RAW.obras);
const DECISORES = unpack(RAW.decCols, RAW.dec);
const UNICOS = unpack(RAW.uniCols, RAW.uni);
const FORNECEDORES = unpack(RAW.fornCols, RAW.forn);

let filteredObras = [], filteredDec = [], filteredUnicos = [], filteredForn = [];
let pageObras = 1, pageDec = 1, pageUnicos = 1, pageForn = 1;
const PAGE_SIZE = 25;
let sortCol = 'score', sortAsc = false, timer = null;

function debouncedFilter() { clearTimeout(timer); timer = setTimeout(applyFilters, 160); }
function toggleSidebar(open) { document.getElementById('sidebar').classList.toggle('open', open); document.getElementById('overlay').classList.toggle('open', open); }
function switchSection(sec, el) {
  document.querySelectorAll('.section').forEach(s => s.classList.remove('active'));
  document.getElementById('sec-' + sec).classList.add('active');
  document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
  if (el) el.classList.add('active');
  toggleSidebar(false);
}
function fmtBRL(v) {
  if (v >= 1e9) return 'R$ ' + (v / 1e9).toFixed(2).replace('.', ',') + ' bi';
  if (v >= 1e6) return 'R$ ' + (v / 1e6).toFixed(2).replace('.', ',') + ' mi';
  return 'R$ ' + Number(v || 0).toLocaleString('pt-BR', { maximumFractionDigits: 0 });
}
function esc(s) { return String(s || '').replace(/[&<>"']/g, m => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m])); }

function init() {
  const fSel = document.getElementById('f-fonte');
  [...new Set(OBRAS.map(o => o.fonte))].sort().forEach(f => { const o = document.createElement('option'); o.value = f; o.textContent = f; fSel.appendChild(o); });
  const uSel = document.getElementById('f-uf');
  [...new Set(OBRAS.map(o => o.uf))].filter(Boolean).sort().forEach(u => { const o = document.createElement('option'); o.value = u; o.textContent = u; uSel.appendChild(o); });
  document.getElementById('kpi-hist-sub').textContent = `Histórico: ${RAW.summary.obras_antigas.toLocaleString('pt-BR')} obras · ${RAW.summary.fornecedores_total.toLocaleString('pt-BR')} fornecedores`;
  renderFontes();
  applyFilters();
}

function resetFilters() {
  ['f-search','f-fonte','f-cat','f-uf','f-capex-tipo','f-decisor'].forEach(id => document.getElementById(id).value = '');
  applyFilters();
}

function applyFilters() {
  const q = document.getElementById('f-search').value.trim().toLowerCase();
  const fonte = document.getElementById('f-fonte').value;
  const cat = document.getElementById('f-cat').value;
  const uf = document.getElementById('f-uf').value;
  const capTipo = document.getElementById('f-capex-tipo').value;
  const mode = document.getElementById('f-decisor').value;

  filteredObras = OBRAS.filter(o => {
    if (fonte && o.fonte !== fonte) return false;
    if (cat && o.cat !== cat) return false;
    if (uf && o.uf !== uf) return false;
    if (capTipo !== '' && String(o.capTipo) !== capTipo) return false;
    if (mode === 'COM_OPERACIONAL' && o.qOp <= 0) return false;
    if (mode === 'COM_ACIONAVEL' && o.qAci <= 0) return false;
    if (mode === 'COM_WHATSAPP' && !o.wa) return false;
    if (mode === 'COM_MX' && !o.mx) return false;
    if (mode === 'MATCH_FORN' && !o.matchForn) return false;
    if (q && !(o.nome + ' ' + o.empresa + ' ' + o.cnpj + ' ' + o.id + ' ' + o.mun + ' ' + o.dom).toLowerCase().includes(q)) return false;
    return true;
  });

  const validIds = new Set(filteredObras.map(o => o.id));
  filteredDec = DECISORES.filter(d => {
    if (!validIds.has(d.id)) return false;
    if (mode === 'COM_ACIONAVEL' && !d.aci) return false;
    return true;
  });

  filteredUnicos = UNICOS.filter(u => {
    if (mode === 'COM_OPERACIONAL' && !['1_COMPRADOR_SUPRIMENTOS','2_GESTOR_TECNICO_OBRA','3_DIRETORIA_EXECUTIVA'].includes(u.perfil)) return false;
    if (mode === 'COM_WHATSAPP' && !u.wa) return false;
    if (uf && !(u.ufs || '').includes(uf)) return false;
    if (q && !(String(u.nome || '') + ' ' + String(u.cargo || '') + ' ' + String(u.dom || '') + ' ' + String(u.obraPrinc || '')).toLowerCase().includes(q)) return false;
    return true;
  });

  filteredForn = FORNECEDORES.filter(f => {
    if (uf && f.uf !== uf) return false;
    if (q && !(f.razao + ' ' + f.fantasia + ' ' + f.cnpj + ' ' + f.cnae + ' ' + f.setor + ' ' + f.mun).toLowerCase().includes(q)) return false;
    return true;
  });

  sortObras();
  pageObras = 1; pageDec = 1; pageUnicos = 1; pageForn = 1;
  renderAll();
}

function sortBy(col) { if (sortCol === col) sortAsc = !sortAsc; else { sortCol = col; sortAsc = false; } sortObras(); renderObrasTable(); }
function sortObras() {
  filteredObras.sort((a, b) => {
    const va = a[sortCol], vb = b[sortCol];
    if (typeof va === 'number' && typeof vb === 'number') return sortAsc ? va - vb : vb - va;
    return sortAsc ? String(va).localeCompare(String(vb)) : String(vb).localeCompare(String(va));
  });
}

function renderAll() {
  document.getElementById('nav-cnt-obras').textContent = filteredObras.length.toLocaleString('pt-BR');
  document.getElementById('nav-cnt-dec').textContent = filteredDec.length.toLocaleString('pt-BR');
  document.getElementById('nav-cnt-unicos').textContent = filteredUnicos.length.toLocaleString('pt-BR');
  document.getElementById('nav-cnt-forn').textContent = filteredForn.length.toLocaleString('pt-BR');
  document.getElementById('lbl-obras-count').textContent = filteredObras.length.toLocaleString('pt-BR');
  document.getElementById('lbl-dec-count').textContent = filteredDec.length.toLocaleString('pt-BR');
  document.getElementById('lbl-unicos-count').textContent = filteredUnicos.length.toLocaleString('pt-BR');
  document.getElementById('lbl-forn-count').textContent = filteredForn.length.toLocaleString('pt-BR');

  const n = filteredObras.length;
  document.getElementById('kpi-obras').textContent = n.toLocaleString('pt-BR');
  document.getElementById('kpi-obras-sub').textContent = `${filteredObras.filter(o => o.wa).length} com WhatsApp oficial`;
  const capReal = filteredObras.filter(o => o.capTipo === 0).reduce((s, o) => s + o.capex, 0);
  const capProxy = filteredObras.filter(o => o.capTipo === 1).reduce((s, o) => s + o.capex, 0);
  document.getElementById('kpi-capex-real').textContent = fmtBRL(capReal);
  document.getElementById('kpi-capex-proxy').textContent = 'Proxy ANEEL: ' + fmtBRL(capProxy);
  const comAci = filteredObras.filter(o => o.qAci > 0).length;
  const comOp = filteredObras.filter(o => o.qOp > 0).length;
  document.getElementById('kpi-com-aci').textContent = comAci.toLocaleString('pt-BR');
  document.getElementById('kpi-com-op').textContent = `${comOp.toLocaleString('pt-BR')} com Compras/Engenharia/Dir.`;
  document.getElementById('kpi-unicos').textContent = filteredUnicos.length.toLocaleString('pt-BR');

  renderCharts();
  renderObrasTable();
  renderUnicosTable();
  renderDecTable();
  renderFornTable();
}

const CHARTS = {};
function destroyChart(id) { if (CHARTS[id]) { CHARTS[id].destroy(); delete CHARTS[id]; } }

function renderCharts() {
  if (typeof Chart === 'undefined') {
    document.querySelectorAll('.chart-box').forEach(b => b.style.display = 'none');
    renderPilaresFallback();
    renderBarsFrom(filteredObras, 'chart-fontes', 'fonte', 10);
    renderBarsFrom(filteredUnicos, 'chart-perfis', 'perfil', 6);
    renderBarsFrom(filteredObras, 'chart-ufs', 'uf', 10);
    return;
  }
  Chart.defaults.color = '#94a3b8';
  Chart.defaults.font.family = '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif';
  const gridCol = 'rgba(148, 163, 184, 0.1)';

  // 1. Cobertura dos Pilares (%)
  const n = Math.max(1, filteredObras.length);
  const pLabels = ['CNPJ', 'Acionável', 'Domínio', 'MX Ativo', 'Operacional', 'WhatsApp'];
  const pVals = [
    filteredObras.filter(o => o.cnpj).length,
    filteredObras.filter(o => o.qAci > 0).length,
    filteredObras.filter(o => o.dom).length,
    filteredObras.filter(o => o.mx).length,
    filteredObras.filter(o => o.qOp > 0).length,
    filteredObras.filter(o => o.wa).length,
  ];
  const pPcts = pVals.map(v => Number((v / n * 100).toFixed(1)));
  destroyChart('c-pilares');
  const ctxP = document.getElementById('c-pilares').getContext('2d');
  const gradP = ctxP.createLinearGradient(0, 0, 400, 0);
  gradP.addColorStop(0, '#38bdf8'); gradP.addColorStop(1, '#22c55e');
  CHARTS['c-pilares'] = new Chart(ctxP, {
    type: 'bar',
    data: { labels: pLabels, datasets: [{ label: '% Cobertura', data: pPcts, backgroundColor: gradP, borderRadius: 8, barThickness: 18 }] },
    options: {
      indexAxis: 'y', responsive: true, maintainAspectRatio: false,
      plugins: { legend: { display: false }, tooltip: { callbacks: { label: c => ` ${pVals[c.dataIndex].toLocaleString('pt-BR')} obras (${c.raw}%)` } } },
      scales: { x: { max: 100, grid: { color: gridCol }, ticks: { callback: v => v + '%' } }, y: { grid: { display: false } } }
    }
  });

  // 2. Doughnut Fontes
  const fCounts = {};
  filteredObras.forEach(o => { fCounts[o.fonte] = (fCounts[o.fonte] || 0) + 1; });
  const fEnt = Object.entries(fCounts).sort((a, b) => b[1] - a[1]);
  const palette = ['#38bdf8','#818cf8','#22c55e','#f59e0b','#f43f5e','#14b8a6','#a855f7'];
  destroyChart('c-fontes');
  CHARTS['c-fontes'] = new Chart(document.getElementById('c-fontes'), {
    type: 'doughnut',
    data: { labels: fEnt.map(e => e[0]), datasets: [{ data: fEnt.map(e => e[1]), backgroundColor: palette, borderColor: '#1e293b', borderWidth: 3, hoverOffset: 8 }] },
    options: {
      responsive: true, maintainAspectRatio: false, cutout: '62%',
      plugins: { legend: { position: window.innerWidth < 640 ? 'bottom' : 'right', labels: { boxWidth: 12, padding: 10 } } }
    }
  });

  // 3. Perfis Anti-Spam
  const prCounts = {};
  filteredUnicos.forEach(u => { prCounts[u.perfil] = (prCounts[u.perfil] || 0) + 1; });
  const prEnt = Object.entries(prCounts).sort((a, b) => a[0].localeCompare(b[0]));
  const prColors = { '1_COMPRADOR_SUPRIMENTOS':'#22c55e', '2_GESTOR_TECNICO_OBRA':'#38bdf8', '3_DIRETORIA_EXECUTIVA':'#818cf8', '4_SOCIO_QSA':'#f59e0b', '5_OUTRO_NAO_CLASSIFICADO':'#64748b' };
  destroyChart('c-perfis');
  CHARTS['c-perfis'] = new Chart(document.getElementById('c-perfis'), {
    type: 'bar',
    data: { labels: prEnt.map(e => e[0].replace(/^\d_/, '')), datasets: [{ data: prEnt.map(e => e[1]), backgroundColor: prEnt.map(e => prColors[e[0]] || '#38bdf8'), borderRadius: 8, barThickness: 22 }] },
    options: {
      indexAxis: 'y', responsive: true, maintainAspectRatio: false,
      plugins: { legend: { display: false } },
      scales: { x: { grid: { color: gridCol } }, y: { grid: { display: false } } }
    }
  });

  // 4. Combo Top 10 UFs (Obras + CAPEX bi)
  const ufMap = {};
  filteredObras.forEach(o => {
    if (!ufMap[o.uf]) ufMap[o.uf] = { qtd: 0, cap: 0 };
    ufMap[o.uf].qtd += 1;
    ufMap[o.uf].cap += o.capex / 1e9;
  });
  const ufEnt = Object.entries(ufMap).sort((a, b) => b[1].qtd - a[1].qtd).slice(0, 10);
  destroyChart('c-ufs');
  CHARTS['c-ufs'] = new Chart(document.getElementById('c-ufs'), {
    data: {
      labels: ufEnt.map(e => e[0]),
      datasets: [
        { type: 'bar', label: 'Obras', data: ufEnt.map(e => e[1].qtd), backgroundColor: 'rgba(56, 189, 248, 0.75)', borderRadius: 6, yAxisID: 'y' },
        { type: 'line', label: 'CAPEX (R$ bi)', data: ufEnt.map(e => Number(e[1].cap.toFixed(2))), borderColor: '#f59e0b', backgroundColor: '#f59e0b', tension: 0.35, pointRadius: 4, yAxisID: 'y1' }
      ]
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: { legend: { position: 'top', labels: { boxWidth: 12 } } },
      scales: {
        x: { grid: { display: false } },
        y: { position: 'left', grid: { color: gridCol } },
        y1: { position: 'right', grid: { display: false }, ticks: { callback: v => 'R$ ' + v + 'B' } }
      }
    }
  });
}

function renderPilaresFallback() {
  const n = Math.max(1, filteredObras.length);
  const items = [
    ['CNPJ Mapeado', filteredObras.filter(o => o.cnpj).length],
    ['Contato Acionável', filteredObras.filter(o => o.qAci > 0).length],
    ['Domínio Corporativo', filteredObras.filter(o => o.dom).length],
    ['Domínio MX Ativo', filteredObras.filter(o => o.mx).length],
    ['Decisor Operacional', filteredObras.filter(o => o.qOp > 0).length],
    ['WhatsApp Oficial Site', filteredObras.filter(o => o.wa).length],
  ];
  document.getElementById('chart-pilares').innerHTML = items.map(([k, v]) => `
    <div class="bar-row">
      <div class="bar-label">${k}</div>
      <div class="bar-track"><div class="bar-fill" style="width:${(v/n*100).toFixed(1)}%"></div></div>
      <div class="bar-val">${v.toLocaleString('pt-BR')} (${(v/n*100).toFixed(0)}%)</div>
    </div>
  `).join('');
}

function renderBarsFrom(arr, elId, key, limit) {
  const counts = {};
  arr.forEach(o => { const k = o[key] || '(vazio)'; counts[k] = (counts[k] || 0) + 1; });
  const entries = Object.entries(counts).sort((a, b) => b[1] - a[1]).slice(0, limit);
  const max = entries.length ? entries[0][1] : 1;
  document.getElementById(elId).innerHTML = entries.map(([k, v]) => `
    <div class="bar-row"><div class="bar-label" title="${esc(k)}">${esc(k)}</div><div class="bar-track"><div class="bar-fill" style="width:${(v/max*100).toFixed(1)}%"></div></div><div class="bar-val">${v.toLocaleString('pt-BR')}</div></div>
  `).join('') || '<div style="color:var(--muted);font-size:12px;">Sem dados.</div>';
}

function renderObrasTable() {
  const start = (pageObras - 1) * PAGE_SIZE;
  const slice = filteredObras.slice(start, start + PAGE_SIZE);
  document.getElementById('tbody-obras').innerHTML = slice.map(o => `
    <tr>
      <td><span class="pill ${o.score >= 75 ? 'pill-ok' : (o.score >= 50 ? 'pill-civil' : 'pill-muted')}">${o.score}</span></td>
      <td><span class="pill pill-muted">${esc(o.fonte)}</span></td>
      <td><span class="pill ${o.cat === 'INDUSTRIAL' ? 'pill-ind' : 'pill-civil'}">${esc(o.cat)}</span></td>
      <td><strong>${esc(o.uf)}</strong><br><span style="font-size:11px;color:var(--muted);">${esc(o.mun)}</span></td>
      <td style="max-width:300px;"><a href="javascript:void(0)" onclick="openObraPage('${esc(o.id)}')" style="font-weight:600;color:var(--text);">${esc(o.nome)}</a><div style="font-size:11px;color:var(--muted);">ID: ${esc(o.id)}</div></td>
      <td>
        <div>${esc(o.empresa || '—')}</div>
        <div style="font-size:11px;color:var(--muted);">${esc(o.cnpj)} ${o.dom ? '· ' + esc(o.dom) + (o.mx ? ' (MX✓)' : '') : ''}</div>
        ${o.wa ? `<div style="font-size:11px;"><a href="https://wa.me/55${esc(o.wa)}" target="_blank" rel="noopener">WhatsApp Oficial ↗</a></div>` : ''}
        <div style="font-size:11px;color:var(--muted);">Fornecedores ${esc(o.uf)}: ${Number(o.fornUf).toLocaleString('pt-BR')}</div>
      </td>
      <td style="white-space:nowrap;"><strong>${fmtBRL(o.capex)}</strong><br><span style="font-size:11px;color:var(--muted);">${o.capTipo === 1 ? 'Proxy kW' : 'Valor real'}</span></td>
      <td>${o.qAci > 0 ? `<span class="pill pill-ok">${o.qAci} acionável</span>` : (o.qDec > 0 ? `<span class="pill pill-warn">${o.qDec} sem canal</span>` : '<span style="color:var(--muted);">0</span>')}</td>
      <td style="white-space:nowrap;"><button class="btn" style="padding:3px 8px;font-size:11px;" onclick="openObraPage('${esc(o.id)}')">Ver página</button><br><a href="${esc(o.url)}" target="_blank" rel="noopener" style="font-size:11px;">Fonte ↗</a></td>
    </tr>
  `).join('');
  const totalPages = Math.max(1, Math.ceil(filteredObras.length / PAGE_SIZE));
  document.getElementById('pag-info-obras').textContent = `Página ${pageObras} de ${totalPages} (${filteredObras.length.toLocaleString('pt-BR')} obras)`;
}

function renderUnicosTable() {
  const start = (pageUnicos - 1) * PAGE_SIZE;
  const slice = filteredUnicos.slice(start, start + PAGE_SIZE);
  document.getElementById('tbody-unicos').innerHTML = slice.map(u => `
    <tr>
      <td><span class="pill ${u.score >= 75 ? 'pill-ok' : (u.score >= 50 ? 'pill-civil' : 'pill-muted')}">${u.score}</span></td>
      <td><span class="pill pill-muted">${esc(u.perfil)}</span></td>
      <td style="max-width:240px;"><strong>${esc(u.nome)}</strong><br><span style="font-size:11.5px;color:var(--muted);">${esc(u.cargo || '—')}</span></td>
      <td style="font-size:12px;">
        ${u.email ? '✉ ' + esc(u.email) + '<br>' : ''}
        ${u.tel ? '☎ ' + esc(u.tel) + '<br>' : ''}
        ${u.lk ? `<a href="${esc(u.lk)}" target="_blank" rel="noopener">LinkedIn ↗</a> ` : ''}
        ${u.wa ? `<a href="https://wa.me/55${esc(u.wa)}" target="_blank" rel="noopener">WhatsApp ↗</a>` : ''}
      </td>
      <td style="white-space:nowrap;"><strong>${u.qObras} obra(s)</strong><br><span style="color:var(--accent);">${fmtBRL(u.capex)}</span><br><span style="font-size:11px;color:var(--muted);">UFs: ${esc(u.ufs)}</span></td>
      <td style="max-width:260px;font-size:12px;">${esc(u.obraPrinc)}<br><a href="${esc(u.urlPrinc)}" target="_blank" rel="noopener">Abrir fonte ↗</a></td>
    </tr>
  `).join('');
  const totalPages = Math.max(1, Math.ceil(filteredUnicos.length / PAGE_SIZE));
  document.getElementById('pag-info-unicos').textContent = `Página ${pageUnicos} de ${totalPages} (${filteredUnicos.length.toLocaleString('pt-BR')} pessoas únicas)`;
}

function renderDecTable() {
  const start = (pageDec - 1) * PAGE_SIZE;
  const slice = filteredDec.slice(start, start + PAGE_SIZE);
  document.getElementById('tbody-dec').innerHTML = slice.map(d => `
    <tr>
      <td><span class="pill pill-muted">${esc(d.perfil)}</span><br><span style="font-size:11px;color:var(--muted);">${esc(d.match)}</span></td>
      <td>${esc(d.fonte)}<br><span style="font-size:11px;color:var(--muted);">${esc(d.uf)}</span></td>
      <td>${esc(d.empresa)}<br><span style="font-size:11px;color:var(--muted);">${esc(d.cnpj)}</span></td>
      <td><strong>${esc(d.nome)}</strong></td>
      <td style="max-width:220px;">${esc(d.cargo || '—')}</td>
      <td style="font-size:12px;">${d.email ? '✉ '+esc(d.email)+'<br>' : ''}${d.tel ? '☎ '+esc(d.tel)+'<br>' : ''}${d.lk ? `<a href="${esc(d.lk)}" target="_blank" rel="noopener">LinkedIn ↗</a>` : ''}</td>
      <td>${d.aci ? '<span class="pill pill-ok">Acionável</span>' : '<span class="pill pill-warn">Sem canal</span>'}</td>
    </tr>
  `).join('');
  const totalPages = Math.max(1, Math.ceil(filteredDec.length / PAGE_SIZE));
  document.getElementById('pag-info-dec').textContent = `Página ${pageDec} de ${totalPages} (${filteredDec.length.toLocaleString('pt-BR')} vínculos)`;
}

function renderFontes() {
  document.getElementById('nav-cnt-fontes').textContent = RAW.fontes.length;
  document.getElementById('lbl-fontes-count').textContent = RAW.fontes.length;
  document.getElementById('tbody-fontes').innerHTML = RAW.fontes.map(f => `
    <tr><td><strong>${esc(f[0])}</strong></td><td><span class="pill pill-muted">${esc(f[1])}</span></td><td>${Number(f[2]).toLocaleString('pt-BR')}</td><td>${Number(f[3]).toLocaleString('pt-BR')}</td><td>${f[4]}%</td><td>${Number(f[5]).toLocaleString('pt-BR',{minimumFractionDigits:1})}</td><td>${f[6] ? '<span class="pill pill-warn">Outlier</span>' : '<span class="pill pill-ok">OK</span>'}</td></tr>
  `).join('');
}

function renderFornTable() {
  const uf = document.getElementById('f-uf').value;
  const resRows = RAW.fornResumo.filter(r => !uf || r[0] === uf);
  const totBase = resRows.reduce((s, r) => s + r[2], 0);
  const totAci = resRows.reduce((s, r) => s + r[3], 0);
  const totEst = resRows.reduce((s, r) => s + r[4], 0);
  document.getElementById('forn-kpis').innerHTML = `
    <div class="kpi"><div class="kpi-label">Fornecedores Setores Engenharia (DuckDB)</div><div class="kpi-val">${totBase.toLocaleString('pt-BR')}</div><div class="kpi-sub">${uf ? 'Filtrado UF: ' + esc(uf) : 'Base completa Brasil: 4.090.553'}</div></div>
    <div class="kpi"><div class="kpi-label">Com Contato Acionável</div><div class="kpi-val">${totAci.toLocaleString('pt-BR')}</div><div class="kpi-sub">Telefone ou e-mail válido</div></div>
    <div class="kpi"><div class="kpi-label">Estruturados (Peq/Méd/Grande)</div><div class="kpi-val">${totEst.toLocaleString('pt-BR')}</div><div class="kpi-sub">Excluindo MEIs/Micro na métrica</div></div>
    <div class="kpi"><div class="kpi-label">Top Amostra Interativa</div><div class="kpi-val">${filteredForn.length.toLocaleString('pt-BR')}</div><div class="kpi-sub">Média/Grande porte + Matches</div></div>
  `;
  const start = (pageForn - 1) * PAGE_SIZE;
  const slice = filteredForn.slice(start, start + PAGE_SIZE);
  document.getElementById('tbody-forn').innerHTML = slice.map(f => `
    <tr>
      <td style="white-space:nowrap;font-size:12px;">${esc(fmtCNPJ(f.cnpj))}</td>
      <td style="max-width:260px;"><a href="javascript:void(0)" onclick="openFornPage('${esc(f.cnpj)}')" style="font-weight:600;color:var(--text);">${esc(f.razao)}</a>${f.fantasia ? `<div style="font-size:11px;color:var(--muted);">${esc(f.fantasia)}</div>` : ''}</td>
      <td><span class="pill pill-muted">${esc(f.setor)}</span><div style="font-size:11px;color:var(--muted);margin-top:2px;">CNAE ${esc(f.cnae)}</div></td>
      <td><span class="pill ${f.porte==='GRANDE'?'pill-ok':(f.porte==='MEDIA'?'pill-civil':'pill-muted')}">${esc(f.porte || '—')}</span></td>
      <td><strong>${esc(f.uf)}</strong><br><span style="font-size:11px;color:var(--muted);">${esc(f.mun)}</span></td>
      <td style="white-space:nowrap;">${f.capSocial > 0 ? fmtBRL(f.capSocial) : '—'}</td>
      <td style="font-size:12px;">${f.email ? '✉ '+esc(f.email)+'<br>' : ''}${f.tel1 ? '☎ '+esc(f.tel1) : ''}</td>
      <td><button class="btn" style="padding:3px 8px;font-size:11px;" onclick="openFornPage('${esc(f.cnpj)}')">Ver página</button></td>
    </tr>
  `).join('');
  const totalPages = Math.max(1, Math.ceil(filteredForn.length / PAGE_SIZE));
  document.getElementById('pag-info-forn').textContent = `Página ${pageForn} de ${totalPages} (${filteredForn.length.toLocaleString('pt-BR')} fornecedores)`;
}

function openFornPage(cnpj) {
  const f = FORNECEDORES.find(x => x.cnpj === cnpj);
  if (!f) return;
  document.getElementById('fdet-badges').innerHTML = `
    <span class="pill pill-ok">${esc(f.porte || 'N/I')}</span>
    <span class="pill pill-civil">${esc(f.setor)}</span>
    <span class="pill pill-muted">${esc(f.tipoEstab || 'MATRIZ')}</span>
    ${f.matches > 0 ? `<span class="pill pill-ok">${f.matches} match(es) com obras</span>` : ''}
  `;
  document.getElementById('fdet-nome').textContent = f.razao;
  document.getElementById('fdet-sub').textContent = `Nome Fantasia: ${f.fantasia || '—'} · CNPJ: ${fmtCNPJ(f.cnpj)}`;
  document.getElementById('fdet-kpis').innerHTML = `
    <div class="kpi"><div class="kpi-label">Capital Social</div><div class="kpi-val">${f.capSocial > 0 ? fmtBRL(f.capSocial) : '—'}</div></div>
    <div class="kpi"><div class="kpi-label">CNAE Principal</div><div class="kpi-val">${esc(f.cnae)}</div><div class="kpi-sub">${esc(f.cnaeDesc || f.setor)}</div></div>
    <div class="kpi"><div class="kpi-label">Porte</div><div class="kpi-val">${esc(f.porte || '—')}</div></div>
    <div class="kpi"><div class="kpi-label">Matches Históricos</div><div class="kpi-val">${f.matches}</div></div>
  `;
  document.getElementById('fdet-info').innerHTML = `
    <div><strong>UF / Município:</strong> ${esc(f.mun ? f.mun + '/' : '')}${esc(f.uf)}</div>
    <div><strong>Endereço:</strong> ${esc(f.end || '—')}</div>
    <div><strong>CEP:</strong> ${esc(f.cep || '—')}</div>
    <div><strong>Setor Consolidado:</strong> ${esc(f.setor)}</div>
  `;
  document.getElementById('fdet-contatos').innerHTML = `
    <div><strong>E-mail Corporativo:</strong> ${f.email ? `<a href="mailto:${esc(f.email)}">${esc(f.email)}</a>` : '—'}</div>
    <div><strong>Telefone 1:</strong> ${esc(f.tel1 || '—')}</div>
    <div><strong>Telefone 2:</strong> ${esc(f.tel2 || '—')}</div>
  `;
  document.querySelectorAll('.section').forEach(s => s.classList.remove('active'));
  document.getElementById('sec-forn-detalhe').classList.add('active');
  window.scrollTo({ top: 0, behavior: 'smooth' });
}

function changePage(type, delta) {
  if (type === 'obras') { const m = Math.max(1, Math.ceil(filteredObras.length/PAGE_SIZE)); pageObras = Math.min(m, Math.max(1, pageObras+delta)); renderObrasTable(); }
  else if (type === 'unicos') { const m = Math.max(1, Math.ceil(filteredUnicos.length/PAGE_SIZE)); pageUnicos = Math.min(m, Math.max(1, pageUnicos+delta)); renderUnicosTable(); }
  else if (type === 'forn') { const m = Math.max(1, Math.ceil(filteredForn.length/PAGE_SIZE)); pageForn = Math.min(m, Math.max(1, pageForn+delta)); renderFornTable(); }
  else { const m = Math.max(1, Math.ceil(filteredDec.length/PAGE_SIZE)); pageDec = Math.min(m, Math.max(1, pageDec+delta)); renderDecTable(); }
}

let lastSection = 'obras';
function fmtCNPJ(c) {
  if (!c || c.length !== 14) return c || '—';
  return c.replace(/^(\d{2})(\d{3})(\d{3})(\d{4})(\d{2})$/, '$1.$2.$3/$4-$5');
}
function openObraPage(idExt) {
  const active = document.querySelector('.section.active');
  if (active && active.id !== 'sec-obra-detalhe') lastSection = active.id.replace('sec-', '');
  const o = OBRAS.find(x => x.id === idExt);
  if (!o) return;
  const decs = DECISORES.filter(d => d.id === idExt);

  document.getElementById('det-url-btn').href = o.url || '#';
  document.getElementById('det-badges').innerHTML = `
    <span class="pill ${o.score >= 75 ? 'pill-ok' : (o.score >= 50 ? 'pill-civil' : 'pill-muted')}">ICP Score: ${o.score}/100</span>
    <span class="pill ${o.cat === 'INDUSTRIAL' ? 'pill-ind' : 'pill-civil'}">${esc(o.cat)}</span>
    <span class="pill pill-muted">${esc(o.fonte)}</span>
    ${o.sit ? `<span class="pill pill-muted">${esc(o.sit)}</span>` : ''}
  `;
  document.getElementById('det-nome').textContent = o.nome;
  document.getElementById('det-sub').textContent = `ID Externo: ${o.id} · Local: ${o.mun ? o.mun + '/' : ''}${o.uf}`;

  document.getElementById('det-kpis').innerHTML = `
    <div class="kpi"><div class="kpi-label">CAPEX Estimado</div><div class="kpi-val">${fmtBRL(o.capex)}</div><div class="kpi-sub">${o.capTipo === 1 ? 'Proxy R$ 4.500/kW (ANEEL)' : 'Valor Financeiro Real'}</div></div>
    <div class="kpi"><div class="kpi-label">Vigência / Datas</div><div class="kpi-val" style="font-size:17px;">${esc(o.dtIni || '—')} → ${esc(o.dtFim || '—')}</div><div class="kpi-sub">Início / Fim previsto</div></div>
    <div class="kpi"><div class="kpi-label">Decisores Mapeados</div><div class="kpi-val">${o.qDec} (${o.qAci} acionáveis)</div><div class="kpi-sub">${o.qOp} operacional(is) Compras/Eng.</div></div>
    <div class="kpi"><div class="kpi-label">Fornecedores Locais (${esc(o.uf)})</div><div class="kpi-val">${Number(o.fornUf).toLocaleString('pt-BR')}</div><div class="kpi-sub">${o.matchForn ? 'Empresa consta na base de fornecedores ✓' : 'Empresas acionáveis compatíveis na UF'}</div></div>
  `;

  document.getElementById('det-empresa-info').innerHTML = `
    <div><strong>Razão Social / Titular:</strong> ${esc(o.empresa || '—')}</div>
    <div><strong>CNPJ:</strong> ${esc(fmtCNPJ(o.cnpj))}</div>
    <div><strong>Domínio Corporativo:</strong> ${o.dom ? `<a href="https://${esc(o.dom)}" target="_blank" rel="noopener">${esc(o.dom)} ↗</a> ${o.mx ? '<span class="pill pill-ok">MX Ativo ✓</span>' : '<span class="pill pill-warn">Sem MX</span>'}` : '<span style="color:var(--muted);">Não mapeado</span>'}</div>
    <div><strong>WhatsApp Oficial (Site):</strong> ${o.wa ? `<a href="https://wa.me/55${esc(o.wa)}" target="_blank" rel="noopener">+55 ${esc(o.wa)} ↗</a>` : '<span style="color:var(--muted);">Não encontrado no site</span>'}</div>
    <div><strong>Telefone Site:</strong> ${o.telSite ? esc(o.telSite) : '<span style="color:var(--muted);">—</span>'}</div>
  `;

  const checks = [
    ['CNPJ Mapeado', !!o.cnpj],
    ['Contato Acionável', o.qAci > 0],
    ['Decisor Compras/Eng./CAPEX', o.qOp > 0],
    ['Domínio Corporativo', !!o.dom],
    ['Servidor E-mail (MX)', !!o.mx],
    ['WhatsApp Oficial Site', !!o.wa],
    ['Match Fornecedores', !!o.matchForn],
  ];
  document.getElementById('det-checklist').innerHTML = checks.map(([lbl, ok]) =>
    `<span class="pill ${ok ? 'pill-ok' : 'pill-muted'}" style="padding:6px 10px;font-size:12px;">${ok ? '✓' : '✕'} ${lbl}</span>`
  ).join('');

  document.getElementById('det-dec-cnt').textContent = decs.length;
  document.getElementById('det-tbody-dec').innerHTML = decs.length ? decs.map(d => `
    <tr>
      <td><span class="pill pill-muted">${esc(d.perfil)}</span><br><span style="font-size:11px;color:var(--muted);">${esc(d.match)}</span></td>
      <td><strong>${esc(d.nome)}</strong></td>
      <td style="max-width:240px;">${esc(d.cargo || '—')}</td>
      <td>${esc(d.email || '—')}</td>
      <td>${esc(d.tel || '—')}</td>
      <td>${d.lk ? `<a href="${esc(d.lk)}" target="_blank" rel="noopener">LinkedIn ↗</a>` : '—'}</td>
      <td>${d.aci ? '<span class="pill pill-ok">Acionável</span>' : '<span class="pill pill-warn">Sem canal</span>'}</td>
    </tr>
  `).join('') : '<tr><td colspan="7" style="color:var(--muted);">Nenhum decisor vinculado a esta obra até o momento.</td></tr>';

  document.querySelectorAll('.section').forEach(s => s.classList.remove('active'));
  document.getElementById('sec-obra-detalhe').classList.add('active');
  window.scrollTo({ top: 0, behavior: 'smooth' });
}
function backFromObra() { switchSection(lastSection || 'obras', null); }
function openModal(idExt) { openObraPage(idExt); }
function closeModal() { document.getElementById('modal-bg').classList.remove('open'); }

function exportFilteredCSV() {
  if (!filteredObras.length) return alert('Nenhuma obra no filtro atual.');
  const cols = ['id','fonte','cat','uf','mun','nome','empresa','cnpj','dom','mx','wa','capex','qAci','qOp','score','url'];
  const lines = [cols.join(',')].concat(filteredObras.map(o => cols.map(c => '"' + String(o[c] ?? '').replace(/"/g, '""') + '"').join(',')));
  const blob = new Blob(['\\uFEFF' + lines.join('\\n')], { type: 'text/csv;charset=utf-8;' });
  const a = document.createElement('a'); a.href = URL.createObjectURL(blob); a.download = 'wins_obras_filtradas.csv'; a.click();
}

init();
</script>
</body>
</html>
"""

final_html = html_template.replace("__DATA_JSON__", data_json)
with open(OUT_HTML, "w", encoding="utf-8") as f:
    f.write(final_html)

print(f"Dashboard otimizado gerado: {OUT_HTML} ({os.path.getsize(OUT_HTML)/(1024*1024):.2f} MB)")
