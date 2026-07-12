from dataclasses import dataclass


@dataclass(frozen=True)
class MetricSpec:
    metric_id: str
    label: str
    category: str
    description: str
