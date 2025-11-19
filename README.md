# HI Clip Creator

A lightweight Python monitor that watches a defined portion of the Halo Infinite window for medal pop-ups and automatically saves an OBS replay buffer clip whenever a configured medal appears. It now buffers medal chains into a single clip, auto-labels the clip name, and writes session analytics so you can track which medals you earn most.

## How it works

- You define a capture box where medal text appears and list the medal names (with optional aliases) you want to watch.
- The monitor repeatedly captures that HUD region using `mss`, runs it through Tesseract OCR, and compares the recognized lines against your configured medal names with fuzzy matching.
- When a medal clears its match threshold and is outside its cooldown window, the script fires the OBS `SaveReplayBuffer` command through the websocket API.

## Setup

1. Ensure OBS is running with the [obs-websocket plugin](https://github.com/obsproject/obs-websocket) enabled and the Replay Buffer active.
2. Run the installer script (creates a virtual environment, installs dependencies, and copies `config.yaml` if missing):

   ```bash
   chmod +x install.sh
   ./install.sh
   ```

   If you prefer manual setup, install Python 3.10+ dependencies:

   ```bash
   pip install -r requirements.txt
   ```

   The configuration UI uses `tkinter`, which ships with most Python installations. For Halo window auto-detection and the neon UI skin, the app also uses `pygetwindow` (Windows/macOS) and `ttkbootstrap` for styling—both are installed automatically from `requirements.txt`.

   You also need [Tesseract OCR](https://tesseract-ocr.github.io/). On Windows, install the official binaries and ensure `tesseract.exe` is in your `PATH`. On macOS, `brew install tesseract`. On Linux, use your package manager (e.g., `sudo apt install tesseract-ocr`).

3. Copy `config.sample.yaml` to `config.yaml` and update it:

   - `monitor.capture_region`: the bounding box (left/top/width/height) covering where medal text appears on your display.
   - `monitor.medals`: list of medal names to detect, each with optional `aliases`, `match_threshold` (0–1 fuzzy similarity), and `cooldown_seconds` to avoid duplicate triggers.
   - `monitor.detection_buffer_seconds`: how long to wait after the last medal before firing a single clip for a medal chain (prevents back-to-back clips for the same fight).
   - `monitor.tesseract_config`: extra flags passed to Tesseract (defaults to `--psm 6`).
   - `obs`: websocket connection details, optional `trigger_delay_seconds` to offset when the replay buffer is saved, and `filename_format`/`timestamp_format`/`sanitize_filenames` for auto-named clips.
   - `analytics`: opt-in session logging. Specify a session name (or accept the timestamp default), where to write the session summary, and a rolling history file.

Example configuration:

```yaml
obs:
  host: 127.0.0.1
  port: 4455
  password: secret
  trigger_delay_seconds: 0.25
  filename_format: "HI_{session}_{timestamp}_{medals}"
  timestamp_format: "%Y%m%d-%H%M%S"
  sanitize_filenames: true

monitor:
  capture_region:
    left: 100
    top: 100
    width: 420
    height: 240
  sample_rate_hz: 4.0
  grayscale: true
  tesseract_config: "--psm 6 --oem 3"
  detection_buffer_seconds: 6.0
  preferred_window_title: "Halo Infinite"
  preferred_process_names:
    - "HaloInfinite.exe"
  monitor_index: 1
  medals:
    - name: OVERKILL
      aliases: ["OVER KILL"]
      match_threshold: 0.7
      cooldown_seconds: 8.0
    - name: KILLING SPREE
      aliases: ["SPREE"]
      match_threshold: 0.72
      cooldown_seconds: 6.0

analytics:
  enabled: true
  session_name: "my-session"
  session_summary_path: analytics_session.json
  history_path: analytics_history.json
  save_on_exit: true
```

## Usage

Run the monitor with your configuration:

```bash
python -m halo_clip_creator --config config.yaml --log-level INFO
```

Prefer a UI? Launch the configuration app to pick the capture box (on any display), manage medals, and review analytics without editing YAML. The UI can scan for a live Halo Infinite window by both title and executable name, snap the capture region to that window, and surface live stats, medal distributions, and recent sessions in a futuristic control deck:

```bash
python -m halo_clip_creator --ui --config config.yaml
```

 Keep an eye on the logs for OCR scores, medal chain buffers, and clip names. To adjust sensitivity, tweak the `match_threshold` for each medal and the `sample_rate_hz` for performance. The analytics JSON (session + history) will summarize medal counts and every clip that was created during the run.

## Building a release binary

You can publish a single-file binary for players who don't want to install Python. Install the build dependency first (either manually or via the provided build requirements file), then run the PyInstaller helper:

```bash
pip install -r requirements-build.txt
# or: pip install pyinstaller
python build_binary.py
```

The compiled binary will be written to `dist/halo-clip-creator` (or `halo-clip-creator.exe` on Windows) and bundles the CLI + UI entrypoints. The builder explicitly pulls in OpenCV (`cv2`), `pygetwindow`, and `ttkbootstrap` so OCR monitoring, Halo window detection, and the styled UI all work out-of-the-box. Tesseract and OBS with obs-websocket still need to be installed on the target machine. You can attach the `dist/` artifact directly to a GitHub release.
