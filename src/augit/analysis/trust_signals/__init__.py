from augit.analysis.trust_signals.finding import ComparisonRow, Finding
from augit.analysis.trust_signals.metric import SignalDraft, TrustMetric

# Import builtin metric implementations so that they self-register.
from augit.analysis.trust_signals.metrics import *  # noqa
from augit.analysis.trust_signals.runner import (
    IN_SCOPE_METRICS,
    detect_findings,
    overall_status,
)
from augit.analysis.trust_signals.spec import MetricSpec

__all__ = [
    "ComparisonRow",
    "Finding",
    "MetricSpec",
    "SignalDraft",
    "TrustMetric",
    "IN_SCOPE_METRICS",
    "detect_findings",
    "overall_status",
]
