from __future__ import annotations

import logging
import tkinter as tk
from pathlib import Path
from tkinter import font as tkfont, messagebox, ttk
from typing import Callable, Dict, List, Optional, Sequence, Tuple

import mss
import numpy as np
from PIL import Image, ImageTk

try:
    import pygetwindow as gw
except Exception:  # pragma: no cover - optional dependency at runtime
    gw = None

try:
    import ttkbootstrap as tb
except Exception:  # pragma: no cover - optional dependency at runtime
    tb = None

from halo_clip_creator.analytics import load_history, load_session_summary
from halo_clip_creator.config import (
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


def _list_windows(filter_hint: Optional[str] = None) -> Dict[str, Tuple[int, int, int, int]]:
    """Return a mapping of window titles to geometry, filtered toward Halo by default."""

    if gw is None:
        LOGGER.info("pygetwindow not available; window auto-detection disabled")
        return {}

    windows: Dict[str, Tuple[int, int, int, int]] = {}
    try:
        for window in gw.getAllWindows():
            title = (window.title or "").strip()
            if not title or window.isMinimized or not window.isVisible:
                continue
            geometry = (window.left, window.top, window.width, window.height)
            windows[title] = geometry
    except Exception:  # pragma: no cover - depends on OS window APIs
        LOGGER.exception("Unable to enumerate windows for auto-detection")
        return {}

    if filter_hint:
        lowered = filter_hint.lower()
        filtered = {t: g for t, g in windows.items() if lowered in t.lower()}
        if filtered:
            return filtered
    return windows


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
        super().__init__(master, padding=16, style="Surface.TFrame")
        self.settings = settings
        self.session_payload: Optional[dict] = None
        self.history_payload: List[dict] = []
        self._build()
        self.refresh()

    def _build(self) -> None:
        self.columnconfigure(0, weight=1)

        header = ttk.Label(self, text="Live analytics", style="Heading.TLabel")
        header.grid(row=0, column=0, sticky=tk.W, pady=(0, 8))

        self.stats_frame = ttk.Frame(self, style="Surface.TFrame")
        self.stats_frame.grid(row=1, column=0, sticky=tk.EW)
        self.stats_frame.columnconfigure((0, 1, 2), weight=1)

        self.stat_cards = {
            "clips": self._build_stat_card(self.stats_frame, 0, "Clips captured", "0"),
            "medals": self._build_stat_card(self.stats_frame, 1, "Medals seen", "0"),
            "pace": self._build_stat_card(self.stats_frame, 2, "Medals/min", "0.0"),
        }

        chart_frame = ttk.Frame(self, padding=12, style="Card.TFrame")
        chart_frame.grid(row=2, column=0, sticky=tk.NSEW, pady=(12, 8))
        chart_frame.columnconfigure(0, weight=1)
        ttk.Label(chart_frame, text="Medal distribution", style="CardHeading.TLabel").grid(
            row=0, column=0, sticky=tk.W
        )
        self.medal_tree = ttk.Treeview(
            chart_frame,
            columns=("medal", "count", "share"),
            show="headings",
            height=6,
            style="Treeview",
        )
        self.medal_tree.heading("medal", text="Medal")
        self.medal_tree.heading("count", text="Count")
        self.medal_tree.heading("share", text="Share")
        self.medal_tree.column("medal", width=180)
        self.medal_tree.column("count", anchor=tk.CENTER, width=80)
        self.medal_tree.column("share", anchor=tk.CENTER, width=100)
        self.medal_tree.grid(row=1, column=0, sticky=tk.NSEW, pady=(6, 0))

        history_frame = ttk.Frame(self, padding=12, style="Card.TFrame")
        history_frame.grid(row=3, column=0, sticky=tk.NSEW)
        history_frame.columnconfigure(0, weight=1)
        ttk.Label(history_frame, text="Latest sessions", style="CardHeading.TLabel").grid(
            row=0, column=0, sticky=tk.W
        )
        self.history_tree = ttk.Treeview(
            history_frame,
            columns=("session", "clips", "medals"),
            show="headings",
            height=5,
            style="Treeview",
        )
        self.history_tree.heading("session", text="Session")
        self.history_tree.heading("clips", text="Clips")
        self.history_tree.heading("medals", text="Unique medals")
        self.history_tree.column("session", width=220)
        self.history_tree.column("clips", anchor=tk.CENTER, width=80)
        self.history_tree.column("medals", anchor=tk.CENTER, width=120)
        self.history_tree.grid(row=1, column=0, sticky=tk.NSEW, pady=(6, 0))

        ttk.Button(self, text="Refresh analytics", style="Primary.TButton", command=self.refresh).grid(
            row=4, column=0, sticky=tk.E, pady=(12, 0)
        )

    def _build_stat_card(self, master: tk.Misc, column: int, title: str, value: str) -> Dict[str, tk.Widget]:
        card = ttk.Frame(master, padding=14, style="Card.TFrame")
        card.grid(row=0, column=column, sticky=tk.EW, padx=(0 if column == 0 else 10, 0))
        ttk.Label(card, text=title, style="CardHeading.TLabel").pack(anchor=tk.W)
        value_label = ttk.Label(card, text=value, style="CardValue.TLabel")
        value_label.pack(anchor=tk.W, pady=(6, 0))
        return {"frame": card, "value": value_label}

    def refresh(self) -> None:
        self.session_payload = load_session_summary(self.settings.analytics.session_summary_path)
        self.history_payload = load_history(self.settings.analytics.history_path)
        self._render_stats()
        self._render_medals()
        self._render_history()

    def _render_stats(self) -> None:
        payload = self.session_payload or {}
        medal_counts = payload.get("medal_counts", {})
        duration = float(payload.get("session_duration_seconds", 0.0))
        total_medals = sum(medal_counts.values())
        pace = (total_medals / (duration / 60)) if duration > 0 else 0.0

        stats = {
            "clips": payload.get("total_clips", 0),
            "medals": total_medals,
            "pace": f"{pace:.1f}",
        }
        for key, value in stats.items():
            self.stat_cards[key]["value"].configure(text=str(value))

    def _render_medals(self) -> None:
        for item in self.medal_tree.get_children():
            self.medal_tree.delete(item)

        payload = self.session_payload or {}
        medal_counts = payload.get("medal_counts", {})
        total = sum(medal_counts.values()) or 1
        if not medal_counts:
            self.medal_tree.insert("", tk.END, values=("No medals yet", "-", "-"))
            return

        for medal, count in sorted(medal_counts.items(), key=lambda item: item[1], reverse=True):
            share = f"{(count / total) * 100:0.1f}%"
            self.medal_tree.insert("", tk.END, values=(medal, count, share))

    def _render_history(self) -> None:
        for item in self.history_tree.get_children():
            self.history_tree.delete(item)

        if not self.history_payload:
            self.history_tree.insert("", tk.END, values=("No history yet", "-", "-"))
            return

        for entry in self.history_payload[-5:]:
            self.history_tree.insert(
                "",
                tk.END,
                values=(
                    entry.get("session_name", "session"),
                    entry.get("total_clips", 0),
                    len(entry.get("medal_counts", {})),
                ),
            )


class SettingsApp(tb.Window if tb else tk.Tk):
    def __init__(self, config_path: Path):
        if tb:
            super().__init__(themename="cyborg")
        else:
            super().__init__()
        self.title("Halo Infinite Clip Creator")
        self.config_path = config_path
        self.settings = self._load()
        self.window_lookup: Dict[str, Tuple[int, int, int, int]] = {}
        self._init_style()
        self._build_ui()

    def _init_style(self) -> None:
        self.colors = {
            "background": "#0b1021",
            "card": "#121a2f",
            "accent": "#6ee7ff",
            "text": "#e2e8f0",
        }
        self.configure(bg=self.colors["background"])
        style = ttk.Style(self)
        if tb:
            style.theme_use("cyborg")
        style.configure("Surface.TFrame", background=self.colors["background"])
        style.configure("Card.TFrame", background=self.colors["card"], relief=tk.FLAT)
        style.configure("Heading.TLabel", background=self.colors["background"], foreground=self.colors["text"], font=("Segoe UI", 18, "bold"))
        style.configure("CardHeading.TLabel", background=self.colors["card"], foreground=self.colors["accent"], font=("Segoe UI", 10, "bold"))
        style.configure("CardValue.TLabel", background=self.colors["card"], foreground=self.colors["text"], font=("Segoe UI", 18, "bold"))
        style.configure("Primary.TButton", padding=6)
        default_font = tkfont.nametofont("TkDefaultFont")
        default_font.configure(size=10, family="Segoe UI")

    def _load(self) -> Settings:
        try:
            return load_settings(self.config_path)
        except FileNotFoundError:
            LOGGER.info("Config %s not found, loading defaults", self.config_path)
            return default_settings()

    def _build_ui(self) -> None:
        container = ttk.Frame(self, padding=16, style="Surface.TFrame")
        container.pack(fill=tk.BOTH, expand=True)
        container.columnconfigure(0, weight=1)
        container.rowconfigure(1, weight=1)

        self._build_header(container)

        notebook = ttk.Notebook(container)
        notebook.grid(row=1, column=0, sticky=tk.NSEW)

        notebook.add(self._build_capture_tab(notebook), text="Capture")
        notebook.add(self._build_medals_tab(notebook), text="Medals")
        notebook.add(self._build_analytics_tab(notebook), text="Analytics")

        save_frame = ttk.Frame(container, padding=8, style="Surface.TFrame")
        save_frame.grid(row=2, column=0, sticky=tk.EW, pady=(12, 0))
        ttk.Label(save_frame, text=f"Config: {self.config_path}", foreground=self.colors["text"], background=self.colors["background"]).pack(side=tk.LEFT)
        ttk.Button(save_frame, text="Save configuration", style="Primary.TButton", command=self._save).pack(side=tk.RIGHT)

    def _build_header(self, master: tk.Misc) -> None:
        hero = ttk.Frame(master, padding=12, style="Surface.TFrame")
        hero.grid(row=0, column=0, sticky=tk.EW, pady=(0, 12))
        hero.columnconfigure(0, weight=1)
        ttk.Label(hero, text="Halo Infinite Clip Creator", style="Heading.TLabel").grid(row=0, column=0, sticky=tk.W)
        ttk.Label(
            hero,
            text="Select the Halo window, dial in medals, and monitor your streaks in one high-tech control deck.",
            background=self.colors["background"],
            foreground=self.colors["text"],
        ).grid(row=1, column=0, sticky=tk.W)

    def _build_capture_tab(self, master: tk.Misc) -> ttk.Frame:
        frame = ttk.Frame(master, padding=12, style="Surface.TFrame")
        frame.columnconfigure(1, weight=1)
        region = self.settings.monitor.capture_region

        connection_card = ttk.Frame(frame, padding=14, style="Card.TFrame")
        connection_card.grid(row=0, column=0, columnspan=2, sticky=tk.EW, pady=(0, 12))
        connection_card.columnconfigure(1, weight=1)
        ttk.Label(connection_card, text="OBS connection", style="CardHeading.TLabel").grid(row=0, column=0, columnspan=2, sticky=tk.W, pady=(0, 8))
        self.obs_host = tk.StringVar(value=self.settings.obs.host)
        self.obs_port = tk.IntVar(value=self.settings.obs.port)
        self.obs_password = tk.StringVar(value=self.settings.obs.password)
        self.trigger_delay = tk.DoubleVar(value=self.settings.obs.trigger_delay_seconds)
        for idx, (label, var) in enumerate(
            [
                ("OBS host", self.obs_host),
                ("OBS port", self.obs_port),
                ("OBS password", self.obs_password),
                ("Trigger delay (s)", self.trigger_delay),
            ]
        ):
            ttk.Label(connection_card, text=label, background=self.colors["card"], foreground=self.colors["text"]).grid(
                row=idx + 1, column=0, sticky=tk.W, pady=2
            )
            show = "*" if label == "OBS password" else None
            ttk.Entry(connection_card, textvariable=var, show=show).grid(row=idx + 1, column=1, sticky=tk.EW, pady=2)

        region_card = ttk.Frame(frame, padding=14, style="Card.TFrame")
        region_card.grid(row=1, column=0, columnspan=2, sticky=tk.NSEW)
        region_card.columnconfigure(1, weight=1)
        ttk.Label(region_card, text="Capture region", style="CardHeading.TLabel").grid(row=0, column=0, sticky=tk.W)
        self.left_var = tk.IntVar(value=region.left)
        self.top_var = tk.IntVar(value=region.top)
        self.width_var = tk.IntVar(value=region.width)
        self.height_var = tk.IntVar(value=region.height)
        coords = ttk.Frame(region_card, style="Card.TFrame")
        coords.grid(row=1, column=0, columnspan=2, sticky=tk.EW, pady=(6, 4))
        for idx, (label, var) in enumerate(
            [
                ("Left", self.left_var),
                ("Top", self.top_var),
                ("Width", self.width_var),
                ("Height", self.height_var),
            ]
        ):
            ttk.Label(coords, text=label, background=self.colors["card"], foreground=self.colors["text"]).grid(
                row=0, column=idx * 2, sticky=tk.W, padx=(0, 4)
            )
            ttk.Entry(coords, textvariable=var, width=8).grid(row=0, column=idx * 2 + 1, padx=(0, 10))

        ttk.Button(region_card, text="Pick region from screen", style="Primary.TButton", command=self._pick_region).grid(
            row=2, column=0, sticky=tk.W
        )

        self.window_hint = tk.StringVar(value=self.settings.monitor.preferred_window_title or "Halo Infinite")
        window_card = ttk.Frame(frame, padding=14, style="Card.TFrame")
        window_card.grid(row=2, column=0, columnspan=2, sticky=tk.NSEW, pady=(12, 0))
        window_card.columnconfigure(1, weight=1)
        ttk.Label(window_card, text="Halo window auto-detect", style="CardHeading.TLabel").grid(row=0, column=0, sticky=tk.W)
        ttk.Label(
            window_card,
            text="Scan for a running Halo Infinite window and snap the capture region to it.",
            background=self.colors["card"],
            foreground=self.colors["text"],
        ).grid(row=1, column=0, columnspan=2, sticky=tk.W)
        ttk.Label(window_card, text="Window title", background=self.colors["card"], foreground=self.colors["text"]).grid(
            row=2, column=0, sticky=tk.W, pady=(6, 0)
        )
        self.window_combo = ttk.Combobox(window_card, textvariable=self.window_hint, state="readonly")
        self.window_combo.grid(row=2, column=1, sticky=tk.EW, pady=(6, 0))
        button_bar = ttk.Frame(window_card, style="Card.TFrame")
        button_bar.grid(row=3, column=0, columnspan=2, sticky=tk.E, pady=(6, 0))
        ttk.Button(button_bar, text="Scan", style="Primary.TButton", command=self._scan_windows).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(button_bar, text="Snap to window", command=self._apply_window_region).pack(side=tk.LEFT)
        return frame

    def _build_medals_tab(self, master: tk.Misc) -> ttk.Frame:
        frame = ttk.Frame(master, padding=12, style="Surface.TFrame")
        frame.columnconfigure(0, weight=1)
        self.medal_editor = MedalEditor(frame, self.settings.monitor.medals)
        self.medal_editor.grid(row=0, column=0, sticky=tk.NSEW)
        return frame

    def _build_analytics_tab(self, master: tk.Misc) -> ttk.Frame:
        frame = AnalyticsPanel(master, self.settings)
        return frame

    def _pick_region(self) -> None:
        def callback(region: CaptureRegion) -> None:
            self.left_var.set(region.left)
            self.top_var.set(region.top)
            self.width_var.set(region.width)
            self.height_var.set(region.height)

        RegionSelector(self, callback)

    def _scan_windows(self) -> None:
        hint = self.window_hint.get().strip() or None
        windows = _list_windows(hint)
        if not windows:
            messagebox.showwarning("No windows", "No active windows found that match Halo. Launch the game and try again.")
            self.window_lookup = {}
            self.window_combo["values"] = []
            return
        self.window_lookup = windows
        titles = sorted(windows.keys())
        self.window_combo["values"] = titles
        preferred = self.settings.monitor.preferred_window_title
        if preferred and preferred in windows:
            self.window_combo.set(preferred)
        else:
            self.window_combo.set(titles[0])
        self._apply_window_region()

    def _apply_window_region(self) -> None:
        title = self.window_hint.get().strip()
        if not title or title not in self.window_lookup:
            messagebox.showinfo("Select a window", "Choose a detected Halo window before snapping the region.")
            return
        left, top, width, height = self.window_lookup[title]
        self.left_var.set(int(left))
        self.top_var.set(int(top))
        self.width_var.set(int(width))
        self.height_var.set(int(height))

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
            preferred_window_title=self.window_hint.get().strip() or None,
        )
        self.settings = Settings(obs=obs, monitor=monitor, analytics=self.settings.analytics)
        save_settings(self.settings, self.config_path)
        messagebox.showinfo("Saved", f"Configuration saved to {self.config_path}")


def launch_ui(config_path: Path) -> None:
    logging.basicConfig(level="INFO", format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s")
    app = SettingsApp(config_path)
    app.mainloop()
