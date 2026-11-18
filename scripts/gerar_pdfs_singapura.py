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

PDF_ANALISE = os.path.join(OUT_DIR, "03_Analise_Executiva_Singapura_WiNS.pdf")
PDF_OBRAS = os.path.join(OUT_DIR, "04_Mapeamento_10_Obras_Singapura_WiNS.pdf")

NAVY = colors.HexColor("#0F172A")
WINE = colors.HexColor("#6D1D33")
BLUE = colors.HexColor("#1D4ED8")
SLATE = colors.HexColor("#475569")
LIGHT_BG = colors.HexColor("#F8FAFC")
BORDER = colors.HexColor("#CBD5E1")

TARGET_IDS = [
    ("CONVISAO-52993", "Indústria Farmacêutica em MG (R$ 330M). Fit cirúrgico com os cases da Singapura em Salas Limpas, HVAC, Água PW, Boiler e Solda Orbital (Beiersdorf, Libbs, ACG Capsules e CEITEC)."),
    ("BNDES-26201791", "Construção de Planta de Biometano em SP (R$ 373,4M). Escopo idêntico ao case Onebio / EDGE + Orizon executado pela Singapura em Paulínia-SP (BoP, tubulações inox e elétrica MT/BT)."),
    ("BNDES-25204051", "Modernização das 3 Plantas de Sinterização UPV em Volta Redonda-RJ (R$ 625,8M). A CSN já é cliente ativa da Singapura em Volta Redonda (substituição de gás de coqueria 24\")."),
    ("CONVISAO-44026", "Modernização de plantas industriais da CBA em SP (R$ 715,9M). Aderência direta ao portfólio pesado de Siderurgia/Metalurgia (Gerdau, CSN), estruturas metálicas, utilidades e montagem."),
    ("CIMM-27879", "Investimento nas fábricas da Cummins em SP (R$ 600M). Proximidade geográfica (eixo Campinas/Guarulhos-SP) para civil industrial, montagem mecânica, elétrica e automação."),
    ("CIMM-27817", "Expansão das operações da Hitachi Energy em SP (R$ 385M). Aderente ao pilar de Instalações Elétricas, CDCs/CCMs, automação CLP/SCADA Siemens e civil industrial."),
    ("CONVISAO-54043", "Modernização de fábrica da Nestlé em SP (R$ 540M). Vertical alimentícia com demanda de tubulações sanitárias em inox (solda orbital), Central CIP, HVAC e utilidades."),
    ("UTE.GN.SP.076200-8.1", "Usina UTE Cocal Biometano NRD em SP (R$ 22,5M). Mesmo nicho de biogás/biometano e energia em SP já comprovado pela Singapura nos cases Onebio/Orizon e Raízen/Amyris."),
    ("UTE.GN.RJ.033721-8.1", "Usina UTE Comperj da Petrobras no RJ (R$ 1.156,9M). Projeto de grande porte em Óleo & Gás/Energia aderente a tubulações, vasos, elétrica, instrumentação e comissionamento."),
    ("BNDES-26200911", "Construção de Biorrefinaria da Acelen na BA (R$ 477,7M). Segmento Químico/Petroquímico com forte demanda de spools, tanques, tubulações especiais, Fire & Gas e comissionamento (como Chevron e Oxiteno)."),
]


def build_styles():
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="DocTitle", fontName="Helvetica-Bold", fontSize=18, leading=22, textColor=NAVY, spaceAfter=4))
    styles.add(ParagraphStyle(name="DocSub", fontName="Helvetica", fontSize=9.8, leading=13.5, textColor=SLATE, spaceAfter=8))
    styles.add(ParagraphStyle(name="SecHead", fontName="Helvetica-Bold", fontSize=12, leading=15, textColor=WINE, spaceBefore=9, spaceAfter=4))
    styles.add(ParagraphStyle(name="Body", fontName="Helvetica", fontSize=9.1, leading=13, textColor=NAVY, spaceAfter=4))
    styles.add(ParagraphStyle(name="BulletItem", fontName="Helvetica", fontSize=8.9, leading=12.5, textColor=NAVY, leftIndent=10, spaceAfter=2.5))
    styles.add(ParagraphStyle(name="SmallCell", fontName="Helvetica", fontSize=7.9, leading=10.2, textColor=NAVY))
    styles.add(ParagraphStyle(name="SmallBold", fontName="Helvetica-Bold", fontSize=7.9, leading=10.2, textColor=NAVY))
    styles.add(ParagraphStyle(name="Meta", fontName="Helvetica", fontSize=8.0, leading=10.5, textColor=SLATE))
    return styles


