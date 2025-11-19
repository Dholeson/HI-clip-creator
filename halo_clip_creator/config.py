from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

import yaml


@dataclass
class CaptureRegion:
    left: int
    top: int
    width: int
    height: int


@dataclass
class OBSSettings:
    host: str
    port: int
    password: str
    trigger_delay_seconds: float = 0.0
    filename_format: str = "HI_{session}_{timestamp}_{medals}"
    timestamp_format: str = "%Y%m%d-%H%M%S"
    sanitize_filenames: bool = True


@dataclass
class MedalSettings:
    name: str
    aliases: List[str] = field(default_factory=list)
    match_threshold: float = 0.7
    cooldown_seconds: float = 5.0


@dataclass
class MonitorSettings:
    capture_region: CaptureRegion
    medals: List[MedalSettings] = field(default_factory=list)
    sample_rate_hz: float = 4.0
    grayscale: bool = True
    tesseract_config: str = "--psm 6"
    detection_buffer_seconds: float = 6.0


@dataclass
class AnalyticsSettings:
    enabled: bool = True
    session_name: Optional[str] = None
    session_summary_path: Path = Path("analytics_session.json")
    history_path: Path = Path("analytics_history.json")
    save_on_exit: bool = True


@dataclass
class Settings:
    obs: OBSSettings
    monitor: MonitorSettings
    analytics: AnalyticsSettings = field(default_factory=AnalyticsSettings)


class SettingsError(RuntimeError):
    """Raised when configuration cannot be parsed."""


_EXPECTED_KEYS = {
    "obs": {"host", "port", "password"},
    "monitor": {"capture_region", "medals"},
    "analytics": set(),
}


class _Loader:
    def __init__(self, raw: Dict):
        self.raw = raw

    def _ensure_keys(self, node: Dict, keys: set, root: str) -> None:
        missing = keys - set(node)
        if missing:
            raise SettingsError(f"Missing keys in '{root}': {sorted(missing)}")

    def load_capture_region(self, data: Dict) -> CaptureRegion:
        required = {"left", "top", "width", "height"}
        self._ensure_keys(data, required, "monitor.capture_region")
        return CaptureRegion(
            left=int(data["left"]),
            top=int(data["top"]),
            width=int(data["width"]),
            height=int(data["height"]),
        )

    def load_medals(self, data: List[Dict]) -> List[MedalSettings]:
        medals: List[MedalSettings] = []
        for medal in data:
            self._ensure_keys(medal, {"name"}, "monitor.medals")
            medals.append(
                MedalSettings(
                    name=str(medal["name"]),
                    aliases=[str(alias) for alias in medal.get("aliases", [])],
                    match_threshold=float(medal.get("match_threshold", 0.7)),
                    cooldown_seconds=float(medal.get("cooldown_seconds", 5.0)),
                )
            )
        return medals

    def load_monitor(self, data: Dict) -> MonitorSettings:
        self._ensure_keys(data, _EXPECTED_KEYS["monitor"], "monitor")
        region = self.load_capture_region(data["capture_region"])
        medals = self.load_medals(data.get("medals", []))
        return MonitorSettings(
            capture_region=region,
            medals=medals,
            sample_rate_hz=float(data.get("sample_rate_hz", 4.0)),
            grayscale=bool(data.get("grayscale", True)),
            tesseract_config=str(data.get("tesseract_config", "--psm 6")),
            detection_buffer_seconds=float(data.get("detection_buffer_seconds", 6.0)),
        )

    def load_obs(self, data: Dict) -> OBSSettings:
        self._ensure_keys(data, _EXPECTED_KEYS["obs"], "obs")
        return OBSSettings(
            host=str(data["host"]),
            port=int(data["port"]),
            password=str(data["password"]),
            trigger_delay_seconds=float(data.get("trigger_delay_seconds", 0.0)),
            filename_format=str(data.get("filename_format", "HI_{session}_{timestamp}_{medals}")),
            timestamp_format=str(data.get("timestamp_format", "%Y%m%d-%H%M%S")),
            sanitize_filenames=bool(data.get("sanitize_filenames", True)),
        )

    def load_analytics(self, data: Dict) -> AnalyticsSettings:
        return AnalyticsSettings(
            enabled=bool(data.get("enabled", True)),
            session_name=data.get("session_name"),
            session_summary_path=Path(data.get("session_summary_path", "analytics_session.json")),
            history_path=Path(data.get("history_path", "analytics_history.json")),
            save_on_exit=bool(data.get("save_on_exit", True)),
        )

    def build(self) -> Settings:
        self._ensure_keys(self.raw, {"obs", "monitor"}, "root")
        obs = self.load_obs(self.raw["obs"])
        monitor = self.load_monitor(self.raw["monitor"])
        analytics = self.load_analytics(self.raw.get("analytics", {}))
        return Settings(obs=obs, monitor=monitor, analytics=analytics)


def load_settings(path: Path) -> Settings:
    with path.open("r", encoding="utf-8") as handle:
        raw = yaml.safe_load(handle) or {}
    return _Loader(raw).build()


def default_settings() -> Settings:
    """Return a Settings object populated with sensible defaults for the UI."""

    obs = OBSSettings(host="localhost", port=4455, password="changeme")
    monitor = MonitorSettings(
        capture_region=CaptureRegion(left=100, top=100, width=400, height=150),
        medals=[
            MedalSettings(name="KILLIONAIRE", aliases=["Killionaire"], match_threshold=0.7, cooldown_seconds=6.0),
            MedalSettings(name="DOUBLE KILL", aliases=["Double Kill"], match_threshold=0.65, cooldown_seconds=4.0),
        ],
    )
    analytics = AnalyticsSettings()
    return Settings(obs=obs, monitor=monitor, analytics=analytics)


def settings_to_dict(settings: Settings) -> Dict:
    """Convert Settings into a YAML-serializable dictionary."""

    def _convert_capture_region(region: CaptureRegion) -> Dict:
        return asdict(region)

    def _convert_medal(medal: MedalSettings) -> Dict:
        return asdict(medal)

    def _convert_monitor(monitor: MonitorSettings) -> Dict:
        return {
            "capture_region": _convert_capture_region(monitor.capture_region),
            "medals": [_convert_medal(medal) for medal in monitor.medals],
            "sample_rate_hz": monitor.sample_rate_hz,
            "grayscale": monitor.grayscale,
            "tesseract_config": monitor.tesseract_config,
            "detection_buffer_seconds": monitor.detection_buffer_seconds,
        }

    def _convert_obs(obs: OBSSettings) -> Dict:
        return asdict(obs)

    def _convert_analytics(analytics: AnalyticsSettings) -> Dict:
        payload = asdict(analytics)
        payload["session_summary_path"] = str(analytics.session_summary_path)
        payload["history_path"] = str(analytics.history_path)
        return payload

    return {
        "obs": _convert_obs(settings.obs),
        "monitor": _convert_monitor(settings.monitor),
        "analytics": _convert_analytics(settings.analytics),
    }


def save_settings(settings: Settings, path: Path) -> None:
    """Persist Settings to disk as YAML."""

    payload = settings_to_dict(settings)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        yaml.safe_dump(payload, handle, sort_keys=False)
