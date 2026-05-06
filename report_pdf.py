"""PDF Analytics Report — Dynamique des FCP — CGF GESTION.

White/blue institutional style. Compact 2-3 pages.
Covers:
  - Cover page with CGF GESTION logo + institutional header + day KPIs
  - Section 1: Full FCP recap table (day metrics)
  - Section 2: P&L catalysts + top contributors
  - Section 3: Period comparison (day vs selected period)
  - Section 4: Momentum & trend analysis
"""
from __future__ import annotations

import io
from pathlib import Path

import pandas as pd
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm, mm
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
# CGF GESTION palette — white & blue
# ---------------------------------------------------------------------------
BLUE        = colors.HexColor("#004977")   # CGF brand blue
BLUE_LIGHT  = colors.HexColor("#E6EFF5")   # light blue tint
BLUE_MID    = colors.HexColor("#C2D8E8")   # mid blue for borders
BLUE_DARK   = colors.HexColor("#002F4D")   # dark blue for text
WHITE       = colors.white
GREY_LIGHT  = colors.HexColor("#F5F7FA")
GREY_MID    = colors.HexColor("#D0D8E0")
BLACK       = colors.HexColor("#1A1A2E")
GREEN       = colors.HexColor("#1A6B3E")
RED         = colors.HexColor("#B53A2F")
GOLD_ACCENT = colors.HexColor("#EF9F27")   # subtle accent for alerts only

W, H = A4

LOGO_PATH = Path(__file__).resolve().parent / "seed_data" / "cgf_logo.png"
INSTITUTION_LINE1 = "Compagnie Générale de Finance et de Gestion S.A."
INSTITUTION_LINE2 = (
    "Société de gestion collective au capital de 500 000 000 FCFA  "
    "·  N° agrément CREPMF SG-003/2001"
)


# ---------------------------------------------------------------------------
# Styles
# ---------------------------------------------------------------------------
def _styles() -> dict:
    return {
        "inst1": ParagraphStyle(
            "inst1",
            fontName="Helvetica-Bold",
            fontSize=9,
            textColor=BLUE_DARK,
            alignment=TA_CENTER,
            spaceAfter=2,
        ),
        "inst2": ParagraphStyle(
            "inst2",
            fontName="Helvetica",
            fontSize=7.5,
            textColor=colors.HexColor("#4A6A7D"),
            alignment=TA_CENTER,
            spaceAfter=0,
        ),
        "cover_title": ParagraphStyle(
            "cover_title",
            fontName="Helvetica-Bold",
            fontSize=20,
            textColor=WHITE,
            alignment=TA_CENTER,
            spaceAfter=6,
        ),
        "cover_sub": ParagraphStyle(
            "cover_sub",
            fontName="Helvetica",
            fontSize=11,
            textColor=colors.HexColor("#B8D4E8"),
            alignment=TA_CENTER,
            spaceAfter=4,
        ),
        "section_title": ParagraphStyle(
            "section_title",
            fontName="Helvetica-Bold",
            fontSize=11,
            textColor=BLUE,
            spaceBefore=10,
            spaceAfter=4,
        ),
        "subsection": ParagraphStyle(
            "subsection",
            fontName="Helvetica-Bold",
            fontSize=9,
            textColor=BLUE_DARK,
            spaceBefore=6,
            spaceAfter=3,
        ),
        "body": ParagraphStyle(
            "body",
            fontName="Helvetica",
            fontSize=8.5,
            textColor=BLACK,
            leading=13,
            spaceAfter=3,
        ),
        "caption": ParagraphStyle(
            "caption",
            fontName="Helvetica-Oblique",
            fontSize=7,
            textColor=colors.HexColor("#6A8A9D"),
            spaceAfter=2,
            alignment=TA_CENTER,
        ),
        "kpi_val": ParagraphStyle(
            "kpi_val",
            fontName="Helvetica-Bold",
            fontSize=15,
            textColor=WHITE,
            alignment=TA_CENTER,
        ),
        "kpi_lbl": ParagraphStyle(
            "kpi_lbl",
            fontName="Helvetica",
            fontSize=6.5,
            textColor=colors.HexColor("#B8D4E8"),
            alignment=TA_CENTER,
        ),
    }


