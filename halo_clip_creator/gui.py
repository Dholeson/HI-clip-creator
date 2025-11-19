from __future__ import annotations

import logging
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk
from typing import Callable, List, Optional, Sequence

import mss
import numpy as np
from PIL import Image, ImageTk

from .analytics import load_history, load_session_summary
from .config import (
    CaptureRegion,
    MedalSettings,
    MonitorSettings,
    OBSSettings,
    Settings,
    default_settings,
    load_settings,
    save_settings,
)

LOGGER = logging.getLogger(__name__)


class RegionSelector(tk.Toplevel):
    def __init__(self, master: tk.Misc, callback: Callable[[CaptureRegion], None]):
        super().__init__(master)
        self.title("Select capture region")
        self.callback = callback
        self.geometry("1200x750")
        self.resizable(True, True)
        self.selection: Optional[tuple[int, int, int, int]] = None
        self._setup_canvas()

    def _setup_canvas(self) -> None:
        with mss.mss() as screen:
            monitor = screen.monitors[1]
            screenshot = np.array(screen.grab(monitor))
        image = Image.fromarray(screenshot)
        max_width = 1100
        scale = min(1.0, max_width / image.width)
        self.scale = scale
        if scale != 1.0:
            image = image.resize((int(image.width * scale), int(image.height * scale)))
        self.photo = ImageTk.PhotoImage(image)
        self.canvas = tk.Canvas(self, width=self.photo.width(), height=self.photo.height())
        self.canvas.pack(fill=tk.BOTH, expand=True)
        self.canvas.create_image(0, 0, anchor=tk.NW, image=self.photo)
        self.rect = None
        self.start_x = 0
        self.start_y = 0
        self.canvas.bind("<ButtonPress-1>", self._on_press)
        self.canvas.bind("<B1-Motion>", self._on_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_release)

        ttk.Button(self, text="Use Selection", command=self._finish).pack(pady=8)

    def _on_press(self, event: tk.Event) -> None:
        self.start_x = event.x
        self.start_y = event.y
        if self.rect:
            self.canvas.delete(self.rect)
        self.rect = self.canvas.create_rectangle(self.start_x, self.start_y, self.start_x, self.start_y, outline="red")

    def _on_drag(self, event: tk.Event) -> None:
        if not self.rect:
            return
        self.canvas.coords(self.rect, self.start_x, self.start_y, event.x, event.y)

    def _on_release(self, event: tk.Event) -> None:
        if not self.rect:
            return
        x1, y1, x2, y2 = self.canvas.coords(self.rect)
        self.selection = (int(min(x1, x2)), int(min(y1, y2)), int(abs(x2 - x1)), int(abs(y2 - y1)))

    def _finish(self) -> None:
        if not self.selection:
            messagebox.showerror("No region", "Please drag to select a region first.")
            return
        left, top, width, height = self.selection
        scale = 1.0 / self.scale
        region = CaptureRegion(
            left=int(left * scale),
            top=int(top * scale),
            width=int(width * scale),
            height=int(height * scale),
        )
        self.callback(region)
        self.destroy()


class MedalEditor(ttk.Frame):
    def __init__(self, master: tk.Misc, medals: List[MedalSettings]):
        super().__init__(master, padding=8)
        self.medals = medals
        self._build_widgets()
        self._refresh_list()

    def _build_widgets(self) -> None:
        self.columnconfigure(1, weight=1)
        ttk.Label(self, text="Medals").grid(row=0, column=0, sticky=tk.W)
        self.medal_list = tk.Listbox(self, height=8)
        self.medal_list.grid(row=1, column=0, rowspan=6, sticky=tk.NS + tk.EW, padx=(0, 8))
        self.medal_list.bind("<<ListboxSelect>>", self._on_select)

        ttk.Label(self, text="Name").grid(row=1, column=1, sticky=tk.W)
        self.name_var = tk.StringVar()
        ttk.Entry(self, textvariable=self.name_var).grid(row=1, column=2, sticky=tk.EW)

        ttk.Label(self, text="Aliases (comma separated)").grid(row=2, column=1, sticky=tk.W)
        self.alias_var = tk.StringVar()
        ttk.Entry(self, textvariable=self.alias_var).grid(row=2, column=2, sticky=tk.EW)

        ttk.Label(self, text="Match threshold").grid(row=3, column=1, sticky=tk.W)
        self.threshold_var = tk.DoubleVar(value=0.7)
        ttk.Entry(self, textvariable=self.threshold_var).grid(row=3, column=2, sticky=tk.EW)

        ttk.Label(self, text="Cooldown (s)").grid(row=4, column=1, sticky=tk.W)
        self.cooldown_var = tk.DoubleVar(value=5.0)
        ttk.Entry(self, textvariable=self.cooldown_var).grid(row=4, column=2, sticky=tk.EW)

        button_frame = ttk.Frame(self)
        button_frame.grid(row=5, column=1, columnspan=2, pady=4, sticky=tk.E)
        ttk.Button(button_frame, text="Add/Update", command=self._save_medal).pack(side=tk.LEFT, padx=4)
        ttk.Button(button_frame, text="Remove", command=self._remove_medal).pack(side=tk.LEFT)

    def _refresh_list(self) -> None:
        self.medal_list.delete(0, tk.END)
        for medal in self.medals:
            self.medal_list.insert(tk.END, medal.name)

    def _on_select(self, _event: tk.Event) -> None:
        if not self.medal_list.curselection():
            return
        idx = self.medal_list.curselection()[0]
        medal = self.medals[idx]
        self.name_var.set(medal.name)
        self.alias_var.set(", ".join(medal.aliases))
        self.threshold_var.set(medal.match_threshold)
        self.cooldown_var.set(medal.cooldown_seconds)

    def _save_medal(self) -> None:
        name = self.name_var.get().strip()
        if not name:
            messagebox.showerror("Missing name", "Please enter a medal name.")
            return
        aliases = [alias.strip() for alias in self.alias_var.get().split(",") if alias.strip()]
        medal = MedalSettings(
            name=name,
            aliases=aliases,
            match_threshold=float(self.threshold_var.get()),
            cooldown_seconds=float(self.cooldown_var.get()),
        )
        existing = {m.name: idx for idx, m in enumerate(self.medals)}
        if name in existing:
            self.medals[existing[name]] = medal
        else:
            self.medals.append(medal)
        self._refresh_list()

    def _remove_medal(self) -> None:
        if not self.medal_list.curselection():
            return
        idx = self.medal_list.curselection()[0]
        self.medals.pop(idx)
        self._refresh_list()


