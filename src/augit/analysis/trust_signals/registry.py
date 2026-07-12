from collections.abc import Iterable
from typing import TypeVar

from .metric import TrustMetric

T = TypeVar("T", bound=TrustMetric)

_REGISTRY: list[type[TrustMetric]] = []
_REGISTERED_IDS: set[str] = set()


def register_metric(metric_cls: type[T]) -> type[T]:
    """
    Registry decorator.

    Keeps engine open for extension: new metrics only need to be imported
    once and registered here.
    """

    metric_id = metric_cls.spec.metric_id
    if metric_id in _REGISTERED_IDS:
        return metric_cls
    _REGISTERED_IDS.add(metric_id)
    _REGISTRY.append(metric_cls)
    return metric_cls


def registered_metrics() -> tuple[type[TrustMetric], ...]:
    return tuple(_REGISTRY)


def in_scope_metrics() -> tuple:
    return tuple(cls.spec for cls in _REGISTRY)


def get_metric_ids() -> set[str]:
    return set(_REGISTERED_IDS)


def instantiate_metrics() -> Iterable[TrustMetric]:
    for cls in _REGISTRY:
        yield cls()