# ---------------------------------------------------------------------------
# Number formatters
# ---------------------------------------------------------------------------
def _xof(v, signed: bool = False) -> str:
    try:
        v = float(v)
    except (TypeError, ValueError):
        return "-"
    if v != v:  # nan
        return "-"
    if abs(v) >= 1_000_000_000:
        s = f"{v/1_000_000_000:,.2f} Md".replace(",", "\u202f")
    elif abs(v) >= 1_000_000:
        s = f"{v/1_000_000:,.1f} M".replace(",", "\u202f")
    else:
        s = f"{v:,.0f}".replace(",", "\u202f")
    if signed and v > 0:
        return f"+{s}"
    return s


def _pct(v, signed: bool = False) -> str:
    try:
        v = float(v)
    except (TypeError, ValueError):
        return "-"
    if v != v:
        return "-"
    s = f"{v * 100:.2f}%"
    if signed and v > 0:
        return f"+{s}"
    return s


# ---------------------------------------------------------------------------
# Page templates
# ---------------------------------------------------------------------------
def _build_doc(buf: io.BytesIO) -> BaseDocTemplate:
    doc = BaseDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=1.6 * cm,
        rightMargin=1.6 * cm,
        topMargin=1.2 * cm,
        bottomMargin=1.8 * cm,
    )

    # ── Cover background ──
    def _cover_bg(canvas, doc):
        canvas.saveState()
        # Full blue background
        canvas.setFillColor(BLUE)
        canvas.rect(0, 0, W, H, fill=1, stroke=0)
        # White header zone for logo
        canvas.setFillColor(WHITE)
        canvas.rect(0, H - 3.8 * cm, W, 3.8 * cm, fill=1, stroke=0)
        # Thin separator line
        canvas.setFillColor(BLUE_MID)
        canvas.rect(0, H - 3.9 * cm, W, 0.15 * cm, fill=1, stroke=0)
        # Bottom light strip
        canvas.setFillColor(BLUE_DARK)
        canvas.rect(0, 0, W, 1.2 * cm, fill=1, stroke=0)
        canvas.setFont("Helvetica", 7)
        canvas.setFillColor(colors.HexColor("#6A9ABD"))
        canvas.drawCentredString(
            W / 2, 0.42 * cm,
            "Document confidentiel — Usage interne uniquement"
        )
        canvas.restoreState()

    # ── Content page background ──
    def _page_bg(canvas, doc):
        canvas.saveState()
        # White background
        canvas.setFillColor(WHITE)
        canvas.rect(0, 0, W, H, fill=1, stroke=0)
        # White header zone
        canvas.setFillColor(WHITE)
        canvas.rect(0, H - 3.2 * cm, W, 3.2 * cm, fill=1, stroke=0)
        # Blue accent line under header
        canvas.setFillColor(BLUE)
        canvas.rect(0, H - 3.25 * cm, W, 0.18 * cm, fill=1, stroke=0)
        # Light blue left margin accent
        canvas.setFillColor(BLUE_LIGHT)
        canvas.rect(0, 0, 0.4 * cm, H - 3.3 * cm, fill=1, stroke=0)
        # Footer
        canvas.setFillColor(BLUE)
        canvas.rect(0, 0, W, 1.0 * cm, fill=1, stroke=0)
        canvas.setFont("Helvetica", 6.5)
        canvas.setFillColor(colors.HexColor("#B8D4E8"))
        canvas.drawString(1.6 * cm, 0.35 * cm,
                          INSTITUTION_LINE1)
        canvas.drawRightString(W - 1.6 * cm, 0.35 * cm,
                               f"Page {doc.page}")
        canvas.restoreState()

    cover_frame = Frame(
        1.6*cm, 1.5*cm, W - 3.2*cm, H - 5*cm,
        id="cover_frame",
    )
    content_frame = Frame(
        1.8*cm, 1.3*cm, W - 3.4*cm, H - 5*cm,
        id="content_frame",
    )

    doc.addPageTemplates([
        PageTemplate(id="cover",   frames=[cover_frame],   onPage=_cover_bg),
        PageTemplate(id="content", frames=[content_frame], onPage=_page_bg),
    ])
    return doc


