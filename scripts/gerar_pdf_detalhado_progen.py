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
OUT_PDF = os.path.join(BASE_DIR, "Entregas", "07_Estudo_Completo_WiNS_para_Progen_SA.pdf")

NAVY = colors.HexColor("#0F172A")
GOLD = colors.HexColor("#C9A227")
BLUE = colors.HexColor("#1D4ED8")
SLATE = colors.HexColor("#475569")
LIGHT_BG = colors.HexColor("#F8FAFC")
SOFT_GOLD = colors.HexColor("#FEF9E7")
BORDER = colors.HexColor("#CBD5E1")


def draw_cover(canvas, doc):
    canvas.saveState()
    w, h = A4
    canvas.setFillColor(NAVY)
    canvas.rect(0, 0, w, h, stroke=0, fill=1)
    canvas.setFillColor(GOLD)
    canvas.rect(18 * mm, h - 22 * mm, 24 * mm, 1.5 * mm, stroke=0, fill=1)
    canvas.setStrokeColor(GOLD)
    canvas.setLineWidth(1.2)
    canvas.rect(w - 42 * mm, h - 42 * mm, 24 * mm, 24 * mm, stroke=1, fill=0)
    canvas.setFillColor(GOLD)
    canvas.setFont("Helvetica-Bold", 14)
    canvas.drawCentredString(w - 30 * mm, h - 32 * mm, "W")
    canvas.setStrokeColor(colors.HexColor("#334155"))
    canvas.setLineWidth(0.6)
    canvas.line(18 * mm, h - 102 * mm, w - 18 * mm, h - 102 * mm)
    canvas.line(18 * mm, h - 145 * mm, w - 18 * mm, h - 145 * mm)
    canvas.restoreState()


def draw_later(canvas, doc):
    canvas.saveState()
    w, h = A4
    canvas.setStrokeColor(GOLD)
    canvas.setLineWidth(0.9)
    canvas.line(15 * mm, h - 11 * mm, w - 15 * mm, h - 11 * mm)
    canvas.setStrokeColor(BORDER)
    canvas.setLineWidth(0.5)
    canvas.line(15 * mm, 12 * mm, w - 15 * mm, 12 * mm)
    canvas.setFillColor(SLATE)
    canvas.setFont("Helvetica", 7.5)
    canvas.drawString(15 * mm, 8 * mm, "WiNS ENGENHARIA · ESTUDO ESTRATÉGICO & PROPOSTA PARA PROGEN S.A. · NOVEMBRO DE 2026")
    canvas.drawRightString(w - 15 * mm, 8 * mm, f"Página {doc.page}")
    canvas.restoreState()


def build_styles():
    s = getSampleStyleSheet()
    s.add(ParagraphStyle(name="CoverKicker", fontName="Helvetica", fontSize=9.5, leading=13, textColor=GOLD, spaceAfter=10))
    s.add(ParagraphStyle(name="CoverTitle", fontName="Helvetica-Bold", fontSize=27, leading=32, textColor=colors.white, spaceAfter=8))
    s.add(ParagraphStyle(name="CoverSub", fontName="Helvetica", fontSize=12.5, leading=18, textColor=colors.HexColor("#CBD5E1"), spaceAfter=18))
    s.add(ParagraphStyle(name="CoverMeta", fontName="Helvetica", fontSize=9.5, leading=14.5, textColor=colors.HexColor("#E2E8F0"), spaceAfter=3))
    s.add(ParagraphStyle(name="CoverStatVal", fontName="Helvetica-Bold", fontSize=18, leading=22, textColor=colors.white))
    s.add(ParagraphStyle(name="CoverStatLbl", fontName="Helvetica", fontSize=8.0, leading=11, textColor=colors.HexColor("#94A3B8")))
    s.add(ParagraphStyle(name="CoverFoot", fontName="Helvetica", fontSize=8.0, leading=11.5, textColor=colors.HexColor("#94A3B8")))

    s.add(ParagraphStyle(name="DocTitle", fontName="Helvetica-Bold", fontSize=17.5, leading=21, textColor=NAVY, spaceAfter=3))
    s.add(ParagraphStyle(name="SecHead", fontName="Helvetica-Bold", fontSize=12.2, leading=16, textColor=BLUE, spaceBefore=9, spaceAfter=4))
    s.add(ParagraphStyle(name="SubHead", fontName="Helvetica-Bold", fontSize=10.2, leading=14, textColor=NAVY, spaceBefore=6, spaceAfter=3))
    s.add(ParagraphStyle(name="Body", fontName="Helvetica", fontSize=9.0, leading=13.2, textColor=NAVY, spaceAfter=4))
    s.add(ParagraphStyle(name="BulletItem", fontName="Helvetica", fontSize=8.9, leading=12.8, textColor=NAVY, leftIndent=9, spaceAfter=3))
    s.add(ParagraphStyle(name="SmallCell", fontName="Helvetica", fontSize=7.7, leading=10.2, textColor=NAVY))
    s.add(ParagraphStyle(name="SmallBold", fontName="Helvetica-Bold", fontSize=7.7, leading=10.2, textColor=NAVY))
    return s


