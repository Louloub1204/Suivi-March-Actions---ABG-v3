"""PDF Analytics Report — Drivers de performance par action — CGF GESTION.

Action-centric perspective:
  - Which stocks drove P&L (positive and negative)
  - How each stock's move propagated across FCPs
  - Sector-level P&L attribution
  - Per-FCP decomposition of daily variation

Style: White + CGF Blue (#004977) institutional.
"""
from __future__ import annotations

import io
from pathlib import Path

import pandas as pd
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    HRFlowable,
    Image,
    NextPageTemplate,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)

# ---------------------------------------------------------------------------
# Palette
# ---------------------------------------------------------------------------
BLUE       = colors.HexColor("#004977")
BLUE_LIGHT = colors.HexColor("#E6EFF5")
BLUE_MID   = colors.HexColor("#C2D8E8")
BLUE_DARK  = colors.HexColor("#002F4D")
WHITE      = colors.white
GREY_LIGHT = colors.HexColor("#F5F7FA")
BLACK      = colors.HexColor("#1A1A2E")
GREEN      = colors.HexColor("#1A6B3E")
GREEN_BG   = colors.HexColor("#E8F5EE")
RED        = colors.HexColor("#B53A2F")
RED_BG     = colors.HexColor("#FAEAEA")

W, H = A4

LOGO_PATH = Path(__file__).resolve().parent / "seed_data" / "cgf_logo.png"
INST1 = "Compagnie Générale de Finance et de Gestion S.A."
INST2 = ("Société de gestion collective au capital de 500 000 000 FCFA"
         "  ·  N° agrément CREPMF SG-003/2001")


# ---------------------------------------------------------------------------
# Number helpers
# ---------------------------------------------------------------------------
def _xof(v, signed: bool = False) -> str:
    try:
        v = float(v)
    except (TypeError, ValueError):
        return "-"
    if v != v:
        return "-"
    if abs(v) >= 1_000_000_000:
        s = f"{v/1_000_000_000:.2f} Md"
    elif abs(v) >= 1_000_000:
        s = f"{v/1_000_000:.1f} M"
    else:
        s = f"{int(round(v)):,}".replace(",", " ")
    return (f"+{s}" if signed and v > 0 else s)


def _pct(v, signed: bool = False) -> str:
    try:
        v = float(v)
    except (TypeError, ValueError):
        return "-"
    if v != v:
        return "-"
    s = f"{v * 100:.2f}%"
    return (f"+{s}" if signed and v > 0 else s)


def _arrow(v) -> str:
    try:
        v = float(v)
        return "▲" if v > 0 else ("▼" if v < 0 else "—")
    except (TypeError, ValueError):
        return "—"


# ---------------------------------------------------------------------------
# Styles
# ---------------------------------------------------------------------------
def _styles() -> dict:
    return {
        "inst1": ParagraphStyle("inst1", fontName="Helvetica-Bold",
                                fontSize=9, textColor=BLUE_DARK,
                                alignment=TA_CENTER, spaceAfter=2),
        "inst2": ParagraphStyle("inst2", fontName="Helvetica",
                                fontSize=7.5,
                                textColor=colors.HexColor("#4A6A7D"),
                                alignment=TA_CENTER),
        "cover_title": ParagraphStyle("cover_title",
                                      fontName="Helvetica-Bold",
                                      fontSize=20, textColor=WHITE,
                                      alignment=TA_CENTER, spaceAfter=6),
        "cover_sub": ParagraphStyle("cover_sub", fontName="Helvetica",
                                    fontSize=11,
                                    textColor=colors.HexColor("#B8D4E8"),
                                    alignment=TA_CENTER, spaceAfter=4),
        "section": ParagraphStyle("section", fontName="Helvetica-Bold",
                                  fontSize=11, textColor=BLUE,
                                  spaceBefore=8, spaceAfter=4),
        "sub": ParagraphStyle("sub", fontName="Helvetica-Bold",
                               fontSize=9, textColor=BLUE_DARK,
                               spaceBefore=6, spaceAfter=3),
        "body": ParagraphStyle("body", fontName="Helvetica",
                                fontSize=8, textColor=BLACK,
                                leading=12, spaceAfter=3),
        "caption": ParagraphStyle("caption", fontName="Helvetica-Oblique",
                                  fontSize=7,
                                  textColor=colors.HexColor("#6A8A9D"),
                                  alignment=TA_CENTER, spaceAfter=2),
        "kpi_val": ParagraphStyle("kpi_val", fontName="Helvetica-Bold",
                                  fontSize=14, textColor=WHITE,
                                  alignment=TA_CENTER),
        "kpi_lbl": ParagraphStyle("kpi_lbl", fontName="Helvetica",
                                  fontSize=6.5,
                                  textColor=colors.HexColor("#B8D4E8"),
                                  alignment=TA_CENTER),
    }


