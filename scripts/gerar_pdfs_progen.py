import os
import duckdb
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    HRFlowable,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

BASE_DIR = r"C:\Users\kbadmin\Documents\Projetos\01_Ecossistema_WiNS\Engenharia"
MAIN_DB = os.path.join(BASE_DIR, "Banco_Dados", "wins_engenharia.duckdb")
OUT_DIR = os.path.join(BASE_DIR, "Entregas")
os.makedirs(OUT_DIR, exist_ok=True)

PDF_PROPOSTA = os.path.join(OUT_DIR, "05_Proposta_Executiva_Progen_WiNS.pdf")
PDF_OBRAS = os.path.join(OUT_DIR, "06_Mapeamento_12_Obras_Progen_WiNS.pdf")

NAVY = colors.HexColor("#0F172A")
GOLD = colors.HexColor("#C9A227")
BLUE = colors.HexColor("#1D4ED8")
SLATE = colors.HexColor("#475569")
LIGHT_BG = colors.HexColor("#F8FAFC")
BORDER = colors.HexColor("#CBD5E1")

TARGET_IDS = [
    ("CONVISAO-47472", "Industrial / Papel & Celulose (MS, R$ 25 bi, em execução) — aderência máxima à JV Valpro (Valmet) e à diretoria de Engenharia/EPCM da Progen."),
    ("CVM160-24677", "Saneamento & Infraestrutura (Sabesp, Debêntures Lei 12.431, R$ 6,29 bi, SP) — grandes pacotes de engenharia consultiva, gerenciamento de obras e fiscalização."),
    ("SIGET-6714", "Transmissão de Energia (ISA Energia Brasil, SE 230/88 kV Dom Pedro I + LTs em SP, 22 módulos) — encaixe direto com a Progen Energia S.A."),
    ("BNDES-26700181", "Energia Eólica & Transmissão (Axia Energia Sul, Coxilha Negra 302,4 MW, RS, R$ 1,40 bi) — demanda pesada de subestações, linhas de transmissão e EPCM."),
    ("BNDES-25204051", "Siderurgia & Manutenção Industrial (CSN Volta Redonda/RJ, R$ 625,8 mi) — modernização de 3 plantas de sinterização; aderência à Progen Engenharia e Manutenção."),
    ("BNDES-25204031", "Bioenergia / Etanol de Milho (Inpasa, BA, R$ 600 mi) — referência histórica da Progen em plantas de bioenergia premiadas pela MundoPM."),
    ("BNDES-26201091", "Energia Eólica & Transmissão (TGR Subholding / Serra do Tigre 126 MW, RN/PB, R$ 600 mi) — 20 decisores de Compras/Engenharia mapeados para EPCM e conexões."),
    ("BNDES-26200911", "Refino / Biorrefinaria SAF & RD (Acelen Industrial, BA, R$ 477,7 mi) — engenharia multidisciplinar, suprimentos críticos, BIM 3D e gerenciamento de implantação."),
    ("BNDES-26200141", "Distribuição de Energia (Energisa Tocantins, R$ 460 mi, TO) — cliente âncora já atendido pela Progen; expansão contínua de redes e subestações."),
    ("BNDES-25204281", "Geração Termelétrica & Transmissão (UTE GNA II, 1.672,6 MW no Porto do Açu/RJ, R$ 375 mi) — grande porte industrial em praça com base operacional da Progen no RJ."),
    ("BNDES-26200131", "Distribuição de Energia (Energisa Mato Grosso, R$ 370 mi, MT) — 10 decisores acionáveis para contratos recorrentes de redes e atendimento regulado."),
    ("BNDES-25203461", "Mineração & Metalurgia (CBA / Votorantim, Alumínio/SP e GO, R$ 231,4 mi) — vertical clássica da Progen; modernização de fornos, águas e logística."),
]


def build_styles():
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="DocTitle", fontName="Helvetica-Bold", fontSize=18.5, leading=22, textColor=NAVY, spaceAfter=3))
    styles.add(ParagraphStyle(name="DocSub", fontName="Helvetica", fontSize=9.8, leading=13.5, textColor=SLATE, spaceAfter=8))
    styles.add(ParagraphStyle(name="SecHead", fontName="Helvetica-Bold", fontSize=12, leading=15.5, textColor=BLUE, spaceBefore=9, spaceAfter=4))
    styles.add(ParagraphStyle(name="Body", fontName="Helvetica", fontSize=9.1, leading=13.2, textColor=NAVY, spaceAfter=4))
    styles.add(ParagraphStyle(name="BulletItem", fontName="Helvetica", fontSize=9.0, leading=12.8, textColor=NAVY, leftIndent=10, spaceAfter=3))
    styles.add(ParagraphStyle(name="SmallCell", fontName="Helvetica", fontSize=7.8, leading=10.2, textColor=NAVY))
    styles.add(ParagraphStyle(name="SmallBold", fontName="Helvetica-Bold", fontSize=7.8, leading=10.2, textColor=NAVY))
    styles.add(ParagraphStyle(name="Meta", fontName="Helvetica", fontSize=8.0, leading=10.5, textColor=SLATE))
    return styles