class AnalyticsPanel(ttk.Frame):
    def __init__(self, master: tk.Misc, settings: Settings):
        super().__init__(master, padding=8)
        self.settings = settings
        self._build()
        self.refresh()

    def _build(self) -> None:
        self.columnconfigure(1, weight=1)
        ttk.Label(self, text="Session summary").grid(row=0, column=0, sticky=tk.W)
        self.session_text = tk.Text(self, height=8, width=60)
        self.session_text.grid(row=1, column=0, columnspan=2, sticky=tk.EW)
        self.session_text.configure(state=tk.DISABLED)

        ttk.Label(self, text="History (latest 5 sessions)").grid(row=2, column=0, sticky=tk.W, pady=(8, 0))
        self.history_text = tk.Text(self, height=8, width=60)
        self.history_text.grid(row=3, column=0, columnspan=2, sticky=tk.EW)
        self.history_text.configure(state=tk.DISABLED)
        ttk.Button(self, text="Refresh analytics", command=self.refresh).grid(row=4, column=0, pady=6, sticky=tk.W)

    def refresh(self) -> None:
        session = load_session_summary(self.settings.analytics.session_summary_path)
        history = load_history(self.settings.analytics.history_path)
        self._render_text(self.session_text, self._format_session(session))
        self._render_text(self.history_text, self._format_history(history))

    def _format_session(self, payload: Optional[dict]) -> str:
        if not payload:
            return "No session analytics saved yet. Run the monitor to generate data."
        lines = [
            f"Session: {payload.get('session_name')}",
            f"Duration: {int(payload.get('session_duration_seconds', 0))}s",
            f"Total clips: {payload.get('total_clips', 0)}",
            "Medal counts:",
        ]
        medal_counts = payload.get("medal_counts", {})
        if medal_counts:
            lines.extend([f"  - {name}: {count}" for name, count in medal_counts.items()])
        else:
            lines.append("  No medals recorded")
        return "\n".join(lines)

    def _format_history(self, history: Sequence[dict]) -> str:
        if not history:
            return "History file is empty."
        latest = history[-5:]
        formatted: List[str] = []
        for entry in latest:
            formatted.append(
                f"{entry.get('session_name')} - clips: {entry.get('total_clips', 0)} - medals: {len(entry.get('medal_counts', {}))}"
            )
        return "\n".join(formatted)

    def _render_text(self, widget: tk.Text, content: str) -> None:
        widget.configure(state=tk.NORMAL)
        widget.delete("1.0", tk.END)
        widget.insert(tk.END, content)
        widget.configure(state=tk.DISABLED)