# ---------------------------------------------------------------------------
# Page templates
# ---------------------------------------------------------------------------
def _build_doc(buf: io.BytesIO) -> BaseDocTemplate:
    doc = BaseDocTemplate(buf, pagesize=A4,
                          leftMargin=1.6*cm, rightMargin=1.6*cm,
                          topMargin=1.0*cm, bottomMargin=1.6*cm)

    def _cover_bg(c, d):
        c.saveState()
        c.setFillColor(BLUE); c.rect(0, 0, W, H, fill=1, stroke=0)
        c.setFillColor(WHITE); c.rect(0, H-3.6*cm, W, 3.6*cm, fill=1, stroke=0)
        c.setFillColor(BLUE_MID); c.rect(0, H-3.7*cm, W, .12*cm, fill=1, stroke=0)
        c.setFillColor(BLUE_DARK); c.rect(0, 0, W, 1.1*cm, fill=1, stroke=0)
        c.setFont("Helvetica", 6.5)
        c.setFillColor(colors.HexColor("#6A9ABD"))
        c.drawCentredString(W/2, .38*cm,
                            "Document confidentiel — Usage interne uniquement")
        c.restoreState()

    def _page_bg(c, d):
        c.saveState()
        c.setFillColor(WHITE); c.rect(0, 0, W, H, fill=1, stroke=0)
        c.setFillColor(WHITE); c.rect(0, H-3.0*cm, W, 3.0*cm, fill=1, stroke=0)
        c.setFillColor(BLUE); c.rect(0, H-3.05*cm, W, .18*cm, fill=1, stroke=0)
        c.setFillColor(BLUE_LIGHT); c.rect(0, 0, .35*cm, H-3.1*cm, fill=1, stroke=0)
        c.setFillColor(BLUE); c.rect(0, 0, W, .95*cm, fill=1, stroke=0)
        c.setFont("Helvetica", 6.5)
        c.setFillColor(colors.HexColor("#B8D4E8"))
        c.drawString(1.6*cm, .33*cm, INST1)
        c.drawRightString(W-1.6*cm, .33*cm, f"Page {d.page}")
        c.restoreState()

    cover_f  = Frame(1.6*cm, 1.4*cm, W-3.2*cm, H-4.8*cm, id="cover")
    content_f = Frame(1.8*cm, 1.2*cm, W-3.4*cm, H-4.6*cm, id="content")

    doc.addPageTemplates([
        PageTemplate(id="cover",   frames=[cover_f],   onPage=_cover_bg),
        PageTemplate(id="content", frames=[content_f], onPage=_page_bg),
    ])
    return doc


# ---------------------------------------------------------------------------
# Reusable header block
# ---------------------------------------------------------------------------
def _header(styles: dict) -> list:
    items = []
    if LOGO_PATH.exists():
        lw, lh = 170, int(170 * 60 / 911)
        img = Image(str(LOGO_PATH), width=lw, height=lh)
        img.hAlign = "CENTER"
        items.append(img)
        items.append(Spacer(1, 3))
    items.append(Paragraph(INST1, styles["inst1"]))
    items.append(Paragraph(INST2, styles["inst2"]))
    return items


