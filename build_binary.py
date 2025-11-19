#!/usr/bin/env python3
"""
Helper for building a standalone Halo Clip Creator binary with PyInstaller.

The resulting binary bundles the CLI + UI entrypoint (`python -m halo_clip_creator`)
so you can upload it to a release without requiring a Python install on the
consumer side (Tesseract and OBS are still required at runtime).
"""
from __future__ import annotations

import os
from pathlib import Path
import sys

try:  # pragma: no cover - runtime convenience script
    import PyInstaller.__main__ as PyInstaller
except ModuleNotFoundError:  # pragma: no cover - runtime convenience script
    sys.exit(
        "PyInstaller is not installed. Install it with `pip install pyinstaller` "
        "or `pip install -r requirements-build.txt`."
    )


def main() -> None:  # pragma: no cover - convenience wrapper
    project_root = Path(__file__).parent
    source = project_root / "halo_clip_creator" / "__main__.py"

    data_sep = ";" if os.name == "nt" else ":"
    config_sample = project_root / "config.sample.yaml"
    add_data_arg = f"{config_sample}{data_sep}."

    PyInstaller.run(
        [
            str(source),
            "--name",
            "halo-clip-creator",
            "--onefile",
            "--clean",
            "--noconfirm",
            "--collect-all",
            "halo_clip_creator",
            "--hidden-import",
            "cv2",
            "--collect-submodules",
            "cv2",
            "--hidden-import",
            "pygetwindow",
            "--collect-submodules",
            "pygetwindow",
            "--hidden-import",
            "ttkbootstrap",
            "--collect-submodules",
            "ttkbootstrap",
            "--add-data",
            add_data_arg,
        ]
    )


if __name__ == "__main__":
    main()
