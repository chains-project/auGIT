from dataclasses import dataclass, field


@dataclass(frozen=True)
class ComparisonRow:
    """One baseline vs. compare-window observation for report transparency."""

    subject: str
    baseline: str
    observed: str


@dataclass
class Finding:
    metric_id: str
    metric_label: str
    title: str
    summary: str
    evidence: list[str] = field(default_factory=list)
    comparisons: list[ComparisonRow] = field(default_factory=list)