# ---------------------------------------------------------------------------
# Standard table style helper
# ---------------------------------------------------------------------------
def _base_ts(header_bg=None, col_w=None) -> list:
    hb = header_bg or BLUE
    ht = WHITE if hb == BLUE else BLUE
    return [
        ("BACKGROUND",    (0, 0), (-1, 0), hb),
        ("TEXTCOLOR",     (0, 0), (-1, 0), ht),
        ("FONTNAME",      (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE",      (0, 0), (-1, -1), 7.5),
        ("TOPPADDING",    (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("ALIGN",         (0, 0), (0, -1), "LEFT"),
        ("ALIGN",         (1, 0), (-1, -1), "RIGHT"),
        ("ROWBACKGROUNDS",(0, 1), (-1, -1), [WHITE, BLUE_LIGHT]),
        ("LINEBELOW",     (0, 0), (-1, 0), 1.2, BLUE),
        ("LINEBELOW",     (0, 1), (-1, -2), 0.3, BLUE_MID),
        ("BOX",           (0, 0), (-1, -1), 0.5, BLUE_MID),
        ("TEXTCOLOR",     (0, 1), (-1, -1), BLACK),
    ]


# ---------------------------------------------------------------------------
# Cover page
# ---------------------------------------------------------------------------
def _cover(as_of, total_pnl, total_valo, n_movers, n_fcps, styles):
    s = styles
    items = _header(s)
    items.append(Spacer(1, 2.2*cm))
    items.append(Paragraph("RAPPORT ANALYTICS", s["cover_title"]))
    items.append(Paragraph(
        "Analyse des Drivers de Performance — Actions BRVM",
        s["cover_sub"],
    ))
    items.append(Paragraph(
        f"Séance du {pd.Timestamp(as_of).strftime('%d %B %Y').upper()}",
        s["cover_sub"],
    ))
    items.append(Spacer(1, 0.8*cm))

    c_pnl = colors.HexColor("#90EE90") if total_pnl >= 0 \
            else colors.HexColor("#FF9999")
    kpi_data = [
        [
            Paragraph(_xof(total_valo), s["kpi_val"]),
            Paragraph(_xof(total_pnl, signed=True),
                      ParagraphStyle("kv", parent=s["kpi_val"],
                                     textColor=c_pnl)),
            Paragraph(str(n_movers), s["kpi_val"]),
            Paragraph(str(n_fcps), s["kpi_val"]),
        ],
        [
            Paragraph("Valorisation globale (FCFA)", s["kpi_lbl"]),
            Paragraph("P&L journalier (FCFA)", s["kpi_lbl"]),
            Paragraph("Actions ayant bougé", s["kpi_lbl"]),
            Paragraph("FCPs impactés", s["kpi_lbl"]),
        ],
    ]
    kpi_tbl = Table(kpi_data,
                    colWidths=[(W-3.2*cm)/4]*4,
                    rowHeights=[1.2*cm, .5*cm])
    kpi_tbl.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, -1), BLUE_DARK),
        ("BOX",           (0, 0), (-1, -1), 1, colors.HexColor("#6A9ABD")),
        ("LINEAFTER",     (0, 0), (2, 1),   .5, colors.HexColor("#1A5070")),
        ("TOPPADDING",    (0, 0), (-1, -1), 10),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
    ]))
    items.append(kpi_tbl)
    items.append(NextPageTemplate("content"))
    items.append(PageBreak())
    return items


# ---------------------------------------------------------------------------
# Section 1 — Top drivers (positive + negative)
# ---------------------------------------------------------------------------
def _drivers_section(by_ticker: pd.DataFrame, styles: dict) -> list:
    items = _header(styles)
    items.append(Spacer(1, .25*cm))
    items.append(Paragraph(
        "1. Actions ayant drivé la performance du jour",
        styles["section"],
    ))
    items.append(HRFlowable(width="100%", thickness=1.5,
                             color=BLUE, spaceAfter=4))
    items.append(Paragraph(
        "Classement par contribution au P&L global. "
        "La contribution = Σ (quantités détenues × variation de cours) "
        "sur l'ensemble des FCPs exposés à ce titre.",
        styles["body"],
    ))
    items.append(Spacer(1, .2*cm))

    # Positive drivers
    items.append(Paragraph("Principaux drivers positifs", styles["sub"]))
    pos = by_ticker[by_ticker["pnl_total"] > 0].head(10)
    items.append(_drivers_table(pos, positive=True))

    items.append(Spacer(1, .3*cm))
    items.append(Paragraph("Principaux drivers négatifs", styles["sub"]))
    neg = by_ticker[by_ticker["pnl_total"] < 0].tail(10)
    items.append(_drivers_table(neg, positive=False))

    return items


