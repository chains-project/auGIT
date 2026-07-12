import os
import sys
from contextlib import contextmanager
from typing import TYPE_CHECKING, Generator

from tqdm import tqdm

if TYPE_CHECKING:
    pass


def progress_enabled() -> bool:
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return False
    if os.environ.get("SSC_AUDIT_NO_PROGRESS"):
        return False
    return sys.stderr.isatty()


@contextmanager
def item_progress(
    desc: str,
    total: int | None = None,
    *,
    unit: str = "items",
) -> Generator[tqdm]:
    bar = tqdm(total=total, desc=desc, unit=unit, disable=not progress_enabled())
    try:
        yield bar
    finally:
        # When total is unknown, tqdm shows "Nitems". Setting total on exit gives a
        # consistent final "100%|...| N/N" line like the collectors that know totals.
        if bar.total is None:
            bar.total = bar.n
            bar.refresh()
        bar.close()