def fmt_int(v):
    return f"{int(v or 0):,}".replace(",", ".")


def fmt_capex(val):
    if val is None or val <= 0:
        return "N/D"
    if val >= 1e9:
        return f"R$ {val/1e9:,.2f} bi".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"R$ {val/1e6:,.2f} mi".replace(",", "X").replace(".", ",").replace("X", ".")


def clean(v):
    return str(v).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;") if v is not None else "—"


def make_table(rows, col_widths, header_bg=NAVY):
    tbl = Table(
        [[Paragraph(f"<b>{clean(c)}</b>" if ri == 0 else clean(c), build_cell_style(ri == 0)) for c in r] for ri, r in enumerate(rows)],
        colWidths=col_widths,
        repeatRows=1,
    )
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), header_bg),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("BOX", (0, 0), (-1, -1), 0.7, BORDER),
        ("INNERGRID", (0, 0), (-1, -1), 0.4, BORDER),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("PADDING", (0, 0), (-1, -1), 4.2),
    ]))
    return tbl


_STYLES = build_styles()


def build_cell_style(is_header: bool):
    if is_header:
        return ParagraphStyle(name="HdrCell", fontName="Helvetica-Bold", fontSize=7.7, leading=10.0, textColor=colors.white)
    return _STYLES["SmallCell"]