def _drivers_table(df: pd.DataFrame, positive: bool) -> Table:
    accent = GREEN if positive else RED
    accent_bg = GREEN_BG if positive else RED_BG

    headers = [
        "Symbole", "Variation cours", "Cours veille",
        "Cours jour", "Qté totale", "Contribution P&L",
        "FCPs exposés",
    ]
    col_w = [2.0*cm, 2.4*cm, 2.4*cm, 2.4*cm, 2.2*cm, 3.2*cm, 1.8*cm]
    rows = [headers]
    style_cmds = _base_ts()
    style_cmds += [
        ("ALIGN", (4, 0), (5, -1), "RIGHT"),
        ("ALIGN", (6, 0), (6, -1), "CENTER"),
    ]

    if df.empty:
        rows.append(["Aucun", "-", "-", "-", "-", "-", "-"])
    else:
        for i, (_, r) in enumerate(df.iterrows(), 1):
            vunit = float(r.get("variation_unit", 0) or 0)
            pnl   = float(r.get("pnl_total", 0) or 0)
            rows.append([
                r["ticker"],
                f"{_arrow(vunit)} {_xof(vunit, signed=True)} FCFA",
                _xof(r.get("close_prev")),
                _xof(r.get("close_today")),
                f"{r.get('qty_total', 0):,.0f}".replace(",", " "),
                _xof(pnl, signed=True),
                str(int(r.get("n_fcps", 1))),
            ])
            bg = accent_bg if i % 2 == 0 else WHITE
            style_cmds += [
                ("BACKGROUND", (0, i), (-1, i), bg),
                ("TEXTCOLOR",  (1, i), (1,  i), accent),
                ("FONTNAME",   (1, i), (1,  i), "Helvetica-Bold"),
                ("TEXTCOLOR",  (5, i), (5,  i), accent),
                ("FONTNAME",   (5, i), (5,  i), "Helvetica-Bold"),
            ]

    tbl = Table(rows, colWidths=col_w, repeatRows=1)
    tbl.setStyle(TableStyle(style_cmds))
    return tbl


