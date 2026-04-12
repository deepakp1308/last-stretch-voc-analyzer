"""Generate a static HTML dashboard from the analysis report."""

from __future__ import annotations

from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from src.models import AnalysisReport


TEMPLATE_DIR = Path(__file__).parent.parent / "dashboard" / "templates"


def generate_dashboard(report: AnalysisReport, output_path: str = "dashboard/index.html") -> str:
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATE_DIR)),
        autoescape=True,
    )
    env.filters["currency"] = lambda v: f"${v:,.0f}"
    env.filters["pct"] = lambda v: f"{v:.0%}"

    template = env.get_template("report.html")
    html = template.render(report=report)

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html)
    return str(out)
