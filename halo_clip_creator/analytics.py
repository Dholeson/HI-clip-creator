from __future__ import annotations

import json
import logging
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, List, Sequence

from .config import AnalyticsSettings

LOGGER = logging.getLogger(__name__)


@dataclass
class ClipEvent:
    timestamp: float
    medals: Sequence[str] = field(default_factory=list)


class AnalyticsTracker:
    def __init__(self, settings: AnalyticsSettings):
        self.settings = settings
        self.session_started_at = time.time()
        self.session_name = settings.session_name or time.strftime("%Y%m%d-%H%M%S")
        self.medal_counts: Dict[str, int] = {}
        self.clip_events: List[ClipEvent] = []
        self.clip_counter: int = 0

    def record_medal(self, medal_name: str) -> None:
        if not self.settings.enabled:
            return
        self.medal_counts[medal_name] = self.medal_counts.get(medal_name, 0) + 1

    def record_clip(self, medals: Sequence[str]) -> int:
        if not self.settings.enabled:
            return self.clip_counter
        self.clip_counter += 1
        self.clip_events.append(ClipEvent(timestamp=time.time(), medals=list(medals)))
        return self.clip_counter

    def _summary_payload(self) -> Dict:
        return {
            "session_name": self.session_name,
            "session_started_at": self.session_started_at,
            "session_duration_seconds": time.time() - self.session_started_at,
            "total_clips": len(self.clip_events),
            "medal_counts": self.medal_counts,
            "clips": [asdict(event) for event in self.clip_events],
        }

    def _write_json(self, path: Path, payload: Dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2)

    def save_session(self) -> None:
        if not (self.settings.enabled and self.settings.save_on_exit):
            return
        payload = self._summary_payload()
        LOGGER.info("Writing session analytics to %s", self.settings.session_summary_path)
        self._write_json(self.settings.session_summary_path, payload)
        try:
            existing: List[Dict] = []
            if self.settings.history_path.exists():
                with self.settings.history_path.open("r", encoding="utf-8") as handle:
                    existing = json.load(handle)
            existing.append(payload)
            LOGGER.info("Updating analytics history at %s", self.settings.history_path)
            self._write_json(self.settings.history_path, existing)
        except Exception:
            LOGGER.exception("Unable to update analytics history")


def load_session_summary(path: Path) -> Dict | None:
    """Load a previously saved analytics session summary if it exists."""

    if not path.exists():
        return None
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def load_history(path: Path) -> List[Dict]:
    """Load analytics history entries if available."""

    if not path.exists():
        return []
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)
