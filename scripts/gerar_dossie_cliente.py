import argparse
import os
import re
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

NAVY = colors.HexColor("#0F172A")
BLUE = colors.HexColor("#1D4ED8")
SLATE = colors.HexColor("#475569")
LIGHT_BG = colors.HexColor("#F8FAFC")
BORDER = colors.HexColor("#CBD5E1")


def build_styles():
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="DocTitle", fontName="Helvetica-Bold", fontSize=18, leading=22, textColor=NAVY, spaceAfter=4))
    styles.add(ParagraphStyle(name="DocSub", fontName="Helvetica", fontSize=9.5, leading=13, textColor=SLATE, spaceAfter=8))
    styles.add(ParagraphStyle(name="SecHead", fontName="Helvetica-Bold", fontSize=12, leading=15, textColor=BLUE, spaceBefore=8, spaceAfter=4))
    styles.add(ParagraphStyle(name="Body", fontName="Helvetica", fontSize=9.0, leading=13, textColor=NAVY, spaceAfter=4))
    styles.add(ParagraphStyle(name="SmallCell", fontName="Helvetica", fontSize=7.8, leading=10, textColor=NAVY))
    styles.add(ParagraphStyle(name="SmallBold", fontName="Helvetica-Bold", fontSize=7.8, leading=10, textColor=NAVY))
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


def slugify(text: str) -> str:
    s = re.sub(r"[^A-Za-z0-9]+", "_", text.strip())
    return s.strip("_") or "Cliente"


