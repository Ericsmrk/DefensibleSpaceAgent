from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Optional, Tuple

from reportlab.lib import colors
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    Image,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)
from reportlab.platypus.flowables import Flowable
from reportlab.graphics.shapes import Drawing, Line, Rect, String
from reportlab.graphics import renderPDF


ROOT = Path(__file__).resolve().parents[2]
REPORT_MD = Path(__file__).resolve().parent / "REPORT.md"
OUT_PDF = Path(__file__).resolve().parent / "Agent_Project_Report.pdf"

SAMPLE_IMAGES = [
    ROOT / "docs" / "example_interaction_picture_1.PNG",
    ROOT / "docs" / "example_interaction_picture_2.PNG",
    ROOT / "docs" / "example_interaction_picture_3.PNG",
]


@dataclass
class MdBlock:
    kind: str  # title | h2 | h3 | p | ul | pagebreak
    text: str = ""
    items: Optional[List[str]] = None


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _parse_markdown(md: str) -> List[MdBlock]:
    """
    Minimal parser for the report source.
    Supports:
      - Pandoc title lines starting with '%'
      - '##' and '###' headings
      - paragraphs
      - '-' bullet lists
      - '\newpage' marker (LaTeX-like) for explicit page breaks
    """
    lines = md.replace("\r\n", "\n").split("\n")
    blocks: List[MdBlock] = []

    # Title block (pandoc-style % lines)
    title_lines = []
    i = 0
    while i < len(lines) and lines[i].startswith("%"):
        title_lines.append(lines[i].lstrip("%").strip())
        i += 1
    if title_lines:
        blocks.append(MdBlock(kind="title", text="\n".join(title_lines)))

    def flush_paragraph(buf: List[str]) -> None:
        text = " ".join(s.strip() for s in buf).strip()
        if text:
            blocks.append(MdBlock(kind="p", text=text))
        buf.clear()

    para: List[str] = []
    ul: List[str] = []

    def flush_ul() -> None:
        nonlocal ul
        if ul:
            blocks.append(MdBlock(kind="ul", items=ul[:]))
            ul = []

    for j in range(i, len(lines)):
        line = lines[j].rstrip()
        if not line.strip():
            flush_paragraph(para)
            flush_ul()
            continue

        if line.strip() == r"\newpage":
            flush_paragraph(para)
            flush_ul()
            blocks.append(MdBlock(kind="pagebreak"))
            continue

        m2 = re.match(r"^(##)\s+(.*)$", line)
        m3 = re.match(r"^(###)\s+(.*)$", line)
        if m2:
            flush_paragraph(para)
            flush_ul()
            blocks.append(MdBlock(kind="h2", text=m2.group(2).strip()))
            continue
        if m3:
            flush_paragraph(para)
            flush_ul()
            blocks.append(MdBlock(kind="h3", text=m3.group(2).strip()))
            continue

        if line.lstrip().startswith("- "):
            flush_paragraph(para)
            ul.append(line.strip()[2:].strip())
            continue

        para.append(line.strip())

    flush_paragraph(para)
    flush_ul()
    return blocks


def _register_fonts() -> None:
    """
    Prefer system fonts if present; fall back to built-in Helvetica otherwise.
    ReportLab can use TTF for better typography, but we keep this optional.
    """
    candidates: List[Tuple[str, Path]] = []
    win_dir = os.environ.get("WINDIR")
    if win_dir:
        fonts = Path(win_dir) / "Fonts"
        candidates.extend(
            [
                ("Inter", fonts / "Inter-Regular.ttf"),
                ("Inter-Bold", fonts / "Inter-Bold.ttf"),
                ("Calibri", fonts / "calibri.ttf"),
                ("Calibri-Bold", fonts / "calibrib.ttf"),
                ("Times", fonts / "times.ttf"),
                ("Times-Bold", fonts / "timesbd.ttf"),
            ]
        )
    for name, path in candidates:
        if path.is_file():
            try:
                pdfmetrics.registerFont(TTFont(name, str(path)))
            except Exception:
                pass