# ---------------------------------------------------------------------------
# Section 2 — Action → FCP contribution matrix
# ---------------------------------------------------------------------------
def _action_fcp_section(drivers: pd.DataFrame,
                        by_ticker: pd.DataFrame,
                        styles: dict) -> list:
    items = []
    items.append(Spacer(1, .3*cm))
    items.append(Paragraph(
        "2. Propagation par FCP — Contribution action → portefeuille",
        styles["section"],
    ))
    items.append(HRFlowable(width="100%", thickness=1.5,
                             color=BLUE, spaceAfter=4))
    items.append(Paragraph(
        "Pour chaque action significative, détail de la contribution "
        "au P&L de chaque FCP exposé (en FCFA et en % du P&L du FCP).",
        styles["body"],
    ))
    items.append(Spacer(1, .2*cm))

    # Keep top 10 movers by absolute P&L
    top_tickers = (
        by_ticker.assign(_abs=by_ticker["pnl_total"].abs())
        .nlargest(10, "_abs")["ticker"]
        .tolist()
    )

    for ticker in top_tickers:
        rows_t = drivers[drivers["ticker"] == ticker].copy()
        rows_t = rows_t[rows_t["pnl_total"] != 0].sort_values(
            "pnl_total", ascending=False
        )
        if rows_t.empty:
            continue

        vunit = float(rows_t["variation_unit"].iloc[0])
        total_pnl_ticker = float(rows_t["pnl_total"].sum())
        c = GREEN if total_pnl_ticker >= 0 else RED

        items.append(Paragraph(
            f"● {ticker}   —   "
            f"Variation : {_arrow(vunit)} {_xof(vunit, signed=True)} FCFA   |   "
            f"Contribution totale : {_xof(total_pnl_ticker, signed=True)} FCFA",
            ParagraphStyle("th", parent=styles["sub"],
                           textColor=c, spaceBefore=5),
        ))

        tbl_data = [["FCP", "Qté détenue", "P&L FCFA", "% du P&L du FCP"]]
        ts = _base_ts(header_bg=BLUE_LIGHT)
        for j, (_, rr) in enumerate(rows_t.iterrows(), 1):
            pnl_r = float(rr["pnl_total"])
            pnl_fcp_pct = float(rr.get("pnl_pct_of_fcp", 0) or 0)
            tbl_data.append([
                rr["fcp"],
                f"{rr['qty_now']:,.0f}".replace(",", " "),
                _xof(pnl_r, signed=True),
                _pct(pnl_fcp_pct, signed=True),
            ])
            c_row = GREEN if pnl_r >= 0 else RED
            ts += [
                ("TEXTCOLOR", (2, j), (3, j), c_row),
                ("FONTNAME",  (2, j), (3, j), "Helvetica-Bold"),
            ]

        cw = [7*cm, 2.8*cm, 3.5*cm, 2.7*cm]
        tbl = Table(tbl_data, colWidths=cw)
        tbl.setStyle(TableStyle(ts))
        items.append(tbl)

    return items


# ---------------------------------------------------------------------------
# Section 3 — Sector P&L attribution
# ---------------------------------------------------------------------------
def _sector_section(drivers: pd.DataFrame,
                    sectors_map: dict[str, str],
                    styles: dict) -> list:
    items = []
    items.append(Spacer(1, .3*cm))
    items.append(Paragraph(
        "3. Contribution sectorielle au P&L",
        styles["section"],
    ))
    items.append(HRFlowable(width="100%", thickness=1.5,
                             color=BLUE, spaceAfter=4))

    df = drivers.copy()
    df["secteur"] = df["ticker"].map(
        lambda t: sectors_map.get(t.strip().upper(), "Non classé")
    )
    sec = (
        df.groupby("secteur")
        .agg(
            pnl_total=("pnl_total", "sum"),
            valo_total=("valo_today", "sum"),
            n_tickers=("ticker", "nunique"),
        )
        .reset_index()
        .sort_values("pnl_total", ascending=False)
    )
    grand_pnl = float(sec["pnl_total"].sum())

    headers = ["Secteur", "P&L (FCFA)", "% du P&L global",
               "Valorisation", "Nb titres"]
    col_w = [6*cm, 3.2*cm, 2.8*cm, 3.5*cm, 1.5*cm]
    rows = [headers]
    ts = _base_ts()
    for i, (_, r) in enumerate(sec.iterrows(), 1):
        pnl_s = float(r["pnl_total"])
        pct_g = pnl_s / grand_pnl if grand_pnl else 0
        rows.append([
            r["secteur"],
            _xof(pnl_s, signed=True),
            _pct(pct_g, signed=True),
            _xof(r["valo_total"]),
            str(int(r["n_tickers"])),
        ])
        c = GREEN if pnl_s >= 0 else RED
        ts += [
            ("TEXTCOLOR", (1, i), (2, i), c),
            ("FONTNAME",  (1, i), (2, i), "Helvetica-Bold"),
        ]

    tbl = Table(rows, colWidths=col_w, repeatRows=1)
    tbl.setStyle(TableStyle(ts))
    items.append(tbl)
    return items


