import os
import duckdb
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
    PageBreak,
    HRFlowable,
)

BASE_DIR = r"C:\Users\kbadmin\Documents\Projetos\01_Ecossistema_WiNS\Engenharia"
MAIN_DB = os.path.join(BASE_DIR, "Banco_Dados", "wins_engenharia.duckdb")
OUT_DIR = os.path.join(BASE_DIR, "Entregas")
os.makedirs(OUT_DIR, exist_ok=True)

PDF_ANALISE = os.path.join(OUT_DIR, "01_Analise_Executiva_Riteke_WiNS.pdf")
PDF_OBRAS = os.path.join(OUT_DIR, "02_Mapeamento_10_Obras_Riteke_WiNS.pdf")

NAVY = colors.HexColor("#0F172A")
BLUE = colors.HexColor("#1D4ED8")
SLATE = colors.HexColor("#475569")
LIGHT_BG = colors.HexColor("#F8FAFC")
BORDER = colors.HexColor("#CBD5E1")
ACCENT_BG = colors.HexColor("#EFF6FF")

TARGET_IDS = [
    ("UTE.FL.MS.074134-5.1", "Papel & Celulose / Termelétrica Biomassa — aderência máxima ao núcleo histórico da Riteke (caldeiras, tubulações de vapor, montagem eletromecânica e estruturas metálicas)."),
    ("UTE.GN.RJ.033721-8.1", "Óleo & Gás / Termelétrica (Petrobras — cliente já exibido pela Riteke). Demanda pesada de montagem eletromecânica, tubulações de alta pressão, caldeiraria e gestão de paradas."),
    ("BNDES-25204031", "Bioenergia / Usina de Etanol (R$ 600M). Escopo direto para fabricação/montagem de tanques, reservatórios metálicos, caldeiraria pesada, tubulações de processo e EPCMV."),
    ("BNDES-26200151", "Bioenergia / Usina de Etanol (R$ 500M). Projeto greenfield com alta necessidade de montagem eletromecânica, estruturas metálicas, alinhamento a laser e locação de canteiro."),
    ("BNDES-26200911", "Biorrefinaria / Químico & Petroquímico (R$ 477,7M). Exige conformidade NR-10/NR-12/NR-13, vasos de pressão, tanques, tubulações industriais e comissionamento."),
    ("BNDES-26201431", "Manufatura Industrial / Retrofit & Modernização (R$ 300M). Aderente aos pilares de Reforma/Retrofit de equipamentos, dispositivos industriais, pórticos e montagem."),
    ("BNDES-26200651", "Sucroalcooleiro / Planta de Etanol de Milho (R$ 250M). Grande volume de caldeiraria, silos/tanques metálicos, tubulações e engenharia eletromecânica."),
    ("BNDES-25901911", "Químico / Planta de Biodiesel (R$ 54M). Escopo típico para tanques metálicos, caldeiras, tubulações industriais e montagem eletromecânica completa."),
    ("BNDES-26900721", "Agroindustrial / 5 Silos de Armazenagem (R$ 30M). Aderente a estruturas metálicas, caldeiraria pesada, pórticos, transportadores e montagem em campo."),
    ("BNDES-24800601", "Energia & Vapor Industrial em SP (ComBio — cliente já exibido no site da Riteke). Proximidade operacional em SP para caldeiras, biomassa, manutenção e paradas."),
]


def build_styles():
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="DocTitle", fontName="Helvetica-Bold", fontSize=19, leading=23, textColor=NAVY, spaceAfter=4))
    styles.add(ParagraphStyle(name="DocSub", fontName="Helvetica", fontSize=10, leading=14, textColor=SLATE, spaceAfter=10))
    styles.add(ParagraphStyle(name="SecHead", fontName="Helvetica-Bold", fontSize=12.5, leading=16, textColor=BLUE, spaceBefore=10, spaceAfter=5))
    styles.add(ParagraphStyle(name="Body", fontName="Helvetica", fontSize=9.3, leading=13.5, textColor=NAVY, spaceAfter=4))
    styles.add(ParagraphStyle(name="BulletItem", fontName="Helvetica", fontSize=9.1, leading=13, textColor=NAVY, leftIndent=10, spaceAfter=3))
    styles.add(ParagraphStyle(name="SmallCell", fontName="Helvetica", fontSize=8.0, leading=10.5, textColor=NAVY))
    styles.add(ParagraphStyle(name="SmallBold", fontName="Helvetica-Bold", fontSize=8.0, leading=10.5, textColor=NAVY))
    styles.add(ParagraphStyle(name="Meta", fontName="Helvetica", fontSize=8.2, leading=11, textColor=SLATE))
    return styles