def fmt_capex(val):
    if val is None or val == 0:
        return "N/D"
    if val >= 1e9:
        return f"R$ {val/1e9:,.2f} bi".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"R$ {val/1e6:,.2f} mi".replace(",", "X").replace(".", ",").replace("X", ".")


def clean_str(v):
    return str(v).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;") if v is not None and str(v).strip() != "" else "—"


def generate_analysis_pdf(styles, con):
    doc = SimpleDocTemplate(PDF_ANALISE, pagesize=A4, leftMargin=15*mm, rightMargin=15*mm, topMargin=14*mm, bottomMargin=14*mm)
    story = []

    story.append(Paragraph("ANÁLISE EXECUTIVA — SINGAPURA CONSTRUÇÃO E MONTAGENS", styles["DocTitle"]))
    story.append(Paragraph("Dossiê Consolidado: Site (singapura.eng.br), Portfólio Institucional (39 págs.), Automação SCADA e DuckDB WiNS", styles["DocSub"]))
    story.append(HRFlowable(width="100%", thickness=1.5, color=WINE, spaceAfter=8))

    kpis = [
        ["CNPJ / Cadastro WiNS", "37.960.189/0001-74 (Ativa desde 04/08/2020) — indexada em fornecedores (CNAE 4292-8/02, Porte DEMAIS, Cap. Social R$ 1,0M)"],
        ["Sede Operacional", "Rua José Gallo, 320, Vista Alegre, Vinhedo – SP (CEP 13285-332) | IE 714.145.527.113 | IM 23706"],
        ["Diretoria & Contatos", "João Batista da Silva Filho (Dir. Negócios): joao.batista@singapura.eng.br | (11) 94734-9098\nAndré Zanatta da Silva (Dir. Gestão/Tec.): andre.zanatta@singapura.eng.br | (11) 99646-5186"],
        ["Orçamentos / Geral", "orcamentos@singapura.eng.br | (11) 91435-2549 | (11) 93310-1299"],
    ]
    t = Table([[Paragraph(f"<b>{k}</b>", styles["SmallBold"]), Paragraph(clean_str(v).replace("\n", "<br/>"), styles["SmallCell"])] for k, v in kpis], colWidths=[44*mm, 136*mm])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), LIGHT_BG),
        ("BOX", (0, 0), (-1, -1), 0.6, BORDER),
        ("INNERGRID", (0, 0), (-1, -1), 0.4, BORDER),
        ("PADDING", (0, 0), (-1, -1), 5),
    ]))
    story.append(t)
    story.append(Spacer(1, 5))

    story.append(Paragraph("1. Origem, Lastro e Porte Real de Operação", styles["SecHead"]))
    story.append(Paragraph("• <b>Cisão da JPA Engenharia (35+ anos):</b> herda acervo técnico de grande porte e premiação entre as <b>20 melhores empresas nacionais</b> do segmento pela revista <i>O Empreiteiro</i> (2 anos consecutivos).", styles["BulletItem"]))
    story.append(Paragraph("• <b>Governança e Operação (2026):</b> opera com dashboards próprios de Suprimentos (R$ 6,0 mi+ em pedidos visíveis no OPR), RH (~178 colaboradores simultâneos em múltiplas frentes) e apresentações semanais de planejamento (One Page Report).", styles["BulletItem"]))
    story.append(Paragraph("• <b>Prêmios de Segurança e Qualidade:</b> Troféu <b>Beiersdorf SHE&amp;S (+100 mil horas sem acidentes)</b> e Placa de Excelência em Itatiba (jul/2024).", styles["BulletItem"]))

    story.append(Paragraph("2. Diferenciais Técnicos vs. Concorrentes Médios", styles["SecHead"]))
    story.append(Paragraph("• <b>Multidisciplinaridade real:</b> Civil Industrial (fundações, bases, pipe racks, bacias) + Montagem Mecânica/Tubulações + Elétrica/Instrumentação + Comissionamento (elétrico, instrumentação e mecânico).", styles["BulletItem"]))
    story.append(Paragraph("• <b>Especialidades de alta barreira:</b> Salas Limpas (isopainéis + HVAC), <b>solda orbital para linhas de ultra-pureza</b>, execução padrão <b>LEED Gold</b>, trepanação, alpinismo industrial (até 35,9m) e integração com <b>Automação CLP/SCADA Siemens</b> (S7-1500, S7-400H, S7-300 Fail-Safety, WinCC, iFIX, ESD e Central CIP).", styles["BulletItem"]))

    story.append(Paragraph("3. Obras Comprovadas em Campo (Portfólio + Web)", styles["SecHead"]))
    cases = [
        ["Farma / Cosméticos / Tech", "Beiersdorf (Itatiba-SP: LIP, Footprint, Wave I LEED Gold), Libbs (Embu-SP: Salas Limpas, Água PW, Pipe Rack), ACG (Pouso Alegre-MG), CEITEC (POA-RS: ultra-pureza), CNPEM/LNLS (Campinas-SP: Sirius), Cimed, Janssen, L'Occitane."],
        ["Química / O&G / Biometano", "Onebio/EDGE + Orizon (Paulínia-SP: Purificação Biogás/Biometano), Chevron Oronite (Mauá-SP), Oxiteno (Mauá/Tremembé-SP), Amyris/Raízen (Barra Bonita-SP), Ultragaz (BA/SP)."],
        ["Siderurgia / Papel / Infra", "CSN (Volta Redonda-RJ: gás coqueria 24\"), Gerdau (Pinda/SJC/Araçariguama-SP), Klabin (Piracicaba-SP), CJ do Brasil (Piracicaba-SP), Dexco (SP/Jundiaí-SP), Embraer (Hangar KC-390), GRU Airport (TPS-3)."],
    ]
    tcases = Table([[Paragraph(f"<b>{k}</b>", styles["SmallBold"]), Paragraph(clean_str(v), styles["SmallCell"])] for k, v in cases], colWidths=[48*mm, 132*mm])
    tcases.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), LIGHT_BG),
        ("BOX", (0, 0), (-1, -1), 0.6, BORDER),
        ("INNERGRID", (0, 0), (-1, -1), 0.4, BORDER),
        ("PADDING", (0, 0), (-1, -1), 5),
    ]))
    story.append(tcases)

    story.append(Paragraph("4. Pontos de Atenção & Oportunidade WiNS", styles["SecHead"]))
    story.append(Paragraph("• <b>Site em Wix subdimensiona a empresa:</b> URLs semânticas quebradas (/cópia-projeto-7) e cases apenas em imagens sem texto indexável — o PDF institucional mostra um porte técnico muito superior ao site.", styles["BulletItem"]))
    story.append(Paragraph("• <b>Abordagem recomendada:</b> enviar diretamente a <b>João Batista da Silva Filho</b> (joao.batista@singapura.eng.br) e <b>André Zanatta</b> (andre.zanatta@singapura.eng.br) o Dossiê 04 com as <b>10 obras ativas de altíssimo fit</b> em Farma, Biometano, Siderurgia, Químico e Manufatura no eixo SP/RJ/MG/BA.", styles["BulletItem"]))

    doc.build(story)