def _styles() -> dict:
    base = getSampleStyleSheet()
    body_font = "Helvetica"
    heading_font = "Helvetica-Bold"
    if "Calibri" in pdfmetrics.getRegisteredFontNames():
        body_font = "Calibri"
        heading_font = "Calibri-Bold" if "Calibri-Bold" in pdfmetrics.getRegisteredFontNames() else "Calibri"
    elif "Inter" in pdfmetrics.getRegisteredFontNames():
        body_font = "Inter"
        heading_font = "Inter-Bold" if "Inter-Bold" in pdfmetrics.getRegisteredFontNames() else "Inter"

    base_body = ParagraphStyle(
        "Body",
        parent=base["BodyText"],
        fontName=body_font,
        fontSize=10.5,
        leading=14,
        spaceAfter=8,
    )
    h2 = ParagraphStyle(
        "H2",
        parent=base["Heading2"],
        fontName=heading_font,
        fontSize=14,
        leading=18,
        spaceBefore=10,
        spaceAfter=8,
    )
    h3 = ParagraphStyle(
        "H3",
        parent=base["Heading3"],
        fontName=heading_font,
        fontSize=12,
        leading=16,
        spaceBefore=8,
        spaceAfter=6,
    )
    title = ParagraphStyle(
        "Title",
        parent=base["Title"],
        fontName=heading_font,
        fontSize=18,
        leading=22,
        spaceAfter=10,
    )
    subtitle = ParagraphStyle(
        "Subtitle",
        parent=base["BodyText"],
        fontName=body_font,
        fontSize=11,
        leading=15,
        textColor=colors.HexColor("#334155"),
        spaceAfter=14,
    )
    bullet = ParagraphStyle(
        "Bullet",
        parent=base_body,
        leftIndent=14,
        bulletIndent=6,
        spaceAfter=3,
    )
    caption = ParagraphStyle(
        "Caption",
        parent=base_body,
        fontSize=9.5,
        leading=12,
        textColor=colors.HexColor("#475569"),
        spaceAfter=10,
    )
    return {
        "body": base_body,
        "h2": h2,
        "h3": h3,
        "title": title,
        "subtitle": subtitle,
        "bullet": bullet,
        "caption": caption,
        "heading_font": heading_font,
        "body_font": body_font,
    }


def _escape_for_paragraph(text: str) -> str:
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    # Minimal emphasis for **bold** markers
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    # Code formatting for `code`
    text = re.sub(r"`([^`]+)`", r"<font face='Courier'>\1</font>", text)
    return text


def _draw_architecture_diagram(sty: dict) -> Drawing:
    w, h = 7.2 * inch, 2.4 * inch
    d = Drawing(w, h)

    def box(x, y, bw, bh, label, fill=colors.whitesmoke):
        d.add(Rect(x, y, bw, bh, strokeColor=colors.HexColor("#334155"), fillColor=fill, strokeWidth=1))
        d.add(String(x + bw / 2, y + bh / 2, label, textAnchor="middle", fontName=sty["heading_font"], fontSize=9))

    def arrow(x1, y1, x2, y2):
        d.add(Line(x1, y1, x2, y2, strokeColor=colors.HexColor("#334155"), strokeWidth=1))
        # small arrow head
        d.add(Line(x2, y2, x2 - 6, y2 + 3, strokeColor=colors.HexColor("#334155"), strokeWidth=1))
        d.add(Line(x2, y2, x2 - 6, y2 - 3, strokeColor=colors.HexColor("#334155"), strokeWidth=1))

    # Columns
    left_x = 0.2 * inch
    mid_x = 2.6 * inch
    right_x = 5.0 * inch
    bw, bh = 2.2 * inch, 0.55 * inch
    gap = 0.22 * inch

    y_top = h - bh - 0.15 * inch
    box(left_x, y_top, bw, bh, "UI (single page)\nweb_app.py")
    box(left_x, y_top - (bh + gap), bw, bh, "API endpoints\n/api/plan, /api/assess")

    box(mid_x, y_top, bw, bh, "Planner (LLM)\nexecution spec JSON")
    box(mid_x, y_top - (bh + gap), bw, bh, "Validators (rule-based)\nplan + tool args")
    box(mid_x, y_top - 2 * (bh + gap), bw, bh, "Tier executors\nBaseline / Full")

    box(right_x, y_top, bw, bh, "Tools\nGoogle Geocode,\nEarth Engine NDVI")
    box(right_x, y_top - (bh + gap), bw, bh, "LLM synthesis\nBaseline report,\nCAL FIRE plan")
    box(right_x, y_top - 2 * (bh + gap), bw, bh, "Outputs\nJSON + narrative")

    # Arrows
    arrow(left_x + bw, y_top + bh / 2, mid_x, y_top + bh / 2)
    arrow(left_x + bw, y_top - (bh + gap) + bh / 2, mid_x, y_top - (bh + gap) + bh / 2)
    arrow(mid_x + bw, y_top + bh / 2, right_x, y_top + bh / 2)
    arrow(mid_x + bw, y_top - 2 * (bh + gap) + bh / 2, right_x, y_top - 2 * (bh + gap) + bh / 2)
    arrow(mid_x + bw, y_top - (bh + gap) + bh / 2, mid_x + bw, y_top - 2 * (bh + gap) + bh / 2)
    arrow(right_x + bw, y_top - (bh + gap) + bh / 2, right_x + bw, y_top - 2 * (bh + gap) + bh / 2)

    return d