def fmt_capex(val):
    if val is None:
        return "N/D"
    if val >= 1e9:
        return f"R$ {val/1e9:,.2f} bi".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"R$ {val/1e6:,.2f} mi".replace(",", "X").replace(".", ",").replace("X", ".")


def clean_str(v):
    return str(v).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;") if v is not None else "—"


def generate_analysis_pdf(styles, con):
    doc = SimpleDocTemplate(PDF_ANALISE, pagesize=A4, leftMargin=16*mm, rightMargin=16*mm, topMargin=15*mm, bottomMargin=15*mm)
    story = []

    story.append(Paragraph("ANÁLISE EXECUTIVA — RITEKE SOLUÇÕES INDUSTRIAIS", styles["DocTitle"]))
    story.append(Paragraph("Cruzamento do Dossiê Corporativo (riteke.com.br) com a Base WiNS Engenharia (DuckDB)", styles["DocSub"]))
    story.append(HRFlowable(width="100%", thickness=1.5, color=BLUE, spaceAfter=8))

    # Card resumo
    kpis = [
        ["CNPJs Ativos", "09.511.000/0001-20 (2008) e 44.406.211/0001-02 (2021) — Mogi Guaçu/SP"],
        ["Enquadramento / Capital", "ME (R$ 1,0M + R$ 300k declarados) | Sócio-Adm.: Adriana da Conceição Silva"],
        ["Presença no DuckDB WiNS", "Indexada em fornecedores (44.406.211/0001-02, CNAE 3311200, Porte PEQUENA)"],
        ["Canais Oficiais", "comercial@riteke.com.br | contato@riteke.com.br | WhatsApp (19) 99794-3261 / 3361-1217"],
    ]
    t = Table([[Paragraph(f"<b>{k}</b>", styles["SmallBold"]), Paragraph(clean_str(v), styles["SmallCell"])] for k, v in kpis], colWidths=[48*mm, 130*mm])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), LIGHT_BG),
        ("BOX", (0, 0), (-1, -1), 0.6, BORDER),
        ("INNERGRID", (0, 0), (-1, -1), 0.4, BORDER),
        ("PADDING", (0, 0), (-1, -1), 5),
    ]))
    story.append(t)
    story.append(Spacer(1, 6))

    story.append(Paragraph("1. Quem é a Riteke na prática", styles["SecHead"]))
    story.append(Paragraph("• Empresa especializada em <b>engenharia eletromecânica, caldeiraria pesada, fabricação/retrofit de equipamentos, montagem industrial, paradas programadas (shutdowns) e locação de equipamentos/containers</b>, com 18 anos de histórico.", styles["BulletItem"]))
    story.append(Paragraph("• Apesar do enquadramento cadastral ME, exibe atendimento a clientes <b>Tier-1</b> (Petrobras, Suzano, Klabin, Sylvamo, Ingredion, ComBio) e grandes OEMs (<b>Andritz, Valmet, Metso</b>), perfil típico de empreiteira técnica de confiança em plantas contínuas.", styles["BulletItem"]))

    story.append(Paragraph("2. Encaixe Estratégico no Ecossistema WiNS Engenharia", styles["SecHead"]))
    story.append(Paragraph("• <b>Papel principal — ICP Cliente da WiNS (maior valor):</b> a Riteke vende serviços eletromecânicos, EPCMV e paradas para grandes projetos industriais. As obras ativas 2026–2027 do banco WiNS são exatamente o mercado comprador dela.", styles["BulletItem"]))

    # Cruzamento real DuckDB
    cl_rows = []
    for cl in ["PETROBRAS", "ARAUCO", "COMBIO"]:
        c, cap = con.execute("SELECT COUNT(DISTINCT id_externo), COALESCE(SUM(capex_estimado), 0) FROM obras_oficiais_ativas WHERE UPPER(obra_empresa) LIKE ?", [f"%{cl}%"]).fetchone()
        cl_rows.append([cl, f"{c} obras ativas", fmt_capex(cap)])
    story.append(Paragraph("• <b>Aderência direta comprovada no DuckDB WiNS:</b>", styles["BulletItem"]))
    tc = Table([["Empresa / Vertical no WiNS", "Obras Ativas", "CAPEX Mapeado"]] + cl_rows, colWidths=[70*mm, 45*mm, 63*mm])
    tc.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("BOX", (0, 0), (-1, -1), 0.6, BORDER),
        ("INNERGRID", (0, 0), (-1, -1), 0.4, BORDER),
        ("PADDING", (0, 0), (-1, -1), 5),
    ]))
    story.append(tc)
    story.append(Spacer(1, 4))
    story.append(Paragraph("• <b>Papel secundário — Compradora/Subcontratante:</b> em contratos EPCMV e Preço Global, demanda subempreiteiros de montagem, içamento, andaimes, consumíveis de solda, END e EPIs.", styles["BulletItem"]))

    story.append(Paragraph("3. Pontos Fortes vs. Riscos e Lacunas", styles["SecHead"]))
    story.append(Paragraph("• <b>Pontos Fortes:</b> 18 anos de operação, conformidade declarada (CREA, NR-10/12/13, LGPD), zero passivo relevante em Reclame Aqui e oferta ponta a ponta.", styles["BulletItem"]))
    story.append(Paragraph("• <b>Risco Financeiro / Porte:</b> capital social somado de R$ 1,3M (ME) para contratos de grande porte — validar capacidade financeira, apólices e atuação via subcontratação de OEMs.", styles["BulletItem"]))
    story.append(Paragraph("• <b>Lacuna de Prova Pública:</b> site exibe logos sem estudos de caso ou métricas (tonelagem, HHT sem acidentes) e sem CATs públicas; exigir Book de Obras/CATs em negociações.", styles["BulletItem"]))
    story.append(Paragraph("• <b>Gargalo Digital:</b> 8 tags &lt;h1&gt; na home, posts demo em inglês (template tombuild) e hero genérico reduzem conversão orgânica B2B.", styles["BulletItem"]))

    story.append(Paragraph("4. Recomendação Imediata de Abordagem Comercial", styles["SecHead"]))
    story.append(Paragraph("Apresentar à Riteke (<b>comercial@riteke.com.br</b> / WhatsApp <b>(19) 99794-3261</b>) um recorte com <b>10 obras ativas 2026–2027</b> de altíssima aderência eletromecânica (detalhadas no Dossiê 02), já com decisores validados de Compras, Engenharia e Diretoria.", styles["Body"]))

    doc.build(story)