# ---------------------------------------------------------------------------
# Header block (logo + institution text)
# ---------------------------------------------------------------------------
def _header_block(styles: dict) -> list:
    items = []
    if LOGO_PATH.exists():
        # Logo: scale to ~180pt wide maintaining aspect ratio (911x60)
        logo_w = 180
        logo_h = int(logo_w * 60 / 911)
        logo = Image(str(LOGO_PATH), width=logo_w, height=logo_h)
        logo.hAlign = "CENTER"
        items.append(logo)
        items.append(Spacer(1, 4))
    items.append(Paragraph(INSTITUTION_LINE1, styles["inst1"]))
    items.append(Paragraph(INSTITUTION_LINE2, styles["inst2"]))
    return items


# ---------------------------------------------------------------------------
# Cover page
# ---------------------------------------------------------------------------
def _cover_section(
    as_of,
    period_label: str,
    total_valo: float,
    var_jour: float,
    var_jour_pct: float,
    n_fcps: int,
    styles: dict,
) -> list:
    items = []

    # Header zone (logo on white)
    items += _header_block(styles)
    items.append(Spacer(1, 2.5 * cm))

    # Title
    items.append(Paragraph("RAPPORT ANALYTICS", styles["cover_title"]))
    items.append(Paragraph(
        "Dynamique des Fonds Communs de Placement — BRVM",
        styles["cover_sub"],
    ))
    items.append(Paragraph(
        f"Séance du {pd.Timestamp(as_of).strftime('%d %B %Y').upper()}"
        + (f"  ·  Période : {period_label}" if period_label else ""),
        styles["cover_sub"],
    ))
    items.append(Spacer(1, 1.0 * cm))

    # KPI row
    kpi_data = [
        [
            Paragraph(_xof(total_valo), styles["kpi_val"]),
            Paragraph(
                _xof(var_jour, signed=True),
                ParagraphStyle("kv_j", parent=styles["kpi_val"],
                               textColor=colors.HexColor("#90EE90") if var_jour >= 0
                               else colors.HexColor("#FF9999")),
            ),
            Paragraph(
                _pct(var_jour_pct, signed=True),
                ParagraphStyle("kv_p", parent=styles["kpi_val"],
                               textColor=colors.HexColor("#90EE90") if var_jour >= 0
                               else colors.HexColor("#FF9999")),
            ),
            Paragraph(str(n_fcps), styles["kpi_val"]),
        ],
        [
            Paragraph("Valorisation totale (FCFA)", styles["kpi_lbl"]),
            Paragraph("Variation journalière (FCFA)", styles["kpi_lbl"]),
            Paragraph("Variation journalière (%)", styles["kpi_lbl"]),
            Paragraph("FCPs actifs", styles["kpi_lbl"]),
        ],
    ]
    kpi_tbl = Table(
        kpi_data,
        colWidths=[(W - 3.2 * cm) / 4] * 4,
        rowHeights=[1.3 * cm, 0.5 * cm],
    )
    kpi_tbl.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, -1), BLUE_DARK),
        ("BOX",           (0, 0), (-1, -1), 1, colors.HexColor("#6A9ABD")),
        ("LINEAFTER",     (0, 0), (2, 1),   0.5, colors.HexColor("#1A5070")),
        ("TOPPADDING",    (0, 0), (-1, -1), 10),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
    ]))
    items.append(kpi_tbl)
    items.append(NextPageTemplate("content"))
    items.append(PageBreak())
    return items


