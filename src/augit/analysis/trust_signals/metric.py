from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from augit.analysis.profile import AuditContext, RepositoryProfile
from augit.analysis.timeline import RepoTimeline
from augit.analysis.trust_signals.finding import ComparisonRow, Finding
from augit.analysis.trust_signals.spec import MetricSpec


@dataclass(frozen=True)
class SignalDraft:
    title: str
    summary: str
    evidence: list[str] = field(default_factory=list)
    comparisons: list[ComparisonRow] = field(default_factory=list)


class TrustMetric(ABC):
    """
    Strategy interface for one trust metric.

    A metric is responsible for:
    - reading the compare-window timeline + baseline profile
    - returning one or more SignalDraft objects
    """

    spec: MetricSpec

    @abstractmethod
    def detect(
        self,
        timeline: RepoTimeline,
        profile: RepositoryProfile,
        context: AuditContext,
    ) -> list[SignalDraft]:
        raise NotImplementedError

    def to_finding(self, draft: SignalDraft) -> Finding:
        return Finding(
            metric_id=self.spec.metric_id,
            metric_label=self.spec.label,
            title=draft.title,
            summary=draft.summary,
            evidence=draft.evidence,
            comparisons=list(draft.comparisons),
        )
