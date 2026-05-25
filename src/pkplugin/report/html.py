"""
HTML report renderer for pk-copilot v0.5.

Produces self-contained HTML reports with embedded base64 images.
No external CSS/JS dependencies — everything is inline.

Refs: docs/02-roadmap.md v0.5, docs/10-21cfr-part11.md
"""

from __future__ import annotations

import base64
import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Sequence

if TYPE_CHECKING:
    from pkplugin.nca.engine import NCAResult
    from pkplugin.nca.bioequivalence import BEResult

from pkplugin import __version__ as _PKPLUGIN_VERSION

# ---------------------------------------------------------------------------
# Embedded CSS
# ---------------------------------------------------------------------------

_CSS = """
body {
    font-family: Arial, Helvetica, sans-serif;
    font-size: 11pt;
    color: #1a1a1a;
    margin: 2cm 2.5cm;
    line-height: 1.5;
}
h1 { font-size: 16pt; color: #003366; border-bottom: 2px solid #003366; padding-bottom: 4px; }
h2 { font-size: 13pt; color: #003366; margin-top: 1.5em; }
h3 { font-size: 11pt; color: #003366; }
table {
    border-collapse: collapse;
    width: 100%;
    margin: 1em 0;
    font-size: 9pt;
}
th {
    background-color: #003366;
    color: #ffffff;
    padding: 5px 8px;
    text-align: left;
}
td {
    padding: 4px 8px;
    border-bottom: 1px solid #cccccc;
}
tr:nth-child(even) td { background-color: #f5f8fc; }
.metadata-table th { background-color: #4a6fa5; }
.verdict-pass {
    background-color: #d4edda;
    border: 1px solid #28a745;
    padding: 8px 12px;
    border-radius: 4px;
    color: #155724;
    font-weight: bold;
}
.verdict-fail {
    background-color: #f8d7da;
    border: 1px solid #dc3545;
    padding: 8px 12px;
    border-radius: 4px;
    color: #721c24;
    font-weight: bold;
}
.verdict-na {
    background-color: #fff3cd;
    border: 1px solid #ffc107;
    padding: 8px 12px;
    border-radius: 4px;
    color: #856404;
    font-weight: bold;
}
.plot-img { max-width: 100%; height: auto; margin: 1em 0; }
.disclaimer {
    margin-top: 3em;
    padding: 8px;
    border-top: 1px solid #cccccc;
    font-size: 8pt;
    color: #666666;
}
@media print {
    body { margin: 1.5cm; }
    .no-print { display: none; }
}
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _embed_image(path: str) -> str:
    """Return an HTML <img> tag with the image embedded as base64."""
    p = Path(path)
    if not p.is_file():
        return f'<p><em>Image not found: {path}</em></p>'
    data = base64.b64encode(p.read_bytes()).decode("ascii")
    return f'<img class="plot-img" src="data:image/png;base64,{data}" alt="{p.name}" />'


def _escape_html(text: str) -> str:
    """Minimal HTML escaping."""
    return (
        text
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _fmt(value: object, decimals: int = 4) -> str:
    """Format a value for display in a table cell."""
    if value is None:
        return "—"
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, float):
        if value != value:  # NaN
            return "—"
        return f"{value:.{decimals}f}"
    return _escape_html(str(value))


def _metadata_table_html(metadata: dict[str, str]) -> str:
    if not metadata:
        return ""
    rows_html = "".join(
        f"<tr><th>{_escape_html(k)}</th><td>{_escape_html(v)}</td></tr>"
        for k, v in metadata.items()
    )
    return f'<table class="metadata-table"><tbody>{rows_html}</tbody></table>'


def _df_to_html(df: "object") -> str:
    """Convert a pandas DataFrame to an HTML table string."""
    try:
        import pandas as pd
        if not isinstance(df, pd.DataFrame) or df.empty:
            return "<p><em>No data.</em></p>"
        # Build header
        headers = "".join(f"<th>{_escape_html(str(c))}</th>" for c in df.columns)
        thead = f"<thead><tr>{headers}</tr></thead>"
        # Build body
        body_rows: list[str] = []
        for _, row in df.iterrows():
            cells = "".join(f"<td>{_fmt(v)}</td>" for v in row)
            body_rows.append(f"<tr>{cells}</tr>")
        tbody = "<tbody>" + "".join(body_rows) + "</tbody>"
        return f"<table>{thead}{tbody}</table>"
    except Exception as exc:
        return f"<p><em>Table render error: {_escape_html(str(exc))}</em></p>"


# ---------------------------------------------------------------------------
# Core renderer
# ---------------------------------------------------------------------------


def render_html_report(
    title: str,
    metadata: dict[str, str],
    sections: list[dict[str, object]],
    output_path: str | Path,
) -> Path:
    """Render a self-contained HTML report. Embeds plots as base64 <img>.

    Each section dict may have keys:
      heading: str
      content_html: str
      plot_paths: list[str]
    """
    out = Path(output_path).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    sections_html_parts: list[str] = []
    for section in sections:
        heading = _escape_html(str(section.get("heading", "")))
        content_html = str(section.get("content_html", ""))
        _raw_pp = section.get("plot_paths")
        plot_paths: list[str] = [str(p) for p in (_raw_pp if isinstance(_raw_pp, list) else [])]

        plots_html = "".join(_embed_image(p) for p in plot_paths)
        sections_html_parts.append(
            f"<section>"
            f"<h2>{heading}</h2>"
            f"{content_html}"
            f"{plots_html}"
            f"</section>"
        )

    sections_html = "\n".join(sections_html_parts)
    meta_html = _metadata_table_html(metadata)

    disclaimer_href = "docs/10-21cfr-part11.md"
    disclaimer = (
        f'<div class="disclaimer">'
        f"<strong>Disclaimer:</strong> pk-copilot is a research and analysis tool. "
        f"It is not intended as a substitute for validated GxP software. "
        f"For regulatory submission use, consult "
        f'<a href="{disclaimer_href}">docs/10-21cfr-part11.md</a> for compliance guidance. '
        f"Report generated by pk-copilot v{_escape_html(_PKPLUGIN_VERSION)} on {timestamp}."
        f"</div>"
    )

    html = (
        "<!DOCTYPE html>\n"
        '<html lang="en">\n'
        "<head>\n"
        '<meta charset="UTF-8" />\n'
        f"<title>{_escape_html(title)}</title>\n"
        f"<style>\n{_CSS}\n</style>\n"
        "</head>\n"
        "<body>\n"
        f"<h1>{_escape_html(title)}</h1>\n"
        f"{meta_html}\n"
        f"{sections_html}\n"
        f"{disclaimer}\n"
        "</body>\n"
        "</html>\n"
    )

    out.write_text(html, encoding="utf-8")
    return out


# ---------------------------------------------------------------------------
# NCA convenience renderer
# ---------------------------------------------------------------------------


def render_nca_report(
    results: Sequence["NCAResult"],
    run_id: str,
    output_path: str | Path,
    *,
    include_plots: bool = True,
    audit_dir: str | Path | None = None,
) -> Path:
    """Full NCA HTML report with parameter table + concentration plots + λz regression plots."""
    from pkplugin.report.tables import build_nca_parameter_table
    from pkplugin.report.plots import plot_concentration_time, plot_lambda_z_regression
    import tempfile
    import os

    out = Path(output_path).resolve()
    tmp_dir = out.parent / f"_plots_{run_id}"

    metadata: dict[str, str] = {
        "run_id": run_id,
        "plugin_version": _PKPLUGIN_VERSION,
        "winnonlin_compat": "6.4",
        "timestamp": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
    }

    # Parameter table section
    table = build_nca_parameter_table(results)
    param_table_html = _df_to_html(table.df)
    sections: list[dict[str, object]] = [
        {
            "heading": "NCA Parameter Table",
            "content_html": param_table_html,
            "plot_paths": [],
        }
    ]

    if include_plots and results:
        import numpy as np
        tmp_dir.mkdir(parents=True, exist_ok=True)

        plot_paths_conc: list[str] = []
        plot_paths_lz: list[str] = []

        for result in results:
            sid = result.subject_id

            # Gather time/conc from parameter rows; fall back to empty arrays
            # The actual concentration profile is not stored on NCAResult directly,
            # so we plot what we can from the lambda_z diagnostic.
            lz = result.lambda_z_result

            # Build approximate time array from lambda_z t_start/t_end
            if lz.t_start is not None and lz.t_end is not None and lz.n_points >= 2:
                t_arr = np.linspace(float(lz.t_start), float(lz.t_end), lz.n_points)
                # Reconstruct concentrations from regression
                c_arr = np.exp(
                    float(lz.intercept) - float(lz.lambda_z) * t_arr
                ) if (lz.intercept is not None and lz.lambda_z is not None) else np.ones(lz.n_points)

                conc_path = tmp_dir / f"conc_{sid}.png"
                try:
                    plot_concentration_time(
                        t_arr, c_arr, conc_path,
                        title=f"Subject {sid}",
                        subject_id=sid,
                    )
                    plot_paths_conc.append(str(conc_path))
                except Exception:
                    pass

                lz_path = tmp_dir / f"lz_{sid}.png"
                try:
                    selected = list(range(len(t_arr)))
                    plot_lambda_z_regression(
                        t_arr, c_arr, selected,
                        float(lz.lambda_z) if lz.lambda_z is not None else 0.0,
                        float(lz.intercept) if lz.intercept is not None else 0.0,
                        lz_path,
                        subject_id=sid,
                    )
                    plot_paths_lz.append(str(lz_path))
                except Exception:
                    pass

        if plot_paths_conc:
            sections.append({
                "heading": "Concentration-Time Profiles",
                "content_html": "",
                "plot_paths": plot_paths_conc,
            })
        if plot_paths_lz:
            sections.append({
                "heading": "Lambda_z Regression Plots",
                "content_html": "",
                "plot_paths": plot_paths_lz,
            })

    return render_html_report(
        title=f"NCA Report — Run {run_id}",
        metadata=metadata,
        sections=sections,
        output_path=out,
    )


# ---------------------------------------------------------------------------
# BE convenience renderer
# ---------------------------------------------------------------------------


def render_be_report(
    be_result: "BEResult",
    output_path: str | Path,
    *,
    audit_dir: str | Path | None = None,
) -> Path:
    """BE HTML report: GMR + 90% CI + ANOVA table + verdict box."""
    from pkplugin.report.tables import build_be_summary_table

    out = Path(output_path).resolve()

    metadata: dict[str, str] = {
        "plugin_version": _PKPLUGIN_VERSION,
        "endpoint": str(be_result.endpoint),
        "design": str(be_result.design),
        "timestamp": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
    }

    # Verdict box
    if be_result.be_demonstrated is True:
        verdict_class = "verdict-pass"
        verdict_text = (
            f"BIOEQUIVALENCE DEMONSTRATED — GMR: {_fmt(be_result.gmr_pct)}% "
            f"(90% CI: {_fmt(be_result.ci_90_low_pct)}%–{_fmt(be_result.ci_90_high_pct)}%) "
            f"within [{be_result.be_window[0]:.2f}%, {be_result.be_window[1]:.2f}%]"
        )
    elif be_result.be_demonstrated is False:
        verdict_class = "verdict-fail"
        verdict_text = (
            f"BIOEQUIVALENCE NOT DEMONSTRATED — GMR: {_fmt(be_result.gmr_pct)}% "
            f"(90% CI: {_fmt(be_result.ci_90_low_pct)}%–{_fmt(be_result.ci_90_high_pct)}%) "
            f"outside [{be_result.be_window[0]:.2f}%, {be_result.be_window[1]:.2f}%]"
        )
    else:
        verdict_class = "verdict-na"
        verdict_text = "BE CONCLUSION UNAVAILABLE — model convergence issue"

    verdict_html = f'<div class="{verdict_class}">{verdict_text}</div>'

    # Summary table
    summary_table = build_be_summary_table(be_result)
    summary_html = _df_to_html(summary_table.df)

    # ANOVA table
    anova_html = ""
    anova = be_result.anova_table
    if anova:
        try:
            import pandas as pd
            anova_df = pd.DataFrame(anova).T
            anova_df.index.name = "Source"
            anova_df = anova_df.reset_index()
            anova_html = _df_to_html(anova_df)
        except Exception:
            anova_html = "<p><em>ANOVA table unavailable.</em></p>"

    sections: list[dict[str, object]] = [
        {
            "heading": "Bioequivalence Verdict",
            "content_html": verdict_html,
            "plot_paths": [],
        },
        {
            "heading": "BE Summary",
            "content_html": summary_html,
            "plot_paths": [],
        },
    ]

    if anova_html:
        sections.append({
            "heading": "ANOVA Table",
            "content_html": anova_html,
            "plot_paths": [],
        })

    if be_result.warnings:
        warnings_html = "<ul>" + "".join(
            f"<li>{_escape_html(w)}</li>" for w in be_result.warnings
        ) + "</ul>"
        sections.append({
            "heading": "Warnings",
            "content_html": warnings_html,
            "plot_paths": [],
        })

    return render_html_report(
        title=f"Bioequivalence Report — {be_result.endpoint}",
        metadata=metadata,
        sections=sections,
        output_path=out,
    )
