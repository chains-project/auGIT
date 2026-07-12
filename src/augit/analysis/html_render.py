from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from augit.analysis.report_builder import TrustReport
from augit.analysis.trust_signals.finding import Finding

_CATEGORY_ORDER = ("contributor", "governance", "release", "dependency", "integrity")

_CATEGORY_LABELS = {
    "contributor": "Contributors",
    "governance": "Governance",
    "release": "Releases",
    "dependency": "Dependencies",
    "integrity": "Integrity",
}


@dataclass(frozen=True)
class FindingSection:
    category: str
    label: str
    baseline: list[str]
    findings: list[Finding]


def _template_dir() -> Path:
    return Path(files("augit.analysis").joinpath("templates"))


def _format_window(report: TrustReport) -> str:
    if report.compare_start and report.compare_end:
        return (
            f"{report.compare_start.strftime('%Y-%m-%d')} – "
            f"{report.compare_end.strftime('%Y-%m-%d')}"
        )
    return "—"


def _group_findings(report: TrustReport) -> list[FindingSection]:
    id_to_category = {m.metric_id: m.category for m in report.metrics_catalog}
    by_category: dict[str, list[Finding]] = {}
    for finding in report.findings:
        category = id_to_category.get(finding.metric_id, "other")
        by_category.setdefault(category, []).append(finding)

    sections: list[FindingSection] = []
    seen = set(_CATEGORY_ORDER)
    for category in _CATEGORY_ORDER:
        findings = by_category.get(category)
        if not findings:
            continue
        sections.append(
            FindingSection(
                category=category,
                label=_CATEGORY_LABELS.get(category, category.title()),
                baseline=report.baseline_by_category.get(category, []),
                findings=findings,
            )
        )
    for category, findings in sorted(by_category.items()):
        if category in seen:
            continue
        sections.append(
            FindingSection(
                category=category,
                label=category.title(),
                baseline=report.baseline_by_category.get(category, []),
                findings=findings,
            )
        )
    return sections


def render_html(report: TrustReport) -> str:
    env = Environment(
        loader=FileSystemLoader(_template_dir()),
        autoescape=select_autoescape(enabled_extensions=("html", "j2")),
    )
    template = env.get_template("report.html.j2")

    if report.coverage_from and report.coverage_to:
        coverage_label = (
            f"{report.coverage_from.strftime('%Y-%m-%d')} – "
            f"{report.coverage_to.strftime('%Y-%m-%d')}"
        )
    elif report.total_events == 0:
        coverage_label = "—"
    else:
        coverage_label = "partial"

    checkpoint_label = (
        report.checkpoint_at.strftime("%Y-%m-%d") if report.checkpoint_at else "none"
    )
    last_report_label = None
    if report.last_report_at:
        last_report_label = report.last_report_at.strftime("%Y-%m-%d %H:%M %Z")
    last_integrity_label = None
    if report.last_integrity_refetch_at:
        last_integrity_label = report.last_integrity_refetch_at.strftime("%Y-%m-%d %H:%M %Z")

    return template.render(
        repo_url=report.repo.canonical_url,
        generated_at=report.generated_at.strftime("%Y-%m-%d %H:%M %Z"),
        finding_count=len(report.findings),
        total_events=report.total_events,
        compare_window_events=report.compare_window_events,
        coverage_label=coverage_label,
        compare_window_label=_format_window(report),
        audit_mode=report.audit_mode,
        tail_days=report.tail_days,
        checkpoint_label=checkpoint_label,
        profile_frozen=report.profile_frozen,
        last_report_label=last_report_label,
        last_report_status=report.last_report_status,
        last_integrity_label=last_integrity_label,
        last_integrity_summary=report.last_integrity_summary,
        finding_sections=_group_findings(report),
        metrics_catalog=report.metrics_catalog,
    )