# ---------------------------------------------------------------------------
# Section 1 — Recap table
# ---------------------------------------------------------------------------
def _recap_table_section(recap: pd.DataFrame, styles: dict) -> list:
    items = _header_block(styles)
    items.append(Spacer(1, 0.3 * cm))
    items.append(Paragraph(
        "1. Récapitulatif des performances par FCP",
        styles["section_title"],
    ))
    items.append(HRFlowable(
        width="100%", thickness=1.5, color=BLUE, spaceAfter=5
    ))

    headers = [
        "FCP", "Valorisation", "Var. jour", "Var. j %",
        "Var. YTD", "Var. YTD %", "Valo déb. année",
    ]
    col_w = [5.2*cm, 3.0*cm, 2.6*cm, 1.7*cm, 2.6*cm, 1.7*cm, 3.0*cm]

    rows = [headers]
    style_cmds = [
        ("BACKGROUND",    (0, 0), (-1, 0), BLUE),
        ("TEXTCOLOR",     (0, 0), (-1, 0), WHITE),
        ("FONTNAME",      (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE",      (0, 0), (-1, 0), 7.5),
        ("TOPPADDING",    (0, 0), (-1, 0), 5),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 5),
        ("FONTNAME",      (0, 1), (-1, -1), "Helvetica"),
        ("FONTSIZE",      (0, 1), (-1, -1), 7.5),
        ("TOPPADDING",    (0, 1), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 1), (-1, -1), 3),
        ("TEXTCOLOR",     (0, 1), (-1, -1), BLACK),
        ("ALIGN",         (1, 0), (-1, -1), "RIGHT"),
        ("ALIGN",         (0, 0), (0, -1), "LEFT"),
        ("ROWBACKGROUNDS",(0, 1), (-1, -1), [WHITE, BLUE_LIGHT]),
        ("LINEBELOW",     (0, 0), (-1, 0), 1.5, BLUE),
        ("LINEBELOW",     (0, 1), (-1, -2), 0.3, BLUE_MID),
        ("BOX",           (0, 0), (-1, -1), 0.5, BLUE_MID),
    ]

    for i, (_, row) in enumerate(recap.iterrows(), start=1):
        v_j = float(row.get("Var. jour", 0) or 0)
        v_y = float(row.get("Var. YTD",  0) or 0)
        rows.append([
            row["FCP"],
            _xof(row.get("Valorisation")),
            _xof(v_j, signed=True),
            _pct(row.get("Var. jour %"), signed=True),
            _xof(v_y, signed=True),
            _pct(row.get("Var. YTD %"), signed=True),
            _xof(row.get("Valo début année")),
        ])
        c_j = GREEN if v_j > 0 else (RED if v_j < 0 else BLACK)
        c_y = GREEN if v_y > 0 else (RED if v_y < 0 else BLACK)
        fn  = "Helvetica-Bold"
        style_cmds += [
            ("TEXTCOLOR", (2, i), (3, i), c_j),
            ("FONTNAME",  (2, i), (3, i), fn if v_j != 0 else "Helvetica"),
            ("TEXTCOLOR", (4, i), (5, i), c_y),
            ("FONTNAME",  (4, i), (5, i), fn if v_y != 0 else "Helvetica"),
        ]

    tbl = Table(rows, colWidths=col_w, repeatRows=1)
    tbl.setStyle(TableStyle(style_cmds))
    items.append(tbl)
    return items


