from __future__ import annotations

import logging
import time
from dataclasses import dataclass

from obswebsocket import obsws, requests

from halo_clip_creator.config import OBSSettings

LOGGER = logging.getLogger(__name__)


@dataclass
class ObsClient:
    settings: OBSSettings
    ws: obsws | None = None

    def connect(self) -> None:
        LOGGER.info("Connecting to OBS at %s:%s", self.settings.host, self.settings.port)
        self.ws = obsws(self.settings.host, self.settings.port, self.settings.password)
        self.ws.connect()
        LOGGER.info("Connected to OBS")

    def close(self) -> None:
        if self.ws is not None:
            LOGGER.info("Closing OBS connection")
            self.ws.disconnect()
            self.ws = None

    def trigger_replay_buffer(self) -> None:
        if self.ws is None:
            raise RuntimeError("OBS websocket is not connected")

        if self.settings.trigger_delay_seconds:
            LOGGER.debug("Sleeping %.2f seconds before triggering replay buffer", self.settings.trigger_delay_seconds)
            time.sleep(self.settings.trigger_delay_seconds)

        LOGGER.info("Saving OBS replay buffer")
        self.ws.call(requests.SaveReplayBuffer())

    def set_filename_format(self, name: str) -> None:
        if self.ws is None:
            raise RuntimeError("OBS websocket is not connected")
        LOGGER.info("Updating OBS filename format to '%s'", name)
        self.ws.call(requests.SetFilenameFormatting(name))
