"""JSONL output of product observations.

Default layout: ``output/<retailer>/<YYYY-MM-DD>/observations.jsonl`` where the
date is the UTC date at the start of the run. Each run appends; one line is one
``ProductObservation``. Several runs on the same day share the file and are told
apart by ``run_id`` (``2026-11-14-kosik-01``, ``-02``, ...).
"""

from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path
from types import TracebackType
from typing import TextIO

from .models import ProductObservation

DEFAULT_OUTPUT_ROOT = Path("output")
OBSERVATIONS_FILE = "observations.jsonl"


def default_output_path(day: date, retailer: str = "kosik", root: Path = DEFAULT_OUTPUT_ROOT) -> Path:
    return root / retailer / day.isoformat() / OBSERVATIONS_FILE


def next_run_id(day: date, path: Path, retailer: str = "kosik") -> str:
    """Next ``<date>-<retailer>-NN`` id, after the highest one already in ``path``."""

    prefix = f"{day.isoformat()}-{retailer}-"
    pattern = re.compile(rf"^{re.escape(prefix)}(\d+)$")
    highest = 0
    if path.exists():
        with path.open(encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                try:
                    run_id = json.loads(line).get("run_id")
                except (json.JSONDecodeError, AttributeError) as exc:
                    raise ValueError(f"{path}:{line_number} is not a valid JSON object") from exc
                match = pattern.match(run_id) if isinstance(run_id, str) else None
                if match:
                    highest = max(highest, int(match.group(1)))
    return f"{prefix}{highest + 1:02d}"


class JsonlWriter:
    """Appends observations to a JSONL file, flushing after every record.

    Flushing per record keeps already scraped products on disk if a long batch
    fails halfway.
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        self.count = 0
        self._handle: TextIO | None = None

    def __enter__(self) -> "JsonlWriter":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._handle = self.path.open("a", encoding="utf-8")
        return self

    def write(self, observation: ProductObservation) -> None:
        if self._handle is None:
            raise RuntimeError("JsonlWriter must be used as a context manager")
        self._handle.write(observation.model_dump_json() + "\n")
        self._handle.flush()
        self.count += 1

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if self._handle is not None:
            self._handle.close()
            self._handle = None


def read_observations(path: Path) -> list[ProductObservation]:
    with path.open(encoding="utf-8") as handle:
        return [ProductObservation.model_validate_json(line) for line in handle if line.strip()]