class SettingsApp(tk.Tk):
    def __init__(self, config_path: Path):
        super().__init__()
        self.title("Halo Infinite Clip Creator")
        self.config_path = config_path
        self.settings = self._load()
        self._build_ui()

    def _load(self) -> Settings:
        try:
            return load_settings(self.config_path)
        except FileNotFoundError:
            LOGGER.info("Config %s not found, loading defaults", self.config_path)
            return default_settings()

    def _build_ui(self) -> None:
        notebook = ttk.Notebook(self)
        notebook.pack(fill=tk.BOTH, expand=True)

        notebook.add(self._build_capture_tab(), text="Capture")
        notebook.add(self._build_medals_tab(), text="Medals")
        notebook.add(self._build_analytics_tab(), text="Analytics")

        save_frame = ttk.Frame(self, padding=8)
        save_frame.pack(fill=tk.X)
        ttk.Button(save_frame, text="Save configuration", command=self._save).pack(side=tk.RIGHT)
        ttk.Label(save_frame, text=f"Config: {self.config_path}").pack(side=tk.LEFT)

    def _build_capture_tab(self) -> ttk.Frame:
        frame = ttk.Frame(self, padding=8)
        frame.columnconfigure(1, weight=1)
        region = self.settings.monitor.capture_region

        ttk.Label(frame, text="OBS host").grid(row=0, column=0, sticky=tk.W)
        self.obs_host = tk.StringVar(value=self.settings.obs.host)
        ttk.Entry(frame, textvariable=self.obs_host).grid(row=0, column=1, sticky=tk.EW)

        ttk.Label(frame, text="OBS port").grid(row=1, column=0, sticky=tk.W)
        self.obs_port = tk.IntVar(value=self.settings.obs.port)
        ttk.Entry(frame, textvariable=self.obs_port).grid(row=1, column=1, sticky=tk.EW)

        ttk.Label(frame, text="OBS password").grid(row=2, column=0, sticky=tk.W)
        self.obs_password = tk.StringVar(value=self.settings.obs.password)
        ttk.Entry(frame, textvariable=self.obs_password, show="*").grid(row=2, column=1, sticky=tk.EW)

        ttk.Label(frame, text="Trigger delay (s)").grid(row=3, column=0, sticky=tk.W)
        self.trigger_delay = tk.DoubleVar(value=self.settings.obs.trigger_delay_seconds)
        ttk.Entry(frame, textvariable=self.trigger_delay).grid(row=3, column=1, sticky=tk.EW)

        ttk.Label(frame, text="Capture region").grid(row=4, column=0, sticky=tk.W, pady=(8, 0))
        self.left_var = tk.IntVar(value=region.left)
        self.top_var = tk.IntVar(value=region.top)
        self.width_var = tk.IntVar(value=region.width)
        self.height_var = tk.IntVar(value=region.height)
        coords = ttk.Frame(frame)
        coords.grid(row=5, column=0, columnspan=2, sticky=tk.EW)
        for idx, (label, var) in enumerate(
            [
                ("Left", self.left_var),
                ("Top", self.top_var),
                ("Width", self.width_var),
                ("Height", self.height_var),
            ]
        ):
            ttk.Label(coords, text=label).grid(row=0, column=idx * 2, sticky=tk.W)
            ttk.Entry(coords, textvariable=var, width=8).grid(row=0, column=idx * 2 + 1, padx=(0, 8))

        ttk.Button(frame, text="Pick region from screen", command=self._pick_region).grid(
            row=6, column=0, columnspan=2, sticky=tk.W, pady=6
        )
        return frame

    def _build_medals_tab(self) -> ttk.Frame:
        frame = ttk.Frame(self, padding=8)
        frame.columnconfigure(0, weight=1)
        self.medal_editor = MedalEditor(frame, self.settings.monitor.medals)
        self.medal_editor.grid(row=0, column=0, sticky=tk.NSEW)
        return frame

    def _build_analytics_tab(self) -> ttk.Frame:
        frame = AnalyticsPanel(self, self.settings)
        return frame

    def _pick_region(self) -> None:
        def callback(region: CaptureRegion) -> None:
            self.left_var.set(region.left)
            self.top_var.set(region.top)
            self.width_var.set(region.width)
            self.height_var.set(region.height)

        RegionSelector(self, callback)

    def _save(self) -> None:
        region = CaptureRegion(
            left=self.left_var.get(),
            top=self.top_var.get(),
            width=self.width_var.get(),
            height=self.height_var.get(),
        )
        obs = OBSSettings(
            host=self.obs_host.get(),
            port=self.obs_port.get(),
            password=self.obs_password.get(),
            trigger_delay_seconds=self.trigger_delay.get(),
            filename_format=self.settings.obs.filename_format,
            timestamp_format=self.settings.obs.timestamp_format,
            sanitize_filenames=self.settings.obs.sanitize_filenames,
        )
        monitor = MonitorSettings(
            capture_region=region,
            medals=self.medal_editor.medals,
            sample_rate_hz=self.settings.monitor.sample_rate_hz,
            grayscale=self.settings.monitor.grayscale,
            tesseract_config=self.settings.monitor.tesseract_config,
            detection_buffer_seconds=self.settings.monitor.detection_buffer_seconds,
        )
        self.settings = Settings(obs=obs, monitor=monitor, analytics=self.settings.analytics)
        save_settings(self.settings, self.config_path)
        messagebox.showinfo("Saved", f"Configuration saved to {self.config_path}")


def launch_ui(config_path: Path) -> None:
    logging.basicConfig(level="INFO", format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s")
    app = SettingsApp(config_path)
    app.mainloop()