def generate_obras_pdf(styles, con):
    doc = SimpleDocTemplate(PDF_OBRAS, pagesize=A4, leftMargin=14*mm, rightMargin=14*mm, topMargin=14*mm, bottomMargin=14*mm)
    story = []

    story.append(Paragraph("PORTFÓLIO DE 10 OBRAS PARA PROSPECÇÃO — RITEKE", styles["DocTitle"]))
    story.append(Paragraph("Obras ativas 2026–2027 selecionadas no banco WiNS Engenharia com decisores validados e aderência eletromecânica/industrial.", styles["DocSub"]))
    story.append(HRFlowable(width="100%", thickness=1.5, color=BLUE, spaceAfter=8))

    # Tabela resumo inicial
    summary_rows = [["#", "Empresa Titular", "Obra / Projeto", "UF", "CAPEX", "Decisores"]]
    detailed_data = []

    for idx, (id_ext, fit_reason) in enumerate(TARGET_IDS, 1):
        obra = con.execute("""
            SELECT
                o.id_externo, o.fonte, o.obra_nome, o.obra_empresa, o.obra_cnpj,
                o.categoria_macro, o.obra_uf, o.obra_municipio, o.capex_estimado,
                o.capex_tipo, o.data_inicio_prevista, o.data_fim_prevista, o.situacao, o.url_origem,
                d.dominio_corporativo, d.mx_ativo, w.whatsapp_oficial, w.telefones_site
            FROM obras_oficiais_ativas o
            LEFT JOIN empresa_dominios_verificados d ON o.obra_cnpj = d.cnpj
            LEFT JOIN empresa_whatsapp_oficial w ON d.dominio_corporativo = w.dominio
            WHERE o.id_externo = ?
            LIMIT 1
        """, [id_ext]).fetchone()

        decs = con.execute("""
            SELECT decisor_nome, decisor_cargo, perfil_decisor, decisor_email, decisor_telefone, decisor_linkedin, tipo_match
            FROM validacao_decisores_obras_novas
            WHERE id_externo = ? AND is_contato_acionavel = TRUE
            ORDER BY
                CASE perfil_decisor
                    WHEN '1_COMPRADOR_SUPRIMENTOS' THEN 1
                    WHEN '2_ENGENHARIA_OBRAS_CAPEX' THEN 2
                    WHEN '3_DIRETORIA_EXECUTIVA' THEN 3
                    ELSE 4
                END,
                (decisor_linkedin IS NOT NULL) DESC,
                (decisor_email IS NOT NULL) DESC
            LIMIT 6
        """, [id_ext]).fetchall()

        summary_rows.append([
            str(idx),
            Paragraph(clean_str(obra[3]), styles["SmallCell"]),
            Paragraph(clean_str(obra[2][:60]), styles["SmallCell"]),
            clean_str(obra[6]),
            fmt_capex(obra[8]),
            str(len(decs)),
        ])
        detailed_data.append((idx, obra, fit_reason, decs))

    tsum = Table(summary_rows, colWidths=[8*mm, 52*mm, 62*mm, 12*mm, 26*mm, 22*mm])
    tsum.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8.0),
        ("BOX", (0, 0), (-1, -1), 0.6, BORDER),
        ("INNERGRID", (0, 0), (-1, -1), 0.4, BORDER),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("PADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(tsum)
    story.append(PageBreak())

    # Detalhamento minucioso de cada obra
    for idx, obra, fit_reason, decs in detailed_data:
        (
            id_ext, fonte, nome, emp, cnpj, cat, uf, mun, capex, cap_tipo,
            dt_ini, dt_fim, sit, url_orig, dom, mx_ok, wa_of, tel_site
        ) = obra

        story.append(Paragraph(f"OBRA #{idx:02d} — {clean_str(emp)}", styles["SecHead"]))
        story.append(Paragraph(f"<b>Projeto:</b> {clean_str(nome)}", styles["Body"]))

        meta_rows = [
            ["ID Externo / Fonte", f"{clean_str(id_ext)} ({clean_str(fonte)})", "CNPJ Titular", clean_str(cnpj)],
            ["Localização", f"{clean_str(mun)} / {clean_str(uf)}", "Categoria Macro", clean_str(cat)],
            ["CAPEX / Tipo", f"{fmt_capex(capex)} ({clean_str(cap_tipo)})", "Vigência / Status", f"{clean_str(dt_ini)} a {clean_str(dt_fim)} | {clean_str(sit)}"],
            ["Domínio / MX", f"{clean_str(dom)} (MX={'Ativo' if mx_ok else 'N/D'})", "WhatsApp / Tel. Site", f"{clean_str(wa_of)} | {clean_str(tel_site)}"],
        ]
        tmeta = Table(
            [[Paragraph(f"<b>{r[0]}</b>", styles["SmallBold"]), Paragraph(r[1], styles["SmallCell"]),
              Paragraph(f"<b>{r[2]}</b>", styles["SmallBold"]), Paragraph(r[3], styles["SmallCell"])] for r in meta_rows],
            colWidths=[32*mm, 62*mm, 32*mm, 56*mm]
        )
        tmeta.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), LIGHT_BG),
            ("BOX", (0, 0), (-1, -1), 0.6, BORDER),
            ("INNERGRID", (0, 0), (-1, -1), 0.4, BORDER),
            ("PADDING", (0, 0), (-1, -1), 4),
        ]))
        story.append(tmeta)
        story.append(Spacer(1, 3))
        story.append(Paragraph(f"<b>Por que ofertar à Riteke:</b> {clean_str(fit_reason)}", styles["Body"]))
        story.append(Paragraph(f"<b>Fonte Oficial:</b> {clean_str(url_orig)}", styles["Meta"]))
        story.append(Spacer(1, 3))

        dec_rows = [["Nome do Decisor", "Cargo / Área", "E-mail", "Telefone", "LinkedIn"]]
        for d in decs:
            d_nome, d_cargo, d_perf, d_em, d_tel, d_lk, d_match = d
            dec_rows.append([
                Paragraph(clean_str(d_nome), styles["SmallBold"]),
                Paragraph(clean_str(d_cargo), styles["SmallCell"]),
                Paragraph(clean_str(d_em), styles["SmallCell"]),
                Paragraph(clean_str(d_tel), styles["SmallCell"]),
                Paragraph(clean_str(d_lk), styles["SmallCell"]),
            ])

        tdec = Table(dec_rows, colWidths=[34*mm, 44*mm, 38*mm, 24*mm, 42*mm])
        tdec.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), BLUE),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 7.5),
            ("BOX", (0, 0), (-1, -1), 0.6, BORDER),
            ("INNERGRID", (0, 0), (-1, -1), 0.4, BORDER),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("PADDING", (0, 0), (-1, -1), 3.5),
        ]))
        story.append(tdec)
        story.append(Spacer(1, 8))
        if idx % 2 == 0 and idx < len(detailed_data):
            story.append(PageBreak())

    doc.build(story)


def main():
    con = duckdb.connect(MAIN_DB, read_only=True)
    styles = build_styles()
    generate_analysis_pdf(styles, con)
    generate_obras_pdf(styles, con)
    con.close()
    print(f"PDF 1 gerado: {PDF_ANALISE} ({os.path.getsize(PDF_ANALISE)/1024:.1f} KB)")
    print(f"PDF 2 gerado: {PDF_OBRAS} ({os.path.getsize(PDF_OBRAS)/1024:.1f} KB)")


if __name__ == "__main__":
    main()