def _draw_llm_flow_diagram(sty: dict) -> Drawing:
    w, h = 7.2 * inch, 2.1 * inch
    d = Drawing(w, h)

    def box(x, y, bw, bh, label, fill=colors.HexColor("#f8fafc")):
        d.add(Rect(x, y, bw, bh, strokeColor=colors.HexColor("#0f172a"), fillColor=fill, strokeWidth=1))
        d.add(String(x + bw / 2, y + bh / 2, label, textAnchor="middle", fontName=sty["heading_font"], fontSize=9))

    def arrow(x1, y1, x2, y2):
        d.add(Line(x1, y1, x2, y2, strokeColor=colors.HexColor("#0f172a"), strokeWidth=1))
        d.add(Line(x2, y2, x2 - 6, y2 + 3, strokeColor=colors.HexColor("#0f172a"), strokeWidth=1))
        d.add(Line(x2, y2, x2 - 6, y2 - 3, strokeColor=colors.HexColor("#0f172a"), strokeWidth=1))

    bw, bh = 1.55 * inch, 0.55 * inch
    y = h - bh - 0.25 * inch
    x0 = 0.25 * inch
    xs = [x0 + i * (bw + 0.22 * inch) for i in range(4)]
    box(xs[0], y, bw, bh, "LLM 1:\nPlanner\n(JSON)")
    box(xs[1], y, bw, bh, "Rule validation\n(plan/args)")
    box(xs[2], y, bw, bh, "LLM 2:\nFull validator\n(JSON)")
    box(xs[3], y, bw, bh, "LLM 3–4:\nRecommendations\n+ Narrative")
    for i in range(3):
        arrow(xs[i] + bw, y + bh / 2, xs[i + 1], y + bh / 2)

    y2 = 0.35 * inch
    box(xs[0], y2, bw, bh, "Baseline branch:\nLLM synthesis\n(JSON)")
    box(xs[1], y2, bw, bh, "Baseline tools\n+ executor")
    arrow(xs[1] + bw / 2, y - 0.05 * inch, xs[1] + bw / 2, y2 + bh + 0.1 * inch)
    arrow(xs[0] + bw / 2, y2 + bh + 0.05 * inch, xs[0] + bw / 2, y - 0.15 * inch)

    return d