def fmt_capex(val):
    if val is None or val <= 0:
        return "N/D"
    if val >= 1e9:
        return f"R$ {val/1e9:,.2f} bi".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"R$ {val/1e6:,.2f} mi".replace(",", "X").replace(".", ",").replace("X", ".")


def clean_str(v):
    return str(v).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;") if v is not None else "—"


def generate_proposta_pdf(styles, con):
    doc = SimpleDocTemplate(PDF_PROPOSTA, pagesize=A4, leftMargin=15 * mm, rightMargin=15 * mm, topMargin=14 * mm, bottomMargin=14 * mm)
    story = []

    tot_obras, tot_aci, tot_op = con.execute(
        "SELECT COUNT(*), SUM(CASE WHEN decisores_acionaveis>0 THEN 1 ELSE 0 END), SUM(CASE WHEN decisores_operacionais>0 THEN 1 ELSE 0 END) FROM todas_obras_consolidadas"
    ).fetchone()
    tot_uni, uni_lk, uni_tel, uni_em = con.execute(
        "SELECT COUNT(*), COUNT(decisor_linkedin), COUNT(decisor_telefone), COUNT(decisor_email) FROM campanha_por_decisor_unico"
    ).fetchone()
    tot_siget = con.execute("SELECT COUNT(*) FROM todas_obras_consolidadas WHERE fonte = 'aneel_transmissao'").fetchone()[0]
    tot_siga = con.execute("SELECT COUNT(*) FROM todas_obras_consolidadas WHERE fonte = 'aneel_siga'").fetchone()[0]
    tot_cvm = con.execute("SELECT COUNT(*) FROM todas_obras_consolidadas WHERE fonte = 'debentures_infra'").fetchone()[0]
    tot_forn = con.execute("SELECT COUNT(*) FROM fornecedores").fetchone()[0]

    fases_rows = con.execute("SELECT fase_obra, COUNT(*) FROM todas_obras_consolidadas GROUP BY 1 ORDER BY 1").fetchall()
    top_ufs_obras = con.execute("""
        SELECT obra_uf, COUNT(*), SUM(CASE WHEN decisores_acionaveis>0 THEN 1 ELSE 0 END), ROUND(SUM(COALESCE(capex_estimado,0))/1e9, 2)
        FROM todas_obras_consolidadas
        GROUP BY 1 ORDER BY 2 DESC LIMIT 8
    """).fetchall()
    setores_forn = con.execute("""
        SELECT setor_consolidado, COUNT(*), SUM(CASE WHEN porte_consolidado IN ('GRANDE','MEDIA') THEN 1 ELSE 0 END)
        FROM fornecedores
        WHERE setor_consolidado IN (
            'CONSTRUCAO_ESPECIALIZADA','ENGENHARIA_ARQUITETURA','METALURGIA_ESTRUTURAS',
            'LOCACAO_MAQUINAS_EQUIPAMENTOS','INFRAESTRUTURA','ENERGIA','SANEAMENTO'
        )
        GROUP BY 1 ORDER BY 2 DESC
    """).fetchall()
    pracas_forn = con.execute("""
        SELECT uf, COUNT(*), SUM(CASE WHEN email IS NOT NULL OR telefone_1 IS NOT NULL THEN 1 ELSE 0 END)
        FROM fornecedores
        WHERE uf IN ('SP','MG','PR','RJ','RS','BA','MA')
          AND setor_consolidado IN (
            'CONSTRUCAO_ESPECIALIZADA','ENGENHARIA_ARQUITETURA','METALURGIA_ESTRUTURAS',
            'LOCACAO_MAQUINAS_EQUIPAMENTOS','INFRAESTRUTURA','ENERGIA','SANEAMENTO'
        )
        GROUP BY 1 ORDER BY 2 DESC
    """).fetchall()

    # PAGINA 1: CAPA EXECUTIVA E VISAO BIDIRECIONAL
    story.append(Paragraph("PROPOSTA EXECUTIVA DETALHADA — PROGEN S.A.", styles["DocTitle"]))
    story.append(Paragraph("Inteligência Bidirecional WiNS Engenharia: Captação de Obras de Alta Margem (Clientes) &amp; Homologação/Blindagem de Suprimentos (Fornecedores)", styles["DocSub"]))
    story.append(HRFlowable(width="100%", thickness=2.0, color=GOLD, spaceAfter=8))

    kpis = [
        ["Base Ativa de Obras (2026–2027)", f"{tot_obras:,} obras consolidadas | {tot_aci:,} acionáveis ({tot_aci/tot_obras*100:.1f}%) | {tot_op:,} com Compras/Eng.".replace(",", ".")],
        ["Decisores Únicos Validados", f"{tot_uni:,} pessoas únicas ({uni_lk:,} LinkedIn | {uni_tel:,} Tel. libphonenumber | {uni_em:,} E-mails)".replace(",", ".")],
        ["Cobertura Energia & Infraestrutura", f"{tot_siget:,} Transmissão (ANEEL SIGET) + {tot_siga:,} Geração (ANEEL SIGA) + {tot_cvm} Debêntures CVM".replace(",", ".")],
        ["Base de Fornecedores Saneada", f"{tot_forn:,} CNPJs indexados por CNAE, Porte, Capital Social, UF/Município, E-mail e Telefone".replace(",", ".")],
        ["Presença Progen no Banco WiNS", "PROGEN S.A. (raiz 57.748.204) e PROGEN MANUTENÇÃO (50.134.905) indexadas em SP, MG, BA, ES, GO, MA e DF"],
    ]
    t = Table([[Paragraph(f"<b>{k}</b>", styles["SmallBold"]), Paragraph(clean_str(v), styles["SmallCell"])] for k, v in kpis], colWidths=[52 * mm, 128 * mm])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), LIGHT_BG),
        ("BOX", (0, 0), (-1, -1), 0.7, BORDER),
        ("INNERGRID", (0, 0), (-1, -1), 0.4, BORDER),
        ("PADDING", (0, 0), (-1, -1), 5),
    ]))
    story.append(t)
    story.append(Spacer(1, 6))

    story.append(Paragraph("1. Sumário Executivo: Por que a WiNS Engenharia faz sentido para a Progen S.A.", styles["SecHead"]))
    story.append(Paragraph("A Progen S.A. é referência nacional em engenharia consultiva, gerenciamento da construção, EPC/EPCM, serviços de energia, manutenção industrial e facilities (R$ 1,54 bilhão de receita líquida em 2024, 7.000+ colaboradores, 4 escritórios regionais e 15 filiais). A análise das demonstrações auditadas (BDO 2024) e da estrutura operacional mostra que o principal desafio da companhia para 2026–2027 não é demanda, mas <b>qualidade de margem e conversão de caixa</b>.", styles["Body"]))
    story.append(Paragraph("Diferente de listas genéricas de leads, a plataforma <b>WiNS Engenharia</b> atua nos <b>dois lados do resultado da Progen</b>:", styles["Body"]))
    story.append(Paragraph("• <b>Lado 1 — Receita &amp; Margem (Clientes):</b> direciona o time comercial (Progen Energia, Engenharia/EPCM, Valpro e Planway) para projetos de maior margem técnica e com financiamento garantido (ANEEL SIGET/SIGA, BNDES, CVM Debêntures, ConVisão, CIMM, IBAMA SISLIC e BVMI), entrando nas fases iniciais (LP/LI/Financiamento) antes da concorrência aberta.", styles["BulletItem"]))
    story.append(Paragraph("• <b>Lado 2 — Custo &amp; Risco de Suprimentos (Fornecedores):</b> disponibiliza 4,09 milhões de CNPJs saneados para a área de Suprimentos e Expediting homologar subcontratados e locadores locais nas 15 filiais, atacando diretamente os gastos de <b>R$ 89,3 mi em terceiros</b>, <b>R$ 67,6 mi em locação de máquinas</b> (+61,3%) e protegendo os <b>R$ 259,4 mi em adiantamentos a fornecedores</b>.", styles["BulletItem"]))

    story.append(Paragraph("2. Diagnóstico Progen (Base Auditada 2024) × Solução WiNS Engenharia", styles["SecHead"]))
    diag_rows = [
        ["Indicador / Dor Mapeada (Progen)", "Evidência Pública (BDO 2024)", "Como a WiNS Engenharia Atua na Prática"],
        ["Compressão de margem por mix", "Margem bruta caiu 18,2% → 16,3%; crescimento veio de facilities/manutenção.", "Prioriza obras de Engenharia, EPCM e Transmissão/Subestações (maior valor agregado)."],
        ["Alongamento de recebimento (DSO)", "DSO subiu de 122 para 157 dias; fluxo operacional de −R$ 215,2 mi.", "Filtra contratantes com recurso aprovado (BNDES/CVM) e Lead Score 0–100."],
        ["Gasto com Locação &amp; Terceiros", "R$ 89,3 mi em terceiros + R$ 67,6 mi em locação (+61,3%) + R$ 32,8 mi frotas.", "83.398 locadores e 1,57M construtoras especializadas por UF/município para cotação competitiva."],
        ["Risco em Adiantamentos", "R$ 259,4 mi adiantados a fornecedores (DPO de apenas 12 dias).", "Checagem cadastral instantânea (situação ATIVA, porte real e capital social) antes de adiantar."],
        ["Capilaridade (15 filiais)", "Mobilização remota encarece obra e exige rede local homologada.", "Cruzamento automático Obra × Fornecedores elegíveis na mesma UF e município."],
    ]
    td = Table(
        [[Paragraph(f"<b>{c}</b>" if ri == 0 else c, styles["SmallBold"] if ri == 0 else styles["SmallCell"]) for c in r] for ri, r in enumerate(diag_rows)],
        colWidths=[46 * mm, 62 * mm, 72 * mm],
    )
    td.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("BOX", (0, 0), (-1, -1), 0.7, BORDER),
        ("INNERGRID", (0, 0), (-1, -1), 0.4, BORDER),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("PADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(td)
    story.append(PageBreak())

    # PAGINA 2: PILAR 1 - LADO CLIENTES (OBRAS E DECISORES)
    story.append(Paragraph("3. Pilar 1 — Lado Clientes: Captação de Obras de Alta Margem", styles["SecHead"]))
    story.append(Paragraph("A base consolidada WiNS combina fontes oficiais em tempo real com portais industriais preditivos, entregando o ciclo completo da obra e os decisores reais (Compras, Suprimentos, Engenharia/CAPEX e Diretoria).", styles["Body"]))

    pillars = [
        ["Unidade de Negócio Progen", "Fontes WiNS Aderentes", "Aplicação Comercial Imediata"],
        ["Progen Energia S.A.\n(R$ 59,3 mi de lucro em 2024)", f"ANEEL SIGET Transmissão ({tot_siget} obras), ANEEL SIGA ({tot_siga}) e BNDES Energia", "Mapeamento de subestações, LTs e redes com concessionária, CNPJ, fase e contatos técnicos."],
        ["Engenharia, EPCM &amp; Valpro\n(Papel/Celulose, Bioenergia, Química)", "BNDES Financiamento, ConVisão CNC (490), CIMM (14) e BVMI Radar (189)", "Abordagem na etapa de licenciamento/projeto para vender engenharia básica/detalhada e EPCM."],
        ["Progen Planway &amp; Infraestrutura\n(Transportes, Aeroportos, Saneamento)", f"CVM Debêntures Lei 12.431 ({tot_cvm}), PNCP (mod. 4/5/6/8) e Portal MG (168)", "Monitoramento diário de emissões incentivadas, concessões e licitações com orçamento."],
        ["Progen Manutenção &amp; Facilities\n(Paradas e Contratos Recorrentes)", "Obras em fase 4_EM_EXECUCAO_ANDAMENTO (409) e IBAMA SISLIC LI", "Entrada no pós-implantação e comissionamento para contratos plurianuais de manutenção."],
    ]
    tp = Table(
        [[Paragraph(f"<b>{c}</b>" if ri == 0 else c, styles["SmallBold"] if ri == 0 else styles["SmallCell"]) for c in r] for ri, r in enumerate(pillars)],
        colWidths=[48 * mm, 60 * mm, 72 * mm],
    )
    tp.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("BOX", (0, 0), (-1, -1), 0.7, BORDER),
        ("INNERGRID", (0, 0), (-1, -1), 0.4, BORDER),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("PADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(tp)
    story.append(Spacer(1, 6))

    story.append(Paragraph("3.1 Distribuição por Fase da Obra (Timing de Abordagem)", styles["SecHead"]))
    fase_desc = {
        "1_ANUNCIO_LICITACAO_LP": "Anúncio / Licitação / LP — Janela ideal para Engenharia Consultiva, estudos e especificação.",
        "2_NAO_INICIADA_INICIAL": "Não Iniciada / Inicial — Janela para EPCM, orçamento de CAPEX e pré-qualificação.",
        "3_LI_LIBERADA_CANTEIRO": "LI Liberada / Canteiro — Gatilho imediato de contratação de obra, montagem e suprimentos.",
        "4_EM_EXECUCAO_ANDAMENTO": "Em Execução — Demanda ativa de gerenciamento de campo, subcontratação e paradas/manutenção.",
        "5_FINANCIAMENTO_ATIVO": "Financiamento Ativo (BNDES) — Recurso aprovado; menor risco de atraso e inadimplência.",
    }
    tf_rows = [["Fase Canônica (fase_obra)", "Obras", "Janela Comercial para a Progen"]]
    for f_code, f_cnt in fases_rows:
        tf_rows.append([f_code, f"{f_cnt:,}".replace(",", "."), fase_desc.get(f_code, "")])
    tf = Table(
        [[Paragraph(f"<b>{c}</b>" if ri == 0 else c, styles["SmallBold"] if ri == 0 else styles["SmallCell"]) for c in r] for ri, r in enumerate(tf_rows)],
        colWidths=[50 * mm, 18 * mm, 112 * mm],
    )
    tf.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("BOX", (0, 0), (-1, -1), 0.7, BORDER),
        ("INNERGRID", (0, 0), (-1, -1), 0.4, BORDER),
        ("PADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(tf)
    story.append(Spacer(1, 6))

    story.append(Paragraph("3.2 Top 8 UFs em Obras Ativas (Alinhamento com Sede e Escritórios Progen)", styles["SecHead"]))
    uf_rows = [["UF", "Obras Ativas", "Com Decisor Acionável", "% Cobertura", "CAPEX Estimado (R$ bi)"]]
    for uf, cnt, aci, cap_bi in top_ufs_obras:
        uf_rows.append([uf or "N/D", f"{cnt:,}".replace(",", "."), f"{aci:,}".replace(",", "."), f"{aci/cnt*100:.1f}%", f"R$ {cap_bi:,.2f} bi".replace(",", "X").replace(".", ",").replace("X", ".")])
    tu = Table(
        [[Paragraph(f"<b>{c}</b>" if ri == 0 else c, styles["SmallBold"] if ri == 0 else styles["SmallCell"]) for c in r] for ri, r in enumerate(uf_rows)],
        colWidths=[22 * mm, 36 * mm, 44 * mm, 32 * mm, 46 * mm],
    )
    tu.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("BOX", (0, 0), (-1, -1), 0.7, BORDER),
        ("INNERGRID", (0, 0), (-1, -1), 0.4, BORDER),
        ("PADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(tu)
    story.append(PageBreak())

    # PAGINA 3: PILAR 2 - LADO FORNECEDORES E SUPRIMENTOS
    story.append(Paragraph("4. Pilar 2 — Lado Fornecedores: Suprimentos, Locação &amp; Mitigação de Risco", styles["SecHead"]))
    story.append(Paragraph("Na demonstração de resultados de 2024 (nota 26.2), a Progen registrou <b>R$ 89,3 milhões em serviços de terceiros</b>, <b>R$ 67,6 milhões em locação de máquinas, equipamentos e veículos (+61,3%)</b>, <b>R$ 32,8 milhões em manutenção de frotas (+85,6%)</b> e <b>R$ 259,4 milhões em adiantamentos a fornecedores</b>. A base de <b>4.090.553 fornecedores</b> do WiNS resolve três gargalos operacionais da área de Suprimentos e Expediting:", styles["Body"]))
    story.append(Paragraph("• <b>1. Sourcing competitivo nas 15 filiais:</b> localizar fornecedores ativos (situação ATIVA na RF) no município da obra antes de mobilizar equipamentos ou subempreiteiros de fora do estado.", styles["BulletItem"]))
    story.append(Paragraph("• <b>2. Blindagem de adiantamentos (R$ 259,4 mi):</b> filtrar subcontratados por <b>Porte Real (Médio/Grande)</b> e <b>Capital Social</b>, evitando contratar empresas sem lastro para pacotes críticos de EPC.", styles["BulletItem"]))
    story.append(Paragraph("• <b>3. Conformidade com o Código de Conduta de Fornecedores (2025):</b> pré-triagem cadastral por CNAE, matriz/filial e contatos corporativos validados.", styles["BulletItem"]))
    story.append(Spacer(1, 4))

    story.append(Paragraph("4.1 Cobertura da Base WiNS nos Setores Críticos de Suprimentos da Progen", styles["SecHead"]))
    sf_rows = [["Setor Consolidado (CNAE)", "CNPJs Ativos na Base", "Estruturados (Média/Grande)", "Uso Direto em Suprimentos / Expediting"]]
    uso_map = {
        "CONSTRUCAO_ESPECIALIZADA": "Montagem, terraplanagem, fundações, elétrica e instalações em campo.",
        "ENGENHARIA_ARQUITETURA": "Apoio técnico, projetos complementares, topografia e inspeções.",
        "METALURGIA_ESTRUTURAS": "Caldeiraria, estruturas metálicas, suportes e tubulações industriais.",
        "LOCACAO_MAQUINAS_EQUIPAMENTOS": "Guindastes, linha amarela, geradores e containers (gasto de R$ 67,6 mi/ano).",
        "INFRAESTRUTURA": "Subcontratação de trechos civis, pavimentação, drenagem e saneamento.",
        "ENERGIA": "Apoio à Progen Energia em redes de distribuição, subestações e LTs.",
        "SANEAMENTO": "Obras hidráulicas, adutoras, estações de tratamento e utilidades.",
    }
    for sec, cnt, mg in setores_forn:
        sf_rows.append([sec, f"{cnt:,}".replace(",", "."), f"{mg:,}".replace(",", "."), uso_map.get(sec, "")])
    tsf = Table(
        [[Paragraph(f"<b>{c}</b>" if ri == 0 else c, styles["SmallBold"] if ri == 0 else styles["SmallCell"]) for c in r] for ri, r in enumerate(sf_rows)],
        colWidths=[50 * mm, 32 * mm, 34 * mm, 64 * mm],
    )
    tsf.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("BOX", (0, 0), (-1, -1), 0.7, BORDER),
        ("INNERGRID", (0, 0), (-1, -1), 0.4, BORDER),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("PADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(tsf)
    story.append(Spacer(1, 6))

    story.append(Paragraph("4.2 Fornecedores de Engenharia Disponíveis nas Praças Estratégicas da Progen", styles["SecHead"]))
    pf_rows = [["UF / Praça Progen", "Fornecedores nos 7 Setores", "Com Contato Direto (E-mail/Tel.)", "% Acionável"]]
    for uf, cnt, aci in pracas_forn:
        pf_rows.append([uf, f"{cnt:,}".replace(",", "."), f"{aci:,}".replace(",", "."), f"{aci/cnt*100:.1f}%"])
    tpf = Table(
        [[Paragraph(f"<b>{c}</b>" if ri == 0 else c, styles["SmallBold"] if ri == 0 else styles["SmallCell"]) for c in r] for ri, r in enumerate(pf_rows)],
        colWidths=[36 * mm, 50 * mm, 58 * mm, 36 * mm],
    )
    tpf.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("BOX", (0, 0), (-1, -1), 0.7, BORDER),
        ("INNERGRID", (0, 0), (-1, -1), 0.4, BORDER),
        ("PADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(tpf)
    story.append(PageBreak())

    # PAGINA 4: RECURSOS DA FERRAMENTA, HIGIENE E PLANO DE PILOTO
    story.append(Paragraph("5. Recursos da Plataforma, Governança de Dados &amp; Plano de Piloto", styles["SecHead"]))
    feats = [
        ["Módulo WiNS", "O que Entrega ao Time da Progen"],
        ["Dashboard Web + Filtros Avançados", "Filtros combinados por UF, Fonte, Categoria, Fase da Obra, Tipo de CAPEX, Qualificação e Status CRM."],
        ["Aba Alertas &amp; Radar BVMI", "Alertas automáticos de obras que mudaram de fase (LP → LI/Execução) e cruzamento com Radar BVMI 2026."],
        ["Lead Score Canônico (0–100)", "Pontuação transparente por fase, CAPEX, decisor Compras/Engenharia e canais validados."],
        ["Página da Obra + Top Fornecedores", "Raio-X completo com decisores, botão 'Copiar Abordagem' (1 clique) e Top 8 fornecedores elegíveis na UF."],
        ["Decisores Únicos (Anti-Spam)", "Visão deduplicada por pessoa (3.118 decisores) para evitar abordagens repetidas pela equipe comercial."],
        ["Mini-CRM &amp; Exportação CSV/Excel/PDF", "Gestão de etapa (Novo / Contato / Proposta / Descartado), planilha executiva e dossiês PDF sob demanda."],
    ]
    tf_mod = Table(
        [[Paragraph(f"<b>{c}</b>" if ri == 0 else c, styles["SmallBold"] if ri == 0 else styles["SmallCell"]) for c in r] for ri, r in enumerate(feats)],
        colWidths=[54 * mm, 126 * mm],
    )
    tf_mod.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("BOX", (0, 0), (-1, -1), 0.7, BORDER),
        ("INNERGRID", (0, 0), (-1, -1), 0.4, BORDER),
        ("PADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(tf_mod)
    story.append(Spacer(1, 6))

    story.append(Paragraph("5.1 Protocolo de Qualidade e Higiene dos Dados (Zero Dados Inventados)", styles["SecHead"]))
    story.append(Paragraph("• <b>Telefones validados via google/libphonenumber:</b> padronização E.164/nacional e remoção de números inválidos.", styles["BulletItem"]))
    story.append(Paragraph("• <b>Auditoria de E-mails Corporativos:</b> verificação DNS MX e checagem SMTP, com vínculo exato por LinkedIn ou CNPJ.", styles["BulletItem"]))
    story.append(Paragraph("• <b>Higiene de LinkedIn e QSA Oficial:</b> remoção automática de perfis truncados/sintéticos e enriquecimento de sócios PF na Receita Federal (`minhareceita.org`).", styles["BulletItem"]))

    story.append(Paragraph("5.2 Cronograma Sugerido de Piloto (30 Dias)", styles["SecHead"]))
    piloto = [
        ["Semana", "Frente Comercial (Clientes)", "Frente Suprimentos (Fornecedores)"],
        ["Semana 1", "Entrega do Dossiê 06 (12 obras prioritárias) + acesso ao Dashboard para Progen Energia e EPCM.", "Calibração dos CNAEs críticos (locação de máquinas, montagem, caldeiraria) por filial."],
        ["Semana 2", "Abordagem ativa com os decisores validados (Compras/Engenharia) e registro no Mini-CRM.", "Entrega do recorte de fornecedores homologáveis nas praças SP, MG, RJ, MA e BA."],
        ["Semana 3", "Recebimento do primeiro boletim de mudanças de fase (LP → LI/Execução) e novas obras SIGET/CVM.", "Checagem de porte e capital social para redução de risco em adiantamentos."],
        ["Semana 4", "Revisão de ROI (reuniões geradas, propostas em cotação) e definição de escopo anual.", "Avaliação de economia em cotações locais e integração contínua com Suprimentos."],
    ]
    tpil = Table(
        [[Paragraph(f"<b>{c}</b>" if ri == 0 else c, styles["SmallBold"] if ri == 0 else styles["SmallCell"]) for c in r] for ri, r in enumerate(piloto)],
        colWidths=[24 * mm, 78 * mm, 78 * mm],
    )
    tpil.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("BOX", (0, 0), (-1, -1), 0.7, BORDER),
        ("INNERGRID", (0, 0), (-1, -1), 0.4, BORDER),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("PADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(tpil)
    story.append(Spacer(1, 6))
    story.append(Paragraph("<b>Próximo passo imediato:</b> reunião executiva de 20 minutos com a Diretoria Comercial / Novos Negócios e Gerência de Suprimentos (Largo do Arouche, 24 — São Paulo/SP | Tel. (11) 3352-9000) para apresentação ao vivo do sistema e ativação do piloto.", styles["Body"]))

    doc.build(story)


def generate_obras_pdf(styles, con):
    doc = SimpleDocTemplate(PDF_OBRAS, pagesize=A4, leftMargin=14 * mm, rightMargin=14 * mm, topMargin=14 * mm, bottomMargin=14 * mm)
    story = []

    story.append(Paragraph("PORTFÓLIO DE 12 OBRAS PARA PROSPECÇÃO — PROGEN S.A.", styles["DocTitle"]))
    story.append(Paragraph("Recorte real do banco WiNS Engenharia (2026–2027) aderente a Progen Energia, Engenharia/EPCM, Valpro e Infraestrutura.", styles["DocSub"]))
    story.append(HRFlowable(width="100%", thickness=2.0, color=GOLD, spaceAfter=8))

    summary_rows = [["#", "Score", "Empresa Titular", "Obra / Projeto", "UF", "CAPEX", "Decisores"]]
    detailed_data = []

    for idx, (id_ext, fit_reason) in enumerate(TARGET_IDS, 1):
        obra = con.execute("""
            SELECT
                o.obra_id, o.fonte, o.obra_nome, o.obra_empresa, o.obra_cnpj,
                o.categoria_macro, o.obra_uf, o.obra_municipio, o.capex_estimado,
                o.capex_tipo, o.data_inicio_prevista, o.data_fim_prevista, o.situacao, o.url_origem,
                o.dominio_corporativo, o.mx_ativo, o.whatsapp_oficial, o.telefones_site,
                o.fase_obra, COALESCE(o.score_prioridade, 0)
            FROM todas_obras_consolidadas o
            WHERE o.obra_id = ?
            LIMIT 1
        """, [id_ext]).fetchone()

        decs = con.execute("""
            SELECT decisor_nome, decisor_cargo, perfil_decisor, decisor_email, decisor_telefone, decisor_linkedin
            FROM validacao_decisores_obras_novas
            WHERE id_externo = ? AND is_contato_acionavel = TRUE
            ORDER BY
                CASE perfil_decisor
                    WHEN '1_COMPRADOR_SUPRIMENTOS' THEN 1
                    WHEN '2_ENGENHARIA_OBRAS_CAPEX' THEN 2
                    WHEN '2_GESTOR_TECNICO_OBRA' THEN 2
                    WHEN '3_DIRETORIA_EXECUTIVA' THEN 3
                    ELSE 4
                END,
                (decisor_linkedin IS NOT NULL) DESC,
                (decisor_email IS NOT NULL) DESC
            LIMIT 6
        """, [id_ext]).fetchall()

        summary_rows.append([
            str(idx),
            str(obra[19]),
            Paragraph(clean_str(obra[3]), styles["SmallCell"]),
            Paragraph(clean_str((obra[2] or "")[:58]), styles["SmallCell"]),
            clean_str(obra[6]),
            fmt_capex(obra[8]),
            str(len(decs)),
        ])
        detailed_data.append((idx, obra, fit_reason, decs))

    tsum = Table(summary_rows, colWidths=[7 * mm, 12 * mm, 48 * mm, 58 * mm, 10 * mm, 26 * mm, 21 * mm])
    tsum.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 7.8),
        ("BOX", (0, 0), (-1, -1), 0.7, BORDER),
        ("INNERGRID", (0, 0), (-1, -1), 0.4, BORDER),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("PADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(tsum)
    story.append(PageBreak())

    for idx, obra, fit_reason, decs in detailed_data:
        (
            id_ext, fonte, nome, emp, cnpj, cat, uf, mun, capex, cap_tipo,
            dt_ini, dt_fim, sit, url_orig, dom, mx_ok, wa_of, tel_site, fase, score
        ) = obra

        story.append(Paragraph(f"OBRA #{idx:02d} (Score {score}/100) — {clean_str(emp)}", styles["SecHead"]))
        story.append(Paragraph(f"<b>Projeto:</b> {clean_str(nome)}", styles["Body"]))

        meta_rows = [
            ["ID / Fonte", f"{clean_str(id_ext)} ({clean_str(fonte)})", "CNPJ Titular", clean_str(cnpj)],
            ["Localização", f"{clean_str(mun)} / {clean_str(uf)}", "Fase / Categoria", f"{clean_str(fase)} | {clean_str(cat)}"],
            ["CAPEX / Tipo", f"{fmt_capex(capex)} ({clean_str(cap_tipo)})", "Vigência / Status", f"{clean_str(dt_ini)} a {clean_str(dt_fim)} | {clean_str(sit)}"],
            ["Domínio / MX", f"{clean_str(dom)} (MX={'Ativo' if mx_ok else 'N/D'})", "WhatsApp / Tel. Site", f"{clean_str(wa_of)} | {clean_str(tel_site)}"],
        ]
        tmeta = Table(
            [[Paragraph(f"<b>{r[0]}</b>", styles["SmallBold"]), Paragraph(r[1], styles["SmallCell"]),
              Paragraph(f"<b>{r[2]}</b>", styles["SmallBold"]), Paragraph(r[3], styles["SmallCell"])] for r in meta_rows],
            colWidths=[30 * mm, 64 * mm, 32 * mm, 56 * mm],
        )
        tmeta.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), LIGHT_BG),
            ("BOX", (0, 0), (-1, -1), 0.6, BORDER),
            ("INNERGRID", (0, 0), (-1, -1), 0.4, BORDER),
            ("PADDING", (0, 0), (-1, -1), 3.5),
        ]))
        story.append(tmeta)
        story.append(Spacer(1, 3))
        story.append(Paragraph(f"<b>Por que ofertar à Progen S.A.:</b> {clean_str(fit_reason)}", styles["Body"]))
        story.append(Paragraph(f"<b>Fonte Oficial:</b> {clean_str(url_orig)}", styles["Meta"]))
        story.append(Spacer(1, 3))

        dec_rows = [["Nome do Decisor", "Cargo / Área", "E-mail", "Telefone", "LinkedIn"]]
        for d in decs:
            dec_rows.append([
                Paragraph(clean_str(d[0]), styles["SmallBold"]),
                Paragraph(clean_str(d[1]), styles["SmallCell"]),
                Paragraph(clean_str(d[3]), styles["SmallCell"]),
                Paragraph(clean_str(d[4]), styles["SmallCell"]),
                Paragraph(clean_str(d[5]), styles["SmallCell"]),
            ])

        tdec = Table(dec_rows, colWidths=[34 * mm, 44 * mm, 38 * mm, 24 * mm, 42 * mm])
        tdec.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), NAVY),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 7.4),
            ("BOX", (0, 0), (-1, -1), 0.6, BORDER),
            ("INNERGRID", (0, 0), (-1, -1), 0.4, BORDER),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("PADDING", (0, 0), (-1, -1), 3.5),
        ]))
        story.append(tdec)
        story.append(Spacer(1, 7))
        if idx % 2 == 0 and idx < len(detailed_data):
            story.append(PageBreak())

    doc.build(story)


def main():
    con = duckdb.connect(MAIN_DB, read_only=True)
    styles = build_styles()
    generate_proposta_pdf(styles, con)
    generate_obras_pdf(styles, con)
    con.close()
    print(f"PDF 1 gerado: {PDF_PROPOSTA} ({os.path.getsize(PDF_PROPOSTA)/1024:.1f} KB)")
    print(f"PDF 2 gerado: {PDF_OBRAS} ({os.path.getsize(PDF_OBRAS)/1024:.1f} KB)")


if __name__ == "__main__":
    main()