def main():
    con = duckdb.connect(MAIN_DB, read_only=True)
    tot_obras, tot_aci, tot_op = con.execute(
        "SELECT COUNT(*), SUM(CASE WHEN decisores_acionaveis>0 THEN 1 ELSE 0 END), SUM(CASE WHEN decisores_operacionais>0 THEN 1 ELSE 0 END) FROM todas_obras_consolidadas"
    ).fetchone()
    tot_uni, uni_lk, uni_tel, uni_em = con.execute(
        "SELECT COUNT(*), COUNT(decisor_linkedin), COUNT(decisor_telefone), COUNT(decisor_email) FROM campanha_por_decisor_unico"
    ).fetchone()
    tot_forn = con.execute("SELECT COUNT(*) FROM fornecedores").fetchone()[0]
    fontes_rows = con.execute("""
        SELECT fonte, COUNT(*), SUM(CASE WHEN decisores_acionaveis>0 THEN 1 ELSE 0 END), ROUND(SUM(COALESCE(capex_estimado,0))/1e9, 2)
        FROM todas_obras_consolidadas GROUP BY 1 ORDER BY 2 DESC
    """).fetchall()
    fases_rows = con.execute("SELECT fase_obra, COUNT(*) FROM todas_obras_consolidadas GROUP BY 1 ORDER BY 1").fetchall()
    top_ufs_obras = con.execute("""
        SELECT obra_uf, COUNT(*), SUM(CASE WHEN decisores_acionaveis>0 THEN 1 ELSE 0 END), ROUND(SUM(COALESCE(capex_estimado,0))/1e9, 2)
        FROM todas_obras_consolidadas GROUP BY 1 ORDER BY 2 DESC LIMIT 10
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
    sample_obras = con.execute("""
        SELECT obra_id, fonte, obra_empresa, obra_uf, capex_estimado, decisores_acionaveis, fase_obra, COALESCE(score_prioridade,0)
        FROM todas_obras_consolidadas
        WHERE obra_id IN ('CONVISAO-47472','CVM160-24677','SIGET-6714','BNDES-26700181','BNDES-25204051','BNDES-25204031','BNDES-26200911','BNDES-26200141')
        ORDER BY COALESCE(score_prioridade,0) DESC, capex_estimado DESC
    """).fetchall()
    con.close()

    os.makedirs(os.path.dirname(OUT_PDF), exist_ok=True)
    doc = SimpleDocTemplate(OUT_PDF, pagesize=A4, leftMargin=15 * mm, rightMargin=15 * mm, topMargin=16 * mm, bottomMargin=16 * mm)
    s = _STYLES
    story = []

    # ==================== PAGINA 1: CAPA ====================
    story.append(Spacer(1, 14 * mm))
    story.append(Paragraph("E S T U D O   E S T R A T É G I C O   &amp;   P R O P O S T A   B 2 B", s["CoverKicker"]))
    story.append(Paragraph("WiNS ENGENHARIA<br/>× PROGEN S.A.", s["CoverTitle"]))
    story.append(Paragraph(
        "Como nossa plataforma de inteligência bidirecional amplia a margem comercial em Engenharia, EPCM e Energia (Clientes) e reduz custo e risco na cadeia de Suprimentos (Fornecedores).",
        s["CoverSub"],
    ))
    story.append(Spacer(1, 10 * mm))
    story.append(Paragraph("<b>Elaboração:</b> 19 de novembro de 2026", s["CoverMeta"]))
    story.append(Paragraph("<b>Empresa-alvo:</b> Progen S.A. (CNPJ 57.748.204/0001-22) · Sede São Paulo/SP", s["CoverMeta"]))
    story.append(Paragraph("<b>Bases cruzadas:</b> Demonstrações Auditadas BDO 2024 + Banco DuckDB WiNS Engenharia", s["CoverMeta"]))
    story.append(Paragraph("<b>Escopo:</b> Obras 2026–2027 (CAPEX &gt; R$ 100 mil) + Base de 4,09 milhões de CNPJs", s["CoverMeta"]))
    story.append(Spacer(1, 18 * mm))

    cov_stats = [[
        [Paragraph(fmt_int(tot_obras), s["CoverStatVal"]), Paragraph("OBRAS ATIVAS<br/>CONSOLIDADAS", s["CoverStatLbl"])],
        [Paragraph(fmt_int(tot_uni), s["CoverStatVal"]), Paragraph("DECISORES ÚNICOS<br/>VALIDADOS", s["CoverStatLbl"])],
        [Paragraph("4,09 mi", s["CoverStatVal"]), Paragraph("FORNECEDORES<br/>SANEADOS (CNPJs)", s["CoverStatLbl"])],
        [Paragraph("756 + 53", s["CoverStatVal"]), Paragraph("TRANSMISSÃO SIGET<br/>+ DEBÊNTURES CVM", s["CoverStatLbl"])],
    ]]
    t_cov = Table(cov_stats, colWidths=[44 * mm, 44 * mm, 44 * mm, 44 * mm])
    t_cov.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("PADDING", (0, 0), (-1, -1), 4)]))
    story.append(t_cov)
    story.append(Spacer(1, 46 * mm))
    story.append(Paragraph(
        "Documento elaborado com dados reais das demonstrações financeiras públicas da Progen S.A. (2024) e indicadores verificados no banco DuckDB da WiNS Engenharia em 19/11/2026.",
        s["CoverFoot"],
    ))
    story.append(PageBreak())

    # ==================== PAGINA 2: SUMARIO & DIAGNOSTICO PROGEN ====================
    story.append(Paragraph("1. Sumário Executivo &amp; Ficha de Aderência", s["DocTitle"]))
    story.append(HRFlowable(width="100%", thickness=1.5, color=GOLD, spaceAfter=6))
    story.append(Paragraph(
        "A Progen S.A. faturou <b>R$ 1,54 bilhão</b> em 2024 (+16,9% vs. 2023), lidera há seis anos o Ranking da Engenharia Brasileira e opera com mais de 7.000 colaboradores em 4 escritórios regionais (SP, BH, São Luís e São Gonçalo) e 15 filiais. Apesar da escala sólida, os números auditados de 2024 mostram que o desafio central da companhia em 2026–2027 é <b>recompor margem operacional e eficiência de capital de giro</b>.",
        s["Body"],
    ))
    story.append(Paragraph(
        "A plataforma <b>WiNS Engenharia</b> resolve exatamente essa equação por atuar nos <b>dois lados do balanço da Progen</b>: (1) acelera a captura de contratos de maior margem técnica em <b>Energia, EPCM e Infraestrutura</b> (Lado Clientes) e (2) estrutura o sourcing regional e a triagem financeira de subcontratados e locadores nas 15 filiais (Lado Fornecedores).",
        s["Body"],
    ))

    story.append(Paragraph("1.1 Cruzamento Direto: Dores Reais da Progen (BDO 2024) × Solução WiNS", s["SecHead"]))
    diag_rows = [
        ["Indicador / Pressão (Progen)", "Dado Auditado (2024)", "Como a WiNS Engenharia Atua na Prática"],
        ["Compressão de margem bruta", "Caiu de 18,2% para 16,3% (crescimento puxado por facilities e manutenção).", "Direciona Progen Energia, EPCM e Valpro para projetos de maior valor agregado antes da licitação aberta."],
        ["Prazo de recebimento (DSO)", "Subiu de 122 para 157 dias; fluxo operacional negativo em −R$ 215,2 mi.", "Prioriza obras com financiamento já aprovado (BNDES e CVM Debêntures) e Lead Score 0–100."],
        ["Reoneração da folha (Lei 14.973)", "Pessoal consome 68,2% da receita (R$ 1,05 bi) e sofre alta gradual de encargos.", "Exige seletividade comercial: focar contratos de Engenharia/EPCM com maior margem por colaborador."],
        ["Serviços de Terceiros", "Gasto anual de R$ 89,3 milhões em subcontratação de serviços.", "Disponibiliza 1,57M construtoras especializadas e 241 mil engenharias por UF/município para cotação."],
        ["Locação de Máquinas e Frotas", "R$ 67,6 mi em locação (+61,3%) + R$ 32,8 mi manutenção de frotas (+85,6%).", "83.398 locadores de máquinas/equipamentos mapeados perto dos canteiros para reduzir frete e diária."],
        ["Adiantamentos a Fornecedores", "Saltaram para R$ 259,4 milhões (+985,6%); DPO de apenas 12 dias.", "Checagem cadastral imediata de porte real, capital social e situação ATIVA antes de liberar adiantamento."],
    ]
    story.append(make_table(diag_rows, [42 * mm, 58 * mm, 80 * mm]))
    story.append(Spacer(1, 6))

    story.append(Paragraph("1.2 Inventário Atualizado da Plataforma WiNS Engenharia (19/11/2026)", s["SecHead"]))
    inv_rows = [
        ["Dimensão na Plataforma", "Volume Atual Verificado", "Aplicação Direta na Progen"],
        ["Obras Consolidadas (2026–2027)", f"{fmt_int(tot_obras)} obras ({fmt_int(tot_aci)} acionáveis = {tot_aci/tot_obras*100:.1f}%)", "Pipeline ativo de curto e médio prazo em todo o Brasil."],
        ["Decisores de Compras / Engenharia", f"{fmt_int(tot_op)} obras com Compras/Eng. · {fmt_int(tot_uni)} pessoas únicas", "Acesso direto sem gatekeeper (anti-spam por pessoa)."],
        ["Canais Validados nos Decisores", f"{fmt_int(uni_lk)} LinkedIns · {fmt_int(uni_tel)} Telefones · {fmt_int(uni_em)} E-mails", "Higiene via libphonenumber, SMTP e auditoria de URL."],
        ["Base de Fornecedores Saneada", f"{fmt_int(tot_forn)} CNPJs ativos indexados por CNAE, Porte e UF", "Homologação rápida de subcontratados nas 15 filiais."],
    ]
    story.append(make_table(inv_rows, [50 * mm, 64 * mm, 66 * mm]))
    story.append(PageBreak())

    # ==================== PAGINA 3: PILAR 1 - LADO CLIENTES ====================
    story.append(Paragraph("2. Pilar 1 (Lado Clientes): Como Capturar Obras de Maior Margem", s["DocTitle"]))
    story.append(HRFlowable(width="100%", thickness=1.5, color=GOLD, spaceAfter=6))
    story.append(Paragraph(
        "A força da WiNS para o time comercial da Progen está em unir <b>fontes oficiais reguladas</b> (ANEEL, BNDES, CVM, PNCP, IBAMA, Portal MG) com <b>portais industriais preditivos</b> (ConVisão, CIMM e BVMI), classificando cada projeto por fase da obra e poder de compra.",
        s["Body"],
    ))

    story.append(Paragraph("2.1 Cobertura por Fonte Oficial e Preditiva (Base Ativa)", s["SecHead"]))
    f_rows = [["Fonte Integrada", "Obras", "Acionáveis", "CAPEX Mapeado", "Vertical Progen Beneficiada"]]
    vert_map = {
        "aneel_siga": "Progen Energia (Geração, Eólica, Solar, Térmica)",
        "aneel_transmissao": "Progen Energia (Subestações e Linhas de Transmissão)",
        "convisao_cnc": "Engenharia, EPCM & Valpro (Obras Industriais/Civis)",
        "pncp_mod_4": "Progen Planway & Infraestrutura (Licitações)",
        "bndes_financiamento": "Engenharia, EPCM & Energia (CAPEX Aprovado)",
        "portal_obras_mg": "Escritório BH / MG (Obras Públicas e Infra)",
        "pncp_mod_5": "Progen Planway & Infraestrutura (Pregões/Obras)",
        "debentures_infra": "Planway, Energia & Saneamento (Lei 12.431)",
        "ibama_sislic": "Engenharia Consultiva & Ambiental (LP / LI)",
        "cimm_investimentos": "Progen Manutenção & Industrial (Fábricas)",
    }
    for src, cnt, aci, cap_bi in fontes_rows[:10]:
        f_rows.append([src, fmt_int(cnt), fmt_int(aci), f"R$ {cap_bi:,.2f} bi".replace(",", "X").replace(".", ",").replace("X", "."), vert_map.get(src, "Multi-vertical")])
    story.append(make_table(f_rows, [38 * mm, 16 * mm, 20 * mm, 30 * mm, 76 * mm]))
    story.append(Spacer(1, 5))

    story.append(Paragraph("2.2 Estratégia de Entrada por Fase da Obra (fase_obra)", s["SecHead"]))
    fase_desc = {
        "1_ANUNCIO_LICITACAO_LP": "Anúncio / Licitação / LP — Entrada antecipada para Engenharia Consultiva, EVTE e especificação técnica.",
        "2_NAO_INICIADA_INICIAL": "Não Iniciada / Inicial — Orçamento de CAPEX, EPCM e pré-qualificação antes da contratação principal.",
        "3_LI_LIBERADA_CANTEIRO": "LI Liberada / Canteiro — Gatilho imediato de mobilização, montagem eletromecânica e compras.",
        "4_EM_EXECUCAO_ANDAMENTO": "Em Execução — Gerenciamento de campo, fiscalização, comissionamento e contratos de manutenção.",
        "5_FINANCIAMENTO_ATIVO": "Financiamento Ativo (BNDES) — Recurso financeiro liberado; reduz risco de atraso e inadimplência.",
    }
    tf_rows = [["Fase Canônica", "Obras", "Como a Progen deve abordar"]]
    for fc, fcnt in fases_rows:
        tf_rows.append([fc, fmt_int(fcnt), fase_desc.get(fc, "")])
    story.append(make_table(tf_rows, [48 * mm, 18 * mm, 114 * mm]))
    story.append(Spacer(1, 5))

    story.append(Paragraph("2.3 Top 10 Estados em Obras Ativas × Presença Regional da Progen", s["SecHead"]))
    uf_rows = [["UF", "Obras Ativas", "Acionáveis", "% Cobertura", "CAPEX Estimado", "Sinergia com Estrutura Progen"]]
    syn_uf = {
        "SP": "Sede Largo do Arouche + redes de distribuição",
        "MG": "Escritório Belo Horizonte + mineração/energia",
        "RJ": "Escritório São Gonçalo + Macaé (O&G)",
        "MA": "Escritório São Luís (Corredor Norte/Vale)",
        "BA": "Polo petroquímico, refino, eólica e bioenergia",
        "RS": "Complexos eólicos, transmissão e indústria",
        "PR": "Papel & celulose, agroindústria e infraestrutura",
    }
    for uf, cnt, aci, cap_bi in top_ufs_obras:
        uf_rows.append([
            uf or "N/D", fmt_int(cnt), fmt_int(aci), f"{aci/cnt*100:.1f}%",
            f"R$ {cap_bi:,.2f} bi".replace(",", "X").replace(".", ",").replace("X", "."),
            syn_uf.get(uf, "Atendimento via filiais / mobilização por contrato"),
        ])
    story.append(make_table(uf_rows, [12 * mm, 22 * mm, 22 * mm, 22 * mm, 30 * mm, 72 * mm]))
    story.append(PageBreak())

    # ==================== PAGINA 4: PILAR 2 - LADO FORNECEDORES ====================
    story.append(Paragraph("3. Pilar 2 (Lado Fornecedores): Suprimentos, Locação &amp; Risco", s["DocTitle"]))
    story.append(HRFlowable(width="100%", thickness=1.5, color=GOLD, spaceAfter=6))
    story.append(Paragraph(
        "Em contratos EPC/EPCM e de manutenção distribuída, a margem ganha na venda pode ser perdida na compra e na mobilização. Em 2024, os custos de <b>locação de máquinas/veículos (+61,3% para R$ 67,6 mi)</b>, <b>manutenção de frotas (+85,6% para R$ 32,8 mi)</b> e <b>serviços de terceiros (R$ 89,3 mi)</b> cresceram muito acima da receita, enquanto os <b>adiantamentos a fornecedores saltaram para R$ 259,4 milhões</b>.",
        s["Body"],
    ))

    story.append(Paragraph("3.1 Base de Fornecedores WiNS nos Setores Críticos da Progen", s["SecHead"]))
    uso_map = {
        "CONSTRUCAO_ESPECIALIZADA": "Terraplanagem, fundações, elétrica, HVAC e montagem em campo.",
        "ENGENHARIA_ARQUITETURA": "Projetos complementares, topografia, ensaios e apoio técnico.",
        "METALURGIA_ESTRUTURAS": "Caldeiraria, estruturas metálicas, suportes e tubulações.",
        "LOCACAO_MAQUINAS_EQUIPAMENTOS": "Guindastes, linha amarela, geradores e containers (R$ 67,6 mi/ano).",
        "INFRAESTRUTURA": "Subcontratação de trechos civis, pavimentação e drenagem.",
        "ENERGIA": "Apoio à Progen Energia em redes de distribuição e subestações.",
        "SANEAMENTO": "Obras hidráulicas, adutoras, estações e utilidades.",
    }
    sf_rows = [["Setor Consolidado", "CNPJs na Base", "Médio/Grande Porte", "Uso Direto em Suprimentos & Expediting"]]
    for sec, cnt, mg in setores_forn:
        sf_rows.append([sec, fmt_int(cnt), fmt_int(mg), uso_map.get(sec, "")])
    story.append(make_table(sf_rows, [48 * mm, 26 * mm, 30 * mm, 76 * mm]))
    story.append(Spacer(1, 5))

    story.append(Paragraph("3.2 Cobertura nas Praças com Sede, Escritórios ou Alta Demanda Progen", s["SecHead"]))
    pf_rows = [["UF", "Fornecedores nos 7 Setores", "Com E-mail / Telefone", "% Acionável", "Ganho Operacional"]]
    ganho_uf = {
        "SP": "Concorrência imediata em locação e montagem na capital e interior.",
        "MG": "Rede local para mineração, energia e obras em BH/Lafaiete.",
        "PR": "Apoio a projetos de celulose, agroindústria e infraestrutura.",
        "RJ": "Base para São Gonçalo, Macaé e projetos de óleo & gás/energia.",
        "RS": "Fornecedores locais para eólicas, subestações e indústria.",
        "BA": "Suporte para polo de Camaçari, refino e renováveis.",
        "MA": "Rede regional para escritório de São Luís e logística Norte.",
    }
    for uf, cnt, aci in pracas_forn:
        pf_rows.append([uf, fmt_int(cnt), fmt_int(aci), f"{aci/cnt*100:.1f}%", ganho_uf.get(uf, "")])
    story.append(make_table(pf_rows, [14 * mm, 38 * mm, 36 * mm, 22 * mm, 70 * mm]))
    story.append(Spacer(1, 5))

    story.append(Paragraph("3.3 Protocolo Prático para Blindar os R$ 259,4 mi em Adiantamentos", s["SecHead"]))
    story.append(Paragraph("• <b>Trava de Porte e Capital Social:</b> antes de aprovar adiantamento ou pacote crítico, Suprimentos verifica porte consolidado (Pequena/Média/Grande), capital social e data de abertura diretamente na página de cada fornecedor.", s["BulletItem"]))
    story.append(Paragraph("• <b>Alinhamento ao Código de Conduta de Fornecedores (2025):</b> pré-triagem automática de CNPJs com situação cadastral ATIVA, evitando empresas recém-criadas ou sem lastro operacional.", s["BulletItem"]))
    story.append(Paragraph("• <b>Cotações Regionais Automatizadas:</b> na página de cada obra do Dashboard, a WiNS já lista os Top 8 fornecedores elegíveis da mesma UF, encurtando o ciclo de cotação e reduzindo custos de mobilização.", s["BulletItem"]))
    story.append(PageBreak())

    # ==================== PAGINA 5: AMOSTRA DE OBRAS + FLUXO DIARIO ====================
    story.append(Paragraph("4. Amostra Real de Oportunidades &amp; Fluxo de Uso na Rotina", s["DocTitle"]))
    story.append(HRFlowable(width="100%", thickness=1.5, color=GOLD, spaceAfter=6))
    story.append(Paragraph(
        "Abaixo estão 8 exemplos reais extraídos hoje do DuckDB WiNS com decisores acionáveis mapeados (o detalhamento completo com contatos nominais de 12 obras segue no <b>Dossiê 06</b>):",
        s["Body"],
    ))
    ob_rows = [["ID WiNS", "Empresa Titular", "UF", "CAPEX", "Fase", "Score", "Dec."]]
    for oid, src, emp, uf, cap, aci, fase, sc in sample_obras:
        ob_rows.append([oid, (emp or "")[:40], uf or "—", fmt_capex(cap), fase, str(sc), str(aci)])
    story.append(make_table(ob_rows, [28 * mm, 52 * mm, 10 * mm, 24 * mm, 40 * mm, 13 * mm, 13 * mm]))
    story.append(Spacer(1, 6))

    story.append(Paragraph("4.1 Como Cada Área da Progen Usa a Ferramenta no Dia a Dia", s["SecHead"]))
    uso_areas = [
        ["Área na Progen", "Recursos Usados na Plataforma WiNS", "Resultado Esperado"],
        ["Diretoria Comercial &amp; Novos Negócios", "Aba Alertas &amp; Radar BVMI + Filtro por Lead Score (>= 75) e Fase (LP / Financiamento).", "Foco diário apenas nas obras novas de maior margem e menor risco de crédito."],
        ["Progen Energia S.A.", "Filtro por fonte aneel_transmissao (756) e aneel_siga (2.215) + Decisores Únicos.", "Prospecção ativa em concessionárias de transmissão e geradoras com cronograma 2026–2028."],
        ["Engenharia, EPCM &amp; Valpro", "Dossiês PDF sob demanda (gerar_dossie_cliente.py) + Botão 'Copiar Abordagem'.", "Preparação rápida de reuniões técnicas com histórico de CAPEX, CNPJ e decisores."],
        ["Suprimentos, Compras &amp; Expediting", "Aba Fornecedores (4,09M CNPJs) + Top Fornecedores na página da Obra + Filtro Porte/Capital.", "Ampliação de base homologada por UF/CNAE, redução de custo de locação e trava em adiantamentos."],
        ["Gestão de Carteira / PMO Comercial", "Mini-CRM integrado (Novo / Em Contato / Proposta / Descartado) + Exportação CSV/Excel.", "Zero retrabalho comercial entre escritórios (SP, BH, São Luís, RJ) e filiais."],
    ]
    story.append(make_table(uso_areas, [42 * mm, 68 * mm, 70 * mm]))
    story.append(PageBreak())

    # ==================== PAGINA 6: GOVERNANCA, CONTATOS E PILOTO ====================
    story.append(Paragraph("5. Qualidade de Dados, Interlocutores Mapeados &amp; Plano de Piloto", s["DocTitle"]))
    story.append(HRFlowable(width="100%", thickness=1.5, color=GOLD, spaceAfter=6))

    story.append(Paragraph("5.1 Rigor Técnico e Higiene Contínua (Zero Dados Inventados)", s["SecHead"]))
    story.append(Paragraph("• <b>Telefones:</b> todos os números passam por validação estrutural via biblioteca oficial <b>google/libphonenumber</b>.", s["BulletItem"]))
    story.append(Paragraph("• <b>E-mails Corporativos:</b> checagem de DNS MX ativo e auditoria SMTP, sem geração sintética não verificada.", s["BulletItem"]))
    story.append(Paragraph("• <b>LinkedIn &amp; QSA Oficial:</b> higienização contra perfis genéricos/truncados e enriquecimento contínuo de sócios PF na Receita Federal.", s["BulletItem"]))
    story.append(Paragraph("• <b>Atualização Incremental:</b> pipeline diário automatizado com detecção de mudança de fase e histórico de alertas.", s["BulletItem"]))

    story.append(Paragraph("5.2 Interlocutores Estratégicos Confirmados na Progen S.A. (Abordagem)", s["SecHead"]))
    cont_rows = [
        ["Frente", "Nome", "Cargo Confirmado", "Praça", "Papel na Reunião / Piloto"],
        ["Comercial", "Rafael Stella", "Diretor de Negócios", "São Paulo/SP", "Patrocinador executivo (Pilar 1 + visão geral)."],
        ["Comercial", "Yuri Marques", "Gerente Comercial Sênior (Energia e Infra)", "Brasil", "Validação imediata dos 756 projetos SIGET + CVM."],
        ["Comercial", "Claudia Mello", "Gerente Comercial", "São Paulo/SP", "Adoção no pipeline de Engenharia e Gerenciamento."],
        ["Suprimentos", "Rafael Depierri", "Gerente de Suprimentos", "Brasil", "Líder para o Pilar 2 (4,09M fornecedores e locação)."],
        ["Suprimentos", "Roberta Moulatlet", "Coordenadora de Suprimentos", "São Paulo/SP", "Operação diária de sourcing e homologação."],
        ["Suprimentos", "Marco Turolla", "Gerente de Projetos/Suprimentos", "Campinas/SP", "Integração Suprimentos × Projetos no interior de SP."],
        ["Operações", "Luiz Dias", "Gerente Geral de Operação", "São Paulo/SP", "Visão de mobilização e capacidade em campo."],
        ["Engenharia", "Rita Lacroce", "Gerente de Engenharia", "São Paulo/SP", "Aderência técnica para projetos conceituais e EPCM."],
    ]
    story.append(make_table(cont_rows, [22 * mm, 34 * mm, 50 * mm, 24 * mm, 50 * mm]))
    story.append(Spacer(1, 6))

    story.append(Paragraph("5.3 Plano de Piloto de 30 Dias (Duas Frentes Simultâneas)", s["SecHead"]))
    pil_rows = [
        ["Período", "Frente Comercial (Clientes / Margem)", "Frente Suprimentos (Fornecedores / Risco)"],
        ["Semana 1", "Apresentação de 20 min com Diretoria Comercial + entrega do Dossiê 06 (12 obras) e acesso ao Dashboard.", "Mapeamento dos CNAEs críticos (locação de máquinas, montagem, caldeiraria, frotas) por filial."],
        ["Semana 2", "Abordagem ativa aos decisores validados (Energia, EPCM e Saneamento) com registro no Mini-CRM.", "Entrega de listas regionais homologáveis nas praças SP, MG, RJ, MA, BA, PR e RS."],
        ["Semana 3", "Entrega do boletim semanal de mudanças de fase (LP → LI/Execução) e novas emissões CVM/SIGET.", "Teste de checagem cadastral (porte/capital social) em novas contratações com adiantamento."],
        ["Semana 4", "Apuração de ROI comercial (reuniões agendadas e propostas abertas) e fechamento do escopo anual.", "Apuração de ganho de agilidade/custo em cotações locais e integração contínua com Suprimentos."],
    ]
    story.append(make_table(pil_rows, [22 * mm, 79 * mm, 79 * mm]))

    doc.build(story, onFirstPage=draw_cover, onLaterPages=draw_later)
    print(f"PDF completo gerado: {OUT_PDF} ({os.path.getsize(OUT_PDF)/1024:.1f} KB)")


if __name__ == "__main__":
    main()