# ---------------------------------------------------------------------------
# Section 4 — Per-FCP decomposition
# ---------------------------------------------------------------------------
def _fcp_decomp_section(drivers: pd.DataFrame, styles: dict) -> list:
    items = []
    items.append(Spacer(1, .3*cm))
    items.append(Paragraph(
        "4. Décomposition du P&L journalier par FCP",
        styles["section"],
    ))
    items.append(HRFlowable(width="100%", thickness=1.5,
                             color=BLUE, spaceAfter=4))
    items.append(Paragraph(
        "Pour chaque FCP, les 3 principales actions ayant contribué "
        "(positivement ou négativement) à la variation du jour.",
        styles["body"],
    ))
    items.append(Spacer(1, .15*cm))

    fcp_pnl = (
        drivers.groupby("fcp")["pnl_total"].sum()
        .sort_values(ascending=False)
    )

    for fcp_name in fcp_pnl.index:
        fcp_rows = (
            drivers[drivers["fcp"] == fcp_name]
            .assign(_abs=lambda d: d["pnl_total"].abs())
            .nlargest(3, "_abs")
        )
        total_fcp = float(fcp_pnl.get(fcp_name, 0))
        c = GREEN if total_fcp >= 0 else RED

        items.append(Paragraph(
            f"{fcp_name}   {_arrow(total_fcp)}  "
            f"{_xof(total_fcp, signed=True)} FCFA",
            ParagraphStyle("fb", parent=styles["sub"],
                           textColor=c, spaceBefore=5),
        ))

        td = [["Titre", "Contribution (FCFA)", "% du P&L du FCP"]]
        ts = _base_ts(header_bg=BLUE_LIGHT)
        for j, (_, r) in enumerate(fcp_rows.iterrows(), 1):
            pnl_r = float(r["pnl_total"])
            pct_r = float(r.get("pnl_pct_of_fcp", 0) or 0)
            td.append([
                r["ticker"],
                _xof(pnl_r, signed=True),
                _pct(pct_r, signed=True),
            ])
            cr = GREEN if pnl_r >= 0 else RED
            ts += [
                ("TEXTCOLOR", (1, j), (2, j), cr),
                ("FONTNAME",  (1, j), (2, j), "Helvetica-Bold"),
            ]
        cw = [5*cm, 5*cm, 5*cm]
        t = Table(td, colWidths=cw,
                  rowHeights=[0.55*cm] * len(td))
        t.setStyle(TableStyle(ts))
        items.append(t)

    return items


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------
def generate_report(
    drivers: pd.DataFrame,
    by_ticker: pd.DataFrame,
    as_of,
    sectors_map: dict[str, str] | None = None,
    recap: pd.DataFrame | None = None,
) -> bytes:
    """Generate the action-centric PDF report.

    Args:
        drivers:     Long DataFrame from portfolio.compute_action_drivers().
        by_ticker:   Aggregated DataFrame from portfolio.aggregate_drivers_by_ticker().
        as_of:       Valuation date.
        sectors_map: Dict {ticker -> sector}. Pass None to skip sector section.
        recap:       Recap DataFrame (used only for cover KPIs if drivers is empty).

    Returns:
        PDF as bytes.
    """
    sectors_map = sectors_map or {}
    as_of_ts = pd.Timestamp(as_of)
    buf = io.BytesIO()
    doc = _build_doc(buf)
    styles = _styles()

    # Cover KPIs
    if not by_ticker.empty:
        total_pnl  = float(by_ticker["pnl_total"].sum())
        total_valo = float(by_ticker["valo_total"].sum())
        n_movers   = int((by_ticker["variation_unit"] != 0).sum())
        n_fcps     = int(drivers["fcp"].nunique()) if not drivers.empty else 0
    elif recap is not None and not recap.empty:
        vj = pd.to_numeric(recap.get("Var. jour", 0), errors="coerce").fillna(0)
        vl = pd.to_numeric(recap.get("Valorisation", 0), errors="coerce").fillna(0)
        total_pnl  = float(vj.sum())
        total_valo = float(vl.sum())
        n_movers   = 0
        n_fcps     = len(recap)
    else:
        total_pnl = total_valo = 0.0
        n_movers = n_fcps = 0

    story: list = []

    story += _cover(as_of_ts, total_pnl, total_valo,
                    n_movers, n_fcps, styles)

    if not by_ticker.empty:
        story += _drivers_section(by_ticker, styles)
        story.append(PageBreak())
        story += _action_fcp_section(drivers, by_ticker, styles)
        if sectors_map:
            story += _sector_section(drivers, sectors_map, styles)
        story.append(PageBreak())
        story += _fcp_decomp_section(drivers, styles)
    else:
        story.append(Paragraph(
            "Aucune donnée de cours disponible pour cette séance.",
            styles["body"],
        ))

    # Footer note
    story.append(Spacer(1, .6*cm))
    story.append(HRFlowable(width="100%", thickness=.5, color=BLUE_MID))
    story.append(Spacer(1, .15*cm))
    story.append(Paragraph(
        f"Rapport généré le {as_of_ts.strftime('%d/%m/%Y')}  ·  "
        "Données BRVM / SharePoint CGF GESTION  ·  "
        "Document confidentiel — usage interne uniquement.",
        styles["caption"],
    ))

    doc.build(story)
    buf.seek(0)
    return buf.read()