# ---------------------------------------------------------------------------
# Section 2 — P&L catalysts
# ---------------------------------------------------------------------------
def _catalysts_section(
    recap: pd.DataFrame,
    exposures,
    styles: dict,
) -> list:
    items = []
    items.append(Spacer(1, 0.4 * cm))
    items.append(Paragraph(
        "2. Catalyseurs du P&L journalier",
        styles["section_title"],
    ))
    items.append(HRFlowable(
        width="100%", thickness=1.5, color=BLUE, spaceAfter=5
    ))

    recap = recap.copy()
    recap["_vj"] = pd.to_numeric(
        recap.get("Var. jour", 0), errors="coerce"
    ).fillna(0)

    # Top 5 positive
    items.append(Paragraph(
        "Top 5 contributeurs positifs", styles["subsection"]
    ))
    _contrib_tbl(recap.nlargest(5, "_vj"), positive=True, items=items)

    items.append(Spacer(1, 0.25 * cm))
    items.append(Paragraph(
        "Top 5 contributeurs négatifs", styles["subsection"]
    ))
    _contrib_tbl(recap.nsmallest(5, "_vj"), positive=False, items=items)

    # Sector breakdown
    if (
        exposures is not None
        and not exposures.empty
        and "secteur" in exposures.columns
    ):
        items.append(Spacer(1, 0.3 * cm))
        items.append(Paragraph(
            "Répartition sectorielle globale", styles["subsection"]
        ))
        sec = (
            exposures.groupby("secteur")["valorisation"]
            .sum()
            .sort_values(ascending=False)
            .reset_index()
        )
        total_s = float(sec["valorisation"].sum())
        sec_data = [["Secteur", "Valorisation (FCFA)", "Poids"]]
        for _, r in sec.iterrows():
            sec_data.append([
                r["secteur"],
                _xof(r["valorisation"]),
                _pct(r["valorisation"] / total_s if total_s else 0),
            ])
        st_tbl = Table(sec_data, colWidths=[8*cm, 4.5*cm, 3*cm])
        st_tbl.setStyle(TableStyle([
            ("BACKGROUND",    (0, 0), (-1, 0), BLUE),
            ("TEXTCOLOR",     (0, 0), (-1, 0), WHITE),
            ("FONTNAME",      (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE",      (0, 0), (-1, -1), 8),
            ("TOPPADDING",    (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ("ALIGN",         (1, 0), (-1, -1), "RIGHT"),
            ("ROWBACKGROUNDS",(0, 1), (-1, -1), [WHITE, BLUE_LIGHT]),
            ("LINEBELOW",     (0, 0), (-1, 0), 1, BLUE),
            ("BOX",           (0, 0), (-1, -1), 0.5, BLUE_MID),
        ]))
        items.append(st_tbl)
    return items


def _contrib_tbl(df: pd.DataFrame, positive: bool, items: list) -> None:
    c = GREEN if positive else RED
    col_w = [5.5*cm, 3.2*cm, 2.5*cm, 3.2*cm, 1.5*cm]
    headers = ["FCP", "Var. jour (FCFA)", "Var. j %",
               "Valorisation", "Rang"]
    rows = [headers]
    for rank, (_, row) in enumerate(df.iterrows(), 1):
        vj = float(row.get("_vj", 0) or 0)
        rows.append([
            row["FCP"],
            _xof(vj, signed=True),
            _pct(row.get("Var. jour %"), signed=True),
            _xof(row.get("Valorisation")),
            str(rank),
        ])
    tbl = Table(rows, colWidths=col_w)
    tbl.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, 0), BLUE_LIGHT),
        ("TEXTCOLOR",     (0, 0), (-1, 0), BLUE),
        ("FONTNAME",      (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE",      (0, 0), (-1, -1), 7.5),
        ("TOPPADDING",    (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("ALIGN",         (1, 0), (-1, -1), "RIGHT"),
        ("ALIGN",         (4, 0), (4, -1), "CENTER"),
        ("ROWBACKGROUNDS",(0, 1), (-1, -1), [WHITE, BLUE_LIGHT]),
        ("LINEBELOW",     (0, 0), (-1, 0), 1, c),
        ("TEXTCOLOR",     (1, 1), (2, -1), c),
        ("FONTNAME",      (1, 1), (2, -1), "Helvetica-Bold"),
        ("BOX",           (0, 0), (-1, -1), 0.5, BLUE_MID),
    ]))
    items.append(tbl)


# ---------------------------------------------------------------------------
# Section 3 — Period comparison
# ---------------------------------------------------------------------------
def _period_section(
    recap_today: pd.DataFrame,
    recap_period: pd.DataFrame | None,
    period_label: str,
    styles: dict,
) -> list:
    items = []
    items.append(Spacer(1, 0.4 * cm))
    items.append(Paragraph(
        f"3. Comparaison sur la période ({period_label})",
        styles["section_title"],
    ))
    items.append(HRFlowable(
        width="100%", thickness=1.5, color=BLUE, spaceAfter=5
    ))

    if recap_period is None or recap_period.empty:
        items.append(Paragraph(
            "Données de comparaison non disponibles pour cette période.",
            styles["body"],
        ))
        return items

    # Merge today vs period
    merged = recap_today[["FCP","Valorisation","Var. jour"]].copy()
    merged = merged.rename(columns={
        "Valorisation": "Valo aujourd'hui",
        "Var. jour":    "Var. jour",
    })

    p_valo = recap_period.set_index("FCP")["Valorisation"].rename("Valo période")
    p_ytd  = recap_period.set_index("FCP").get("Var. YTD", pd.Series(dtype=float))
    merged = merged.set_index("FCP").join(p_valo, how="left").reset_index()

    # Evolution = today - period start
    merged["Evolution"] = (
        pd.to_numeric(merged["Valo aujourd'hui"], errors="coerce") -
        pd.to_numeric(merged["Valo période"], errors="coerce")
    )
    merged["Evol %"] = (
        merged["Evolution"] /
        pd.to_numeric(merged["Valo période"], errors="coerce").replace(0, float("nan"))
    )

    col_w = [5.2*cm, 3.2*cm, 3.2*cm, 3.0*cm, 2.2*cm]
    headers = ["FCP", "Valo aujourd'hui", f"Valo déb. période",
               "Évolution", "Évol. %"]
    rows = [headers]
    style_cmds = [
        ("BACKGROUND",    (0, 0), (-1, 0), BLUE),
        ("TEXTCOLOR",     (0, 0), (-1, 0), WHITE),
        ("FONTNAME",      (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE",      (0, 0), (-1, -1), 7.5),
        ("TOPPADDING",    (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("ALIGN",         (1, 0), (-1, -1), "RIGHT"),
        ("ALIGN",         (0, 0), (0, -1), "LEFT"),
        ("ROWBACKGROUNDS",(0, 1), (-1, -1), [WHITE, BLUE_LIGHT]),
        ("LINEBELOW",     (0, 0), (-1, 0), 1.5, BLUE),
        ("BOX",           (0, 0), (-1, -1), 0.5, BLUE_MID),
    ]
    for i, (_, r) in enumerate(merged.iterrows(), start=1):
        evol = r.get("Evolution")
        ep   = r.get("Evol %")
        rows.append([
            r["FCP"],
            _xof(r.get("Valo aujourd'hui")),
            _xof(r.get("Valo période")),
            _xof(evol, signed=True) if pd.notna(evol) else "-",
            _pct(ep, signed=True)   if pd.notna(ep) else "-",
        ])
        try:
            ev_f = float(evol)
            c = GREEN if ev_f > 0 else (RED if ev_f < 0 else BLACK)
            style_cmds += [
                ("TEXTCOLOR", (3, i), (4, i), c),
                ("FONTNAME",  (3, i), (4, i),
                 "Helvetica-Bold" if ev_f != 0 else "Helvetica"),
            ]
        except (TypeError, ValueError):
            pass

    tbl = Table(rows, colWidths=col_w, repeatRows=1)
    tbl.setStyle(TableStyle(style_cmds))
    items.append(tbl)
    return items


# ---------------------------------------------------------------------------
# Section 4 — Momentum
# ---------------------------------------------------------------------------
def _momentum_section(recap: pd.DataFrame, styles: dict) -> list:
    items = []
    items.append(Spacer(1, 0.4 * cm))
    items.append(Paragraph(
        "4. Tendances et momentum", styles["section_title"]
    ))
    items.append(HRFlowable(
        width="100%", thickness=1.5, color=BLUE, spaceAfter=5
    ))

    r = recap.copy()
    r["_vj"]   = pd.to_numeric(r.get("Var. jour", 0), errors="coerce").fillna(0)
    r["_vytd"] = pd.to_numeric(r.get("Var. YTD",  0), errors="coerce").fillna(0)
    r["_valo"] = pd.to_numeric(r.get("Valorisation", 0), errors="coerce").fillna(0)

    rows = [
        ["Indicateur", "Nb FCPs", "Valorisation concernée (FCFA)"],
        ["Hausse aujourd'hui",
         str(len(r[r["_vj"] > 0])),
         _xof(r[r["_vj"] > 0]["_valo"].sum())],
        ["Baisse aujourd'hui",
         str(len(r[r["_vj"] < 0])),
         _xof(r[r["_vj"] < 0]["_valo"].sum())],
        ["Hausse YTD",
         str(len(r[r["_vytd"] > 0])),
         _xof(r[r["_vytd"] > 0]["_valo"].sum())],
        ["Baisse YTD",
         str(len(r[r["_vytd"] < 0])),
         _xof(r[r["_vytd"] < 0]["_valo"].sum())],
        ["Double momentum positif (jour & YTD)",
         str(len(r[(r["_vj"] > 0) & (r["_vytd"] > 0)])),
         _xof(r[(r["_vj"] > 0) & (r["_vytd"] > 0)]["_valo"].sum())],
        ["Double momentum négatif (jour & YTD)",
         str(len(r[(r["_vj"] < 0) & (r["_vytd"] < 0)])),
         _xof(r[(r["_vj"] < 0) & (r["_vytd"] < 0)]["_valo"].sum())],
    ]
    tbl = Table(rows, colWidths=[9*cm, 3*cm, 4*cm])
    tbl.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, 0), BLUE),
        ("TEXTCOLOR",     (0, 0), (-1, 0), WHITE),
        ("FONTNAME",      (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE",      (0, 0), (-1, -1), 8),
        ("TOPPADDING",    (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("ALIGN",         (1, 0), (-1, -1), "CENTER"),
        ("ROWBACKGROUNDS",(0, 1), (-1, -1), [WHITE, BLUE_LIGHT]),
        ("LINEBELOW",     (0, 0), (-1, 0), 1, BLUE),
        ("BOX",           (0, 0), (-1, -1), 0.5, BLUE_MID),
        # Color rows
        ("TEXTCOLOR", (1, 1), (-1, 2), GREEN),
        ("TEXTCOLOR", (1, 3), (-1, 4), RED),
        ("TEXTCOLOR", (1, 5), (-1, 5), GREEN),
        ("TEXTCOLOR", (1, 6), (-1, 6), RED),
        ("FONTNAME",  (1, 1), (-1, -1), "Helvetica-Bold"),
    ]))
    items.append(tbl)

    # Double positive list
    dp = r[(r["_vj"] > 0) & (r["_vytd"] > 0)]
    if not dp.empty:
        items.append(Spacer(1, 0.25*cm))
        items.append(Paragraph(
            "FCPs en double momentum positif :", styles["subsection"]
        ))
        items.append(Paragraph(
            "  ·  ".join(dp["FCP"].tolist()), styles["body"]
        ))

    # Alerts YTD < -5%
    alerts = r[
        (r["_valo"] > 0) &
        (r["_vytd"] / r["_valo"].replace(0, float("nan")) < -0.05)
    ].dropna(subset=["_vytd"])
    if not alerts.empty:
        items.append(Spacer(1, 0.25*cm))
        items.append(Paragraph(
            "Alertes — FCPs avec YTD < -5% :",
            ParagraphStyle("alert", parent=styles["subsection"],
                           textColor=RED),
        ))
        for _, row in alerts.iterrows():
            ytd_pct = row["_vytd"] / row["_valo"] if row["_valo"] else 0
            items.append(Paragraph(
                f"▸  {row['FCP']}  :  YTD = {_pct(ytd_pct, signed=True)}",
                ParagraphStyle("ab", parent=styles["body"], textColor=RED),
            ))

    # Closing note
    items.append(Spacer(1, 0.8*cm))
    items.append(HRFlowable(width="100%", thickness=0.5, color=BLUE_MID))
    items.append(Spacer(1, 0.15*cm))
    items.append(Paragraph(
        f"Rapport généré automatiquement par le système SVM  ·  "
        "Données BRVM / SharePoint CGF GESTION  ·  "
        "Document confidentiel — usage interne uniquement.",
        styles["caption"],
    ))
    return items


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------
def generate_report(
    recap: pd.DataFrame,
    as_of,
    exposures=None,
    recap_period: pd.DataFrame | None = None,
    period_label: str = "",
) -> bytes:
    """Generate the PDF analytics report and return it as bytes.

    Args:
        recap:         compute_recap() result for as_of date.
        as_of:         Valuation date (pd.Timestamp or date).
        exposures:     compute_exposures() result (for sector breakdown).
                       Pass None to skip.
        recap_period:  compute_recap() result for the start of the period.
                       Pass None to skip period comparison.
        period_label:  Human-readable period label, e.g. "7 derniers jours".

    Returns:
        PDF bytes ready for st.download_button.
    """
    as_of_ts = pd.Timestamp(as_of)
    buf = io.BytesIO()
    doc = _build_doc(buf)
    styles = _styles()

    valo_col = pd.to_numeric(
        recap.get("Valorisation", 0), errors="coerce"
    ).fillna(0)
    vj_col = pd.to_numeric(
        recap.get("Var. jour", 0), errors="coerce"
    ).fillna(0)
    total_valo   = float(valo_col.sum())
    total_vj     = float(vj_col.sum())
    prev_valo    = total_valo - total_vj
    vj_pct       = total_vj / prev_valo if prev_valo else 0.0
    n_actifs     = int((valo_col > 0).sum())

    story: list = []

    story += _cover_section(
        as_of=as_of_ts,
        period_label=period_label,
        total_valo=total_valo,
        var_jour=total_vj,
        var_jour_pct=vj_pct,
        n_fcps=n_actifs,
        styles=styles,
    )

    story += _recap_table_section(recap, styles)
    story += _catalysts_section(recap, exposures, styles)

    story.append(PageBreak())
    story += _period_section(
        recap_today=recap,
        recap_period=recap_period,
        period_label=period_label,
        styles=styles,
    )
    story += _momentum_section(recap, styles)

    doc.build(story)
    buf.seek(0)
    return buf.read()