def main():
    parser = argparse.ArgumentParser(description="Gerador Parametrizado de Dossies Executivos WiNS Engenharia")
    parser.add_argument("--cliente", required=True, help="Nome do cliente/empresa alvo do dossie")
    parser.add_argument("--uf", default="", help="Filtrar por UFs separadas por virgula (ex: SP,MG,PR)")
    parser.add_argument("--categoria", default="", help="Filtrar por trecho da categoria_macro (ex: INDUSTRIAL, ENERGIA)")
    parser.add_argument("--fase", default="", help="Filtrar por trecho de fase_obra (ex: 3_LI, 4_EM_EXECUCAO)")
    parser.add_argument("--min-capex", type=float, default=0.0, help="CAPEX minimo em reais")
    parser.add_argument("--min-score", type=int, default=50, help="Score de prioridade minimo (0-100)")
    parser.add_argument("--top", type=int, default=10, help="Quantidade de obras no dossie (padrao: 10)")
    parser.add_argument("--out-file", default="", help="Caminho de saida opcional do PDF")
    args = parser.parse_args()

    os.makedirs(OUT_DIR, exist_ok=True)
    out_pdf = args.out_file or os.path.join(OUT_DIR, f"Dossie_Prospeccao_{slugify(args.cliente)}_WiNS.pdf")

    where = ["COALESCE(decisores_acionaveis, 0) > 0", f"COALESCE(score_prioridade, 0) >= {int(args.min_score)}"]
    params = []

    if args.uf:
        ufs = [u.strip().upper() for u in args.uf.split(",") if u.strip()]
        if ufs:
            placeholders = ",".join("?" for _ in ufs)
            where.append(f"UPPER(obra_uf) IN ({placeholders})")
            params.extend(ufs)
    if args.categoria:
        where.append("UPPER(COALESCE(categoria_macro, '')) LIKE ?")
        params.append(f"%{args.categoria.strip().upper()}%")
    if args.fase:
        where.append("UPPER(COALESCE(fase_obra, '')) LIKE ?")
        params.append(f"%{args.fase.strip().upper()}%")
    if args.min_capex > 0:
        where.append("COALESCE(capex_estimado, 0) >= ?")
        params.append(args.min_capex)

    sql = f"""
        SELECT
            obra_id, fonte, obra_nome, obra_empresa, obra_cnpj,
            categoria_macro, obra_uf, obra_municipio, capex_estimado,
            capex_tipo, data_inicio_prevista, data_fim_prevista, situacao,
            url_origem, dominio_corporativo, mx_ativo, whatsapp_oficial,
            telefones_site, fase_obra, COALESCE(score_prioridade, 0) AS score_prioridade
        FROM todas_obras_consolidadas
        WHERE {' AND '.join(where)}
        ORDER BY score_prioridade DESC, COALESCE(capex_estimado, 0) DESC, decisores_operacionais DESC
        LIMIT ?
    """
    params.append(int(args.top))

    con = duckdb.connect(MAIN_DB, read_only=True)
    obras = con.execute(sql, params).fetchall()
    if not obras:
        con.close()
        raise SystemExit("Nenhuma obra encontrada para os filtros informados.")

    styles = build_styles()
    doc = SimpleDocTemplate(out_pdf, pagesize=A4, leftMargin=14 * mm, rightMargin=14 * mm, topMargin=14 * mm, bottomMargin=14 * mm)
    story = []

    filtros_txt = (
        f"UF: {args.uf or 'Todas'} | Categoria: {args.categoria or 'Todas'} | "
        f"Fase: {args.fase or 'Todas'} | Score >= {args.min_score}"
    )
    story.append(Paragraph(f"DOSSIÊ DE PROSPECÇÃO — {clean_str(args.cliente.upper())}", styles["DocTitle"]))
    story.append(Paragraph(f"Top {len(obras)} obras ranqueadas por Score WiNS ({clean_str(filtros_txt)})", styles["DocSub"]))
    story.append(HRFlowable(width="100%", thickness=1.5, color=BLUE, spaceAfter=8))

    summary_rows = [["#", "Score", "Empresa Titular", "Obra / Projeto", "UF", "CAPEX", "Fase"]]
    detailed = []
    for idx, obra in enumerate(obras, 1):
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
                (decisor_email IS NOT NULL) DESC,
                (decisor_linkedin IS NOT NULL) DESC
            LIMIT 6
        """, [obra[0]]).fetchall()

        summary_rows.append([
            str(idx),
            str(obra[19]),
            Paragraph(clean_str(obra[3]), styles["SmallCell"]),
            Paragraph(clean_str((obra[2] or "")[:55]), styles["SmallCell"]),
            clean_str(obra[6]),
            fmt_capex(obra[8]),
            Paragraph(clean_str(obra[18]), styles["SmallCell"]),
        ])
        detailed.append((idx, obra, decs))

    tsum = Table(summary_rows, colWidths=[7 * mm, 12 * mm, 44 * mm, 54 * mm, 10 * mm, 24 * mm, 31 * mm])
    tsum.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 7.8),
        ("BOX", (0, 0), (-1, -1), 0.6, BORDER),
        ("INNERGRID", (0, 0), (-1, -1), 0.4, BORDER),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("PADDING", (0, 0), (-1, -1), 3.5),
    ]))
    story.append(tsum)
    story.append(PageBreak())

    for idx, obra, decs in detailed:
        (
            obra_id, fonte, nome, emp, cnpj, cat, uf, mun, capex, cap_tipo,
            dt_ini, dt_fim, sit, url_orig, dom, mx_ok, wa_of, tel_site, fase, score
        ) = obra

        story.append(Paragraph(f"OBRA #{idx:02d} (Score {score}/100) — {clean_str(emp)}", styles["SecHead"]))
        story.append(Paragraph(f"<b>Projeto:</b> {clean_str(nome)}", styles["Body"]))

        meta_rows = [
            ["ID / Fonte", f"{clean_str(obra_id)} ({clean_str(fonte)})", "CNPJ", clean_str(cnpj)],
            ["Localização", f"{clean_str(mun)} / {clean_str(uf)}", "Fase / Categoria", f"{clean_str(fase)} | {clean_str(cat)}"],
            ["CAPEX / Tipo", f"{fmt_capex(capex)} ({clean_str(cap_tipo)})", "Vigência / Situação", f"{clean_str(dt_ini)} a {clean_str(dt_fim)} | {clean_str(sit)}"],
            ["Domínio / MX", f"{clean_str(dom)} (MX={'Ativo' if mx_ok else 'N/D'})", "WhatsApp / Tel. Site", f"{clean_str(wa_of)} | {clean_str(tel_site)}"],
        ]
        tmeta = Table(
            [[Paragraph(f"<b>{r[0]}</b>", styles["SmallBold"]), Paragraph(r[1], styles["SmallCell"]),
              Paragraph(f"<b>{r[2]}</b>", styles["SmallBold"]), Paragraph(r[3], styles["SmallCell"])] for r in meta_rows],
            colWidths=[28 * mm, 64 * mm, 32 * mm, 58 * mm],
        )
        tmeta.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), LIGHT_BG),
            ("BOX", (0, 0), (-1, -1), 0.6, BORDER),
            ("INNERGRID", (0, 0), (-1, -1), 0.4, BORDER),
            ("PADDING", (0, 0), (-1, -1), 3.5),
        ]))
        story.append(tmeta)
        story.append(Paragraph(f"<b>Fonte Oficial:</b> {clean_str(url_orig)}", styles["Meta"]))
        story.append(Spacer(1, 3))

        dec_rows = [["Nome", "Cargo", "E-mail", "Telefone", "LinkedIn"]]
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
            ("BACKGROUND", (0, 0), (-1, 0), BLUE),
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
        if idx % 2 == 0 and idx < len(detailed):
            story.append(PageBreak())

    con.close()
    doc.build(story)
    print(f"Dossie gerado com {len(obras)} obras: {out_pdf} ({os.path.getsize(out_pdf)/1024:.1f} KB)")


if __name__ == "__main__":
    main()