# ---------------------------------------------------------------------------
# Attribution PDF report
# ---------------------------------------------------------------------------

def generate_attribution_pdf(
    attr: pd.DataFrame,
    date_debut,
    date_fin,
) -> bytes:
    """Generate a PDF for the performance attribution table.

    `attr` must have columns:
        FCP, Ptf. Actions début, Achats, Ventes,
        Dividendes, Effet marché, Ptf. Actions fin
    The last row should be the TOTAL row.
    """
    d0 = pd.Timestamp(date_debut)
    d1 = pd.Timestamp(date_fin)
    n_days = (d1 - d0).days
    period_label = (
        f"{d0.strftime('%d/%m/%Y')} → {d1.strftime('%d/%m/%Y')} "
        f"({n_days} jours)"
    )

    buf = io.BytesIO()
    doc = _build_doc(buf)
    styles = _styles()

    story: list = []

    # ── Cover ────────────────────────────────────────────────────────────────
    # Compute KPIs from data
    data_rows = attr[attr["FCP"] != "TOTAL"]
    total_row = attr[attr["FCP"] == "TOTAL"]
    ptf_init_total = float(
        total_row["Ptf. Actions début"].iloc[0]
        if not total_row.empty else data_rows["Ptf. Actions début"].sum()
    )
    ptf_fin_total = float(
        total_row["Ptf. Actions fin"].iloc[0]
        if not total_row.empty else data_rows["Ptf. Actions fin"].sum()
    )
    effet_total = float(
        total_row["Effet marché"].iloc[0]
        if not total_row.empty else data_rows["Effet marché"].sum()
    )
    divs_total = float(
        total_row["Dividendes"].iloc[0]
        if not total_row.empty else data_rows["Dividendes"].sum()
    )

    # Simple cover
    story += _header(styles)
    story.append(Spacer(1, 1.5 * cm))
    story.append(Paragraph(
        "RAPPORT D'ATTRIBUTION DE PERFORMANCE", styles["cover_title"]
    ))
    story.append(Paragraph(
        "Décomposition des Fonds Communs de Placement — BRVM",
        styles["cover_sub"],
    ))
    story.append(Paragraph(f"Période : {period_label}", styles["cover_sub"]))
    story.append(Spacer(1, 0.8 * cm))

    kpi_data = [
        [
            Paragraph(_xof(ptf_init_total), styles["kpi_val"]),
            Paragraph(_xof(ptf_fin_total), styles["kpi_val"]),
            Paragraph(
                _xof(effet_total, signed=True),
                ParagraphStyle("kve", parent=styles["kpi_val"],
                               textColor=colors.HexColor("#90EE90")
                               if effet_total >= 0
                               else colors.HexColor("#FF9999")),
            ),
            Paragraph(_xof(divs_total), styles["kpi_val"]),
        ],
        [
            Paragraph("Ptf. initial (FCFA)", styles["kpi_lbl"]),
            Paragraph("Ptf. final (FCFA)", styles["kpi_lbl"]),
            Paragraph("Effet marché (FCFA)", styles["kpi_lbl"]),
            Paragraph("Dividendes perçus (FCFA)", styles["kpi_lbl"]),
        ],
    ]
    kpi_tbl = Table(
        kpi_data,
        colWidths=[(W - 3.2 * cm) / 4] * 4,
        rowHeights=[1.2 * cm, .5 * cm],
    )
    kpi_tbl.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, -1), BLUE_DARK),
        ("BOX",           (0, 0), (-1, -1), 1, colors.HexColor("#6A9ABD")),
        ("LINEAFTER",     (0, 0), (2, 1),   .5, colors.HexColor("#1A5070")),
        ("TOPPADDING",    (0, 0), (-1, -1), 10),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
    ]))
    story.append(kpi_tbl)
    story.append(NextPageTemplate("content"))
    story.append(PageBreak())

    # ── Attribution table ────────────────────────────────────────────────────
    story += _header(styles)
    story.append(Spacer(1, .25 * cm))
    story.append(Paragraph(
        "Tableau d'attribution de performance",
        styles["section"],
    ))
    story.append(HRFlowable(
        width="100%", thickness=1.5, color=BLUE, spaceAfter=4
    ))
    story.append(Paragraph(
        f"Période : {period_label}   ·   "
        "Effet marché = Ptf. fin − Ptf. début − Achats + Ventes − Dividendes",
        styles["body"],
    ))
    story.append(Spacer(1, .2 * cm))

    cols = [
        "FCP",
        "Ptf.\ndébut",
        "Achats",
        "Ventes",
        "Dividendes",
        "Effet\nmarché",
        "Ptf.\nfin",
    ]
    col_w = [5.5*cm, 3.0*cm, 2.8*cm, 2.8*cm, 2.8*cm, 3.0*cm, 3.0*cm]

    headers = cols
    rows = [headers]
    style_cmds = [
        ("BACKGROUND",    (0, 0), (-1, 0), BLUE),
        ("TEXTCOLOR",     (0, 0), (-1, 0), WHITE),
        ("FONTNAME",      (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE",      (0, 0), (-1, -1), 7),
        ("TOPPADDING",    (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("ALIGN",         (1, 0), (-1, -1), "RIGHT"),
        ("ALIGN",         (0, 0), (0, -1), "LEFT"),
        ("ROWBACKGROUNDS",(0, 1), (-1, -2), [WHITE, BLUE_LIGHT]),
        ("LINEBELOW",     (0, 0), (-1, 0), 1.2, BLUE),
        ("BOX",           (0, 0), (-1, -1), .5, BLUE_MID),
    ]

    for i, (_, row) in enumerate(attr.iterrows(), 1):
        is_total = str(row["FCP"]) == "TOTAL"
        effet = float(row.get("Effet marché", 0) or 0)
        c_effet = GREEN if effet >= 0 else RED

        rows.append([
            row["FCP"],
            _xof(row.get("Ptf. Actions début")),
            _xof(row.get("Achats")),
            _xof(row.get("Ventes")),
            _xof(row.get("Dividendes")),
            _xof(effet, signed=True),
            _xof(row.get("Ptf. Actions fin")),
        ])
        style_cmds += [
            ("TEXTCOLOR", (5, i), (5, i), c_effet),
            ("FONTNAME",  (5, i), (5, i), "Helvetica-Bold"),
        ]
        if is_total:
            style_cmds += [
                ("BACKGROUND", (0, i), (-1, i), BLUE_LIGHT),
                ("FONTNAME",   (0, i), (-1, i), "Helvetica-Bold"),
            ]

    tbl = Table(rows, colWidths=col_w, repeatRows=1)
    tbl.setStyle(TableStyle(style_cmds))
    story.append(tbl)

    # Closing note
    story.append(Spacer(1, .6 * cm))
    story.append(HRFlowable(width="100%", thickness=.5, color=BLUE_MID))
    story.append(Spacer(1, .15 * cm))
    story.append(Paragraph(
        f"Rapport généré le {pd.Timestamp.now().strftime('%d/%m/%Y')}  ·  "
        "CGF GESTION  ·  Document confidentiel — usage interne uniquement.",
        styles["caption"],
    ))

    doc.build(story)
    buf.seek(0)
    return buf.read()
