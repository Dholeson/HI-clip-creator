from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Iterable, List, Sequence, Tuple

import cv2
import mss
import numpy as np
import pytesseract
from difflib import SequenceMatcher

from .analytics import AnalyticsTracker
from .config import MedalSettings, MonitorSettings
from .naming import ClipNamer
from .obs_client import ObsClient

LOGGER = logging.getLogger(__name__)


@dataclass
class Medal:
    settings: MedalSettings
    last_triggered: float = 0.0

    @property
    def cooldown_seconds(self) -> float:
        return self.settings.cooldown_seconds

    @property
    def match_threshold(self) -> float:
        return self.settings.match_threshold

    @property
    def name(self) -> str:
        return self.settings.name

    @property
    def candidates(self) -> Sequence[str]:
        if self.settings.aliases:
            return [self.settings.name, *self.settings.aliases]
        return [self.settings.name]


class ClipMonitor:
    def __init__(
        self,
        settings: MonitorSettings,
        obs_client: ObsClient,
        clip_namer: ClipNamer,
        analytics: AnalyticsTracker,
    ):
        self.settings = settings
        self.obs_client = obs_client
        self.medals: List[Medal] = []
        self.buffered_medals: List[str] = []
        self.buffer_started_at: float | None = None
        self.last_detection_at: float | None = None
        self.clip_namer = clip_namer
        self.analytics = analytics

    def load_medals(self) -> None:
        self.medals = [Medal(settings=medal_settings) for medal_settings in self.settings.medals]
        if not self.medals:
            LOGGER.warning("No medals were configured. Clip triggers will not fire.")

    def _monitor_bounds(self) -> dict:
        region = self.settings.capture_region
        return {
            "left": region.left,
            "top": region.top,
            "width": region.width,
            "height": region.height,
        }

    def _capture_frame(self, screen: mss.base.MSSBase) -> np.ndarray:
        grabbed = screen.grab(self._monitor_bounds())
        frame = np.array(grabbed)
        if self.settings.grayscale:
            frame = cv2.cvtColor(frame, cv2.COLOR_BGRA2GRAY)
        else:
            frame = cv2.cvtColor(frame, cv2.COLOR_BGRA2RGB)
        return frame

    def _active_medals(self) -> Iterable[Medal]:
        now = time.time()
        for medal in self.medals:
            if now - medal.last_triggered >= medal.cooldown_seconds:
                yield medal

    def _extract_text_lines(self, frame: np.ndarray) -> List[str]:
        text = pytesseract.image_to_string(frame, config=self.settings.tesseract_config) or ""
        lines = [line.strip().upper() for line in text.splitlines() if line.strip()]
        LOGGER.debug("OCR lines: %s", lines)
        return lines

    def _score_match(self, lines: Sequence[str], medal: Medal) -> Tuple[float, str]:
        best_score = 0.0
        best_line = ""
        for candidate in (name.upper() for name in medal.candidates):
            for line in lines:
                score = SequenceMatcher(None, candidate, line).ratio()
                if score > best_score:
                    best_score = score
                    best_line = line
        return best_score, best_line

    def _check_medal(self, lines: Sequence[str], medal: Medal) -> bool:
        score, line = self._score_match(lines, medal)
        LOGGER.debug("Medal '%s' best OCR score %.3f against '%s'", medal.name, score, line)
        if score >= medal.match_threshold:
            medal.last_triggered = time.time()
            self.analytics.record_medal(medal.name)
            return True
        return False

    def _buffer_medals(self, triggered: List[Medal]) -> None:
        if not triggered:
            return
        now = time.time()
        names = [medal.name for medal in triggered]
        if self.buffer_started_at is None:
            LOGGER.info("Starting buffer window with medal(s): %s", names)
            self.buffer_started_at = now
        else:
            LOGGER.info("Extending buffer window with medal(s): %s", names)
        self.buffered_medals.extend(names)
        self.last_detection_at = now

    def _should_finalize(self, current_time: float) -> bool:
        if self.last_detection_at is None:
            return False
        return (current_time - self.last_detection_at) >= self.settings.detection_buffer_seconds

    def _finalize_clip(self) -> None:
        if not self.buffered_medals:
            return
        medals = sorted(set(self.buffered_medals))
        clip_index = self.analytics.record_clip(medals)
        clip_name = self.clip_namer.build_name(medals, clip_index)
        LOGGER.info("Detected medal chain %s; saving clip as '%s'", medals, clip_name)
        self.obs_client.set_filename_format(clip_name)
        self.obs_client.trigger_replay_buffer()
        self.buffered_medals = []
        self.buffer_started_at = None
        self.last_detection_at = None

    def flush(self) -> None:
        self._finalize_clip()

    def run(self) -> None:
        delay = 1.0 / self.settings.sample_rate_hz
        with mss.mss() as screen:
            while True:
                frame = self._capture_frame(screen)
                lines = self._extract_text_lines(frame)
                triggered = [medal for medal in self._active_medals() if self._check_medal(lines, medal)]
                if triggered:
                    self._buffer_medals(triggered)
                if self._should_finalize(time.time()):
                    self._finalize_clip()
                time.sleep(delay)