def generate_obras_pdf(styles, con):
    doc = SimpleDocTemplate(PDF_OBRAS, pagesize=A4, leftMargin=14*mm, rightMargin=14*mm, topMargin=14*mm, bottomMargin=14*mm)
    story = []

    story.append(Paragraph("PORTFÓLIO DE 10 OBRAS SOB MEDIDA — SINGAPURA", styles["DocTitle"]))
    story.append(Paragraph("Obras ativas 2026–2027 selecionadas no DuckDB WiNS por aderência técnica direta aos cases de Farma, Biometano, Siderurgia, Química e Manufatura da Singapura.", styles["DocSub"]))
    story.append(HRFlowable(width="100%", thickness=1.5, color=WINE, spaceAfter=8))

    summary_rows = [["#", "Empresa Titular", "Obra / Projeto", "UF", "CAPEX", "Decisores"]]
    detailed_data = []

    for idx, (id_ext, fit_reason) in enumerate(TARGET_IDS, 1):
        obra = con.execute("""
            SELECT
                o.obra_id, o.fonte, o.obra_nome, o.obra_empresa, o.obra_cnpj,
                o.categoria_macro, o.obra_uf, o.obra_municipio, o.capex_estimado,
                o.capex_tipo, o.data_inicio_prevista, o.data_fim_prevista, o.situacao, o.url_origem,
                o.dominio_corporativo, o.mx_ativo, o.whatsapp_oficial, o.telefones_site, o.fase_obra
            FROM todas_obras_consolidadas o
            WHERE o.obra_id = ?
            LIMIT 1
        """, [id_ext]).fetchone()

        decs = con.execute("""
            SELECT decisor_nome, decisor_cargo, perfil_decisor, decisor_email, decisor_telefone, decisor_linkedin, tipo_match
            FROM validacao_decisores_obras_novas
            WHERE id_externo = ? AND is_contato_acionavel = TRUE
            ORDER BY
                CASE perfil_decisor
                    WHEN '1_COMPRADOR_SUPRIMENTOS' THEN 1
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
            Paragraph(clean_str(obra[3]), styles["SmallCell"]),
            Paragraph(clean_str(obra[2][:58]), styles["SmallCell"]),
            clean_str(obra[6]),
            fmt_capex(obra[8]),
            str(len(decs)),
        ])
        detailed_data.append((idx, obra, fit_reason, decs))

    tsum = Table(summary_rows, colWidths=[8*mm, 52*mm, 62*mm, 12*mm, 26*mm, 22*mm])
    tsum.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), WINE),
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

    for idx, obra, fit_reason, decs in detailed_data:
        (
            id_ext, fonte, nome, emp, cnpj, cat, uf, mun, capex, cap_tipo,
            dt_ini, dt_fim, sit, url_orig, dom, mx_ok, wa_of, tel_site, fase
        ) = obra

        story.append(Paragraph(f"OBRA #{idx:02d} — {clean_str(emp)}", styles["SecHead"]))
        story.append(Paragraph(f"<b>Projeto:</b> {clean_str(nome)}", styles["Body"]))

        meta_rows = [
            ["ID / Fonte", f"{clean_str(id_ext)} ({clean_str(fonte)})", "CNPJ Titular", clean_str(cnpj)],
            ["Localização", f"{clean_str(mun)} / {clean_str(uf)}", "Fase / Status", f"{clean_str(fase)} | {clean_str(sit)}"],
            ["CAPEX / Tipo", f"{fmt_capex(capex)} ({clean_str(cap_tipo)})", "Vigência", f"{clean_str(dt_ini)} a {clean_str(dt_fim)}"],
            ["Domínio / MX", f"{clean_str(dom)} (MX={'Ativo' if mx_ok else 'N/D'})", "WhatsApp / Tel. Site", f"{clean_str(wa_of)} | {clean_str(tel_site)}"],
        ]
        tmeta = Table(
            [[Paragraph(f"<b>{r[0]}</b>", styles["SmallBold"]), Paragraph(r[1], styles["SmallCell"]),
              Paragraph(f"<b>{r[2]}</b>", styles["SmallBold"]), Paragraph(r[3], styles["SmallCell"])] for r in meta_rows],
            colWidths=[30*mm, 64*mm, 30*mm, 58*mm]
        )
        tmeta.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), LIGHT_BG),
            ("BOX", (0, 0), (-1, -1), 0.6, BORDER),
            ("INNERGRID", (0, 0), (-1, -1), 0.4, BORDER),
            ("PADDING", (0, 0), (-1, -1), 4),
        ]))
        story.append(tmeta)
        story.append(Spacer(1, 3))
        story.append(Paragraph(f"<b>Por que ofertar à Singapura:</b> {clean_str(fit_reason)}", styles["Body"]))
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
            ("BACKGROUND", (0, 0), (-1, 0), WINE),
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
    print(f"PDF 3 gerado: {PDF_ANALISE} ({os.path.getsize(PDF_ANALISE)/1024:.1f} KB)")
    print(f"PDF 4 gerado: {PDF_OBRAS} ({os.path.getsize(PDF_OBRAS)/1024:.1f} KB)")


if __name__ == "__main__":
    main()
