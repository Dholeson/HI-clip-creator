from __future__ import annotations

import argparse
import logging
from pathlib import Path

from .analytics import AnalyticsTracker
from .config import SettingsError, load_settings
from .monitor import ClipMonitor
from .naming import ClipNamer
from .obs_client import ObsClient


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Monitor Halo Infinite medals and trigger OBS replay buffer.")
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("config.yaml"),
        help="Path to YAML configuration file (default: config.yaml)",
    )
    parser.add_argument("--log-level", default="INFO", help="Logging level (default: INFO)")
    parser.add_argument("--ui", action="store_true", help="Launch the configuration UI instead of the monitor")
    return parser


def main() -> None:
    parser = build_argument_parser()
    args = parser.parse_args()

    logging.basicConfig(
        level=args.log_level.upper(),
        format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
    )

    if args.ui:
        from .gui import launch_ui

        launch_ui(args.config)
        return

    try:
        settings = load_settings(args.config)
    except FileNotFoundError:
        parser.error(f"Configuration file not found: {args.config}")
    except SettingsError as error:
        parser.error(str(error))

    obs_client = ObsClient(settings.obs)
    analytics = AnalyticsTracker(settings.analytics)
    clip_namer = ClipNamer(settings.obs, analytics.session_name)
    monitor = ClipMonitor(settings.monitor, obs_client, clip_namer, analytics)
    monitor.load_medals()

    try:
        obs_client.connect()
        monitor.run()
    except KeyboardInterrupt:
        logging.info("Stopping monitor")
    finally:
        monitor.flush()
        obs_client.close()
        analytics.save_session()


if __name__ == "__main__":
    main()
