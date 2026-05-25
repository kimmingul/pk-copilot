"""
PDF report renderer for pk-copilot v0.5.

Uses reportlab for PDF generation. reportlab is optional — guarded import.

Refs: docs/02-roadmap.md v0.5
"""

from __future__ import annotations

import datetime
from pathlib import Path
from typing import Any

from pkplugin import __version__ as _PKPLUGIN_VERSION


def render_pdf_report(
    title: str,
    sections: list[dict[str, Any]],
    output_path: str | Path,
    metadata: dict[str, str],
) -> Path:
    """PDF report via reportlab. Same content structure as HTML.

    Each section dict may have keys:
      heading: str
      content_html: str  (plain text extracted; HTML tags stripped)
      plot_paths: list[str]

    Raises:
        ImportError: If reportlab is not installed.
    """
    try:
        from reportlab.lib import colors  # type: ignore[import-untyped]
        from reportlab.lib.pagesizes import A4  # type: ignore[import-untyped]
        from reportlab.lib.styles import (  # type: ignore[import-untyped]
            ParagraphStyle,
            getSampleStyleSheet,
        )
        from reportlab.lib.units import cm  # type: ignore[import-untyped]
        from reportlab.platypus import (  # type: ignore[import-untyped]
            HRFlowable,
            Image,
            Paragraph,
            SimpleDocTemplate,
            Spacer,
            Table,
            TableStyle,
        )
    except ImportError as exc:
        raise ImportError(
            'reportlab is not installed. Install with: pip install "pk-copilot[report]"'
        ) from exc

    import re

    out = Path(output_path).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)

    doc = SimpleDocTemplate(
        str(out),
        pagesize=A4,
        leftMargin=2 * cm,
        rightMargin=2 * cm,
        topMargin=2 * cm,
        bottomMargin=2 * cm,
        title=title,
        author=f"pk-copilot v{_PKPLUGIN_VERSION}",
    )

    styles = getSampleStyleSheet()
    style_title = ParagraphStyle(
        "ReportTitle",
        parent=styles["Title"],
        fontSize=16,
        textColor=colors.HexColor("#003366"),
        spaceAfter=12,
    )
    style_h2 = ParagraphStyle(
        "SectionHeading",
        parent=styles["Heading2"],
        fontSize=12,
        textColor=colors.HexColor("#003366"),
        spaceBefore=14,
        spaceAfter=6,
    )
    style_normal = ParagraphStyle(
        "ReportNormal",
        parent=styles["Normal"],
        fontSize=9,
        spaceAfter=4,
    )
    style_disclaimer = ParagraphStyle(
        "Disclaimer",
        parent=styles["Normal"],
        fontSize=7,
        textColor=colors.HexColor("#666666"),
        spaceBefore=12,
    )

    def _strip_html(text: str) -> str:
        """Strip HTML tags, leaving plain text."""
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"&amp;", "&", text)
        text = re.sub(r"&lt;", "<", text)
        text = re.sub(r"&gt;", ">", text)
        text = re.sub(r"&quot;", '"', text)
        text = re.sub(r"\s+", " ", text).strip()
        return text

    story: list[Any] = []

    # Title
    story.append(Paragraph(title, style_title))
    story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#003366")))
    story.append(Spacer(1, 0.3 * cm))

    # Metadata table
    if metadata:
        meta_data = [[k, v] for k, v in metadata.items()]
        meta_table = Table(meta_data, colWidths=[5 * cm, 12 * cm])
        meta_table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#4a6fa5")),
                    ("TEXTCOLOR", (0, 0), (0, -1), colors.white),
                    ("FONTSIZE", (0, 0), (-1, -1), 8),
                    (
                        "ROWBACKGROUNDS",
                        (1, 0),
                        (-1, -1),
                        [colors.HexColor("#f5f8fc"), colors.white],
                    ),
                    ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#cccccc")),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 5),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                    ("TOPPADDING", (0, 0), (-1, -1), 3),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                ]
            )
        )
        story.append(meta_table)
        story.append(Spacer(1, 0.4 * cm))

    # Sections
    for section in sections:
        heading = str(section.get("heading", ""))
        content_html = str(section.get("content_html", ""))
        _raw_pp = section.get("plot_paths")
        plot_paths: list[str] = [str(p) for p in (_raw_pp if isinstance(_raw_pp, list) else [])]

        if heading:
            story.append(Paragraph(heading, style_h2))

        if content_html.strip():
            plain = _strip_html(content_html)
            if plain:
                story.append(Paragraph(plain, style_normal))

        for plot_path in plot_paths:
            p = Path(plot_path)
            if p.is_file():
                try:
                    img = Image(str(p), width=16 * cm, height=12 * cm, kind="proportional")
                    story.append(img)
                    story.append(Spacer(1, 0.3 * cm))
                except Exception:
                    story.append(Paragraph(f"[Image unavailable: {p.name}]", style_normal))

    # Disclaimer
    timestamp = datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%d %H:%M:%S UTC")
    story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#cccccc")))
    story.append(
        Paragraph(
            f"Disclaimer: pk-copilot is a research and analysis tool. "
            f"Not intended as a substitute for validated GxP software. "
            f"See docs/10-21cfr-part11.md for compliance guidance. "
            f"Generated by pk-copilot v{_PKPLUGIN_VERSION} on {timestamp}.",
            style_disclaimer,
        )
    )

    doc.build(story)
    return out
