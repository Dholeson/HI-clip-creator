from __future__ import annotations

import re
import time
from typing import Iterable, Sequence

from .config import OBSSettings


class ClipNamer:
    def __init__(self, settings: OBSSettings, session_name: str):
        self.settings = settings
        self.session_name = session_name

    def _sanitize(self, value: str) -> str:
        if not self.settings.sanitize_filenames:
            return value
        return re.sub(r"[^A-Za-z0-9_.-]+", "_", value)

    def build_name(self, medals: Sequence[str], clip_index: int) -> str:
        medals_text = "-".join(self._sanitize(name) for name in medals) or "CLIP"
        timestamp = time.strftime(self.settings.timestamp_format)
        formatted = self.settings.filename_format.format(
            session=self._sanitize(self.session_name),
            timestamp=self._sanitize(timestamp),
            medals=medals_text,
            clip=clip_index,
        )
        return formatted

    def label_for_medals(self, medals: Iterable[str]) -> str:
        return " / ".join(sorted(set(medals))) or "Clip"