def build_pdf() -> Path:
    if not REPORT_MD.is_file():
        raise FileNotFoundError(f"Missing report source: {REPORT_MD}")

    _register_fonts()
    sty = _styles()

    doc = SimpleDocTemplate(
        str(OUT_PDF),
        pagesize=LETTER,
        leftMargin=0.95 * inch,
        rightMargin=0.95 * inch,
        topMargin=0.85 * inch,
        bottomMargin=0.85 * inch,
        title="ClearSafe California – Defensible Space Agent (Version One)",
        author="DefensibleSpaceAgent repository",
    )

    blocks = _parse_markdown(_read_text(REPORT_MD))
    story: List[object] = []

    # Title page
    if blocks and blocks[0].kind == "title":
        title_lines = blocks[0].text.split("\n")
        story.append(Paragraph(_escape_for_paragraph(title_lines[0]), sty["title"]))
        for line in title_lines[1:]:
            if line.strip():
                story.append(Paragraph(_escape_for_paragraph(line), sty["subtitle"]))
        story.append(Spacer(1, 0.2 * inch))
        # Compact metadata table from repo structure (static, evidence-based in code/docs)
        tbl = Table(
            [
                ["Repository", "DefensibleSpaceAgent"],
                ["Runtime", "Python 3 + Flask"],
                ["Entry point", "web_app.py"],
                ["Core agent", "src/agent.py (planner/validators/executors)"],
            ],
            colWidths=[1.35 * inch, 4.9 * inch],
        )
        tbl.setStyle(
            TableStyle(
                [
                    ("BOX", (0, 0), (-1, -1), 0.75, colors.HexColor("#334155")),
                    ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#94a3b8")),
                    ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f8fafc")),
                    ("FONTNAME", (0, 0), (-1, -1), sty["body"].fontName),
                    ("FONTSIZE", (0, 0), (-1, -1), 10),
                    ("LEFTPADDING", (0, 0), (-1, -1), 8),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                    ("TOPPADDING", (0, 0), (-1, -1), 6),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ]
            )
        )
        story.append(tbl)
        story.append(PageBreak())
        blocks = blocks[1:]

    inserted_arch = False
    inserted_flow = False

    for b in blocks:
        if b.kind == "h2":
            story.append(Paragraph(_escape_for_paragraph(b.text), sty["h2"]))
            # Insert diagrams early, right after architecture and flow sections appear.
            if b.text.strip().lower().startswith("3.") and (not inserted_arch):
                d = _draw_architecture_diagram(sty)
                story.append(Spacer(1, 0.08 * inch))
                story.append(Paragraph("Figure 1. Implemented system architecture (Version One).", sty["caption"]))
                story.append(_DrawingFlowable(d))
                story.append(Spacer(1, 0.12 * inch))
                inserted_arch = True
            if b.text.strip().lower().startswith("4.") and (not inserted_flow):
                d = _draw_llm_flow_diagram(sty)
                story.append(Spacer(1, 0.08 * inch))
                story.append(Paragraph("Figure 2. Multi-LLM orchestration and branching (Baseline vs Full).", sty["caption"]))
                story.append(_DrawingFlowable(d))
                story.append(Spacer(1, 0.12 * inch))
                inserted_flow = True
        elif b.kind == "h3":
            story.append(Paragraph(_escape_for_paragraph(b.text), sty["h3"]))
        elif b.kind == "p":
            story.append(Paragraph(_escape_for_paragraph(b.text), sty["body"]))
        elif b.kind == "ul" and b.items:
            for it in b.items:
                story.append(Paragraph(_escape_for_paragraph(it), sty["bullet"], bulletText="•"))
            story.append(Spacer(1, 0.05 * inch))
        elif b.kind == "pagebreak":
            story.append(PageBreak())

    # Appendix images: force a new section on new pages, and put each screenshot on its own page.
    story.append(PageBreak())
    story.append(Paragraph("Appendix: Sample Interactions (not part of main page limit)", sty["h2"]))

    for idx, img_path in enumerate(SAMPLE_IMAGES, start=1):
        story.append(Paragraph(f"Figure A{idx}. Sample interaction screenshot {idx}.", sty["caption"]))
        if img_path.is_file():
            im = Image(str(img_path))
            # Fit within page width/height with margins; keep aspect ratio.
            max_w = doc.width
            # Keep images comfortably within a single page beneath header/caption.
            max_h = 7.4 * inch
            iw, ih = im.imageWidth, im.imageHeight
            scale = min(max_w / iw, max_h / ih)
            im.drawWidth = iw * scale
            im.drawHeight = ih * scale
            im.hAlign = "CENTER"
            story.append(im)
        else:
            story.append(
                Paragraph(
                    f"<b>Missing image:</b> expected at <font face='Courier'>{img_path.as_posix()}</font>",
                    sty["body"],
                )
            )
        if idx != len(SAMPLE_IMAGES):
            story.append(PageBreak())

    doc.build(story, onFirstPage=_page, onLaterPages=_page)
    return OUT_PDF


class _DrawingFlowable(Flowable):
    """Flowable wrapper to place a reportlab.graphics Drawing in Platypus story."""

    def __init__(self, drawing: Drawing):
        super().__init__()
        self.drawing = drawing
        self.width = drawing.width
        self.height = drawing.height

    def wrap(self, availWidth, availHeight):
        # Allow the drawing to shrink if page width is smaller.
        w = min(self.width, availWidth)
        # Maintain aspect ratio if scaling is needed.
        if self.width > 0:
            scale = w / self.width
            self._scale = scale
            return w, self.height * scale
        self._scale = 1.0
        return w, self.height

    def draw(self):
        scale = getattr(self, "_scale", 1.0) or 1.0
        self.canv.saveState()
        if scale != 1.0:
            self.canv.scale(scale, scale)
        renderPDF.draw(self.drawing, self.canv, 0, 0)
        self.canv.restoreState()


def _page(canvas, doc):
    canvas.saveState()
    canvas.setFont("Helvetica", 9)
    canvas.setFillColor(colors.HexColor("#64748b"))
    canvas.drawString(doc.leftMargin, 0.55 * inch, "ClearSafe California – Defensible Space Agent (v1) · Course report")
    canvas.drawRightString(doc.pagesize[0] - doc.rightMargin, 0.55 * inch, f"Page {doc.page}")
    canvas.restoreState()


if __name__ == "__main__":
    out = build_pdf()
    print(f"Wrote: {out}")

