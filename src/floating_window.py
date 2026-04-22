"""
翻译悬浮窗模块 - 现代化 UI 组件

核心功能：
1. 显示翻译进度和结果的悬浮窗口
2. 支持流式更新译文内容
3. 圆角、毛玻璃、淡入淡出动画效果
4. 智能定位算法（多显示器支持）
5. DWM API 集成（圆角、阴影）
"""

import ctypes
from ctypes import wintypes
import tkinter as tk
from tkinter import font as tkfont

try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    pass

DWMWA_WINDOW_CORNER_PREFERENCE = 33
DWMWA_USE_IMMERSIVE_DARK_MODE = 20
DWMWCP_ROUND = 2
MONITOR_DEFAULTTONEAREST = 2


class _RECT(ctypes.Structure):
    _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long), ("right", ctypes.c_long), ("bottom", ctypes.c_long)]


class _MONITORINFOEX(ctypes.Structure):
    _fields_ = [
        ("cbSize", ctypes.c_ulong),
        ("rcMonitor", _RECT),
        ("rcWork", _RECT),
        ("dwFlags", ctypes.c_ulong),
        ("szDevice", ctypes.c_wchar * 32),
    ]

COLORS = {
    "bg": "#FAFAFA",
    "title_bg_start": "#1976D2",
    "title_bg_end": "#42A5F5",
    "source_bg": "#F5F5F5",
    "trans_bg": "#FFFFFF",
    "text_primary": "#212121",
    "text_secondary": "#757575",
    "accent": "#1976D2",
    "error": "#D32F2F",
    "success": "#388E3C",
    "border": "#E0E0E0",
    "title_text": "#FFFFFF",
}

FONT_FAMILY = "Microsoft YaHei UI"
ANIMATION_DURATION_MS = 200
ANIMATION_STEPS = 8


class FloatingWindow:
    def __init__(
        self,
        on_copy_callback=None,
        on_pin_callback=None,
        on_close_callback=None,
        auto_hide_delay=3.0,
    ):
        self.on_copy_callback = on_copy_callback
        self.on_pin_callback = on_pin_callback
        self.on_close_callback = on_close_callback
        self.auto_hide_delay = auto_hide_delay
        self._window: tk.Toplevel | None = None
        self._visible = False
        self._pinned = False
        self._alpha = 0.0
        self._animation_id = None
        self._auto_hide_id = None
        self._loading_frame = 0
        self._loading_id = None
        self._drag_data = {"start_x": 0, "start_y": 0, "win_x": 0, "win_y": 0}
        self._status_label: tk.Label | None = None
        self._translation_text: tk.Text | None = None
        self._bottom_status: tk.Label | None = None
        self._pin_btn: tk.Button | None = None
        self._copy_btn: tk.Button | None = None
        self._loading_dots: list[tk.Label] = []

    def _create_window(self):
        if self._window is not None and self._window.winfo_exists():
            return
        self._window = tk.Toplevel()
        self._window.overrideredirect(True)
        self._window.attributes("-topmost", True)
        self._window.attributes("-toolwindow", True)
        self._window.attributes("-alpha", 0.0)
        self._window.configure(bg=COLORS["bg"])
        self._apply_dwm_effects()
        self._build_ui()
        self._bind_events()

    def _apply_dwm_effects(self):
        if self._window is None:
            return
        try:
            hwnd = ctypes.windll.user32.GetParent(self._window.winfo_id())
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, DWMWA_WINDOW_CORNER_PREFERENCE, ctypes.byref(ctypes.c_int(DWMWCP_ROUND)), ctypes.sizeof(ctypes.c_int)
            )
        except Exception:
            pass

    def _build_ui(self):
        if self._window is None:
            return
        root = self._container = tk.Frame(self._window, bg=COLORS["bg"], highlightthickness=1, highlightbackground=COLORS["border"])
        root.pack(fill=tk.BOTH, expand=True, padx=2, pady=2)
        self._build_title_bar(root)
        self._build_source_area(root)
        self._build_separator(root)
        self._build_translation_area(root)
        self._build_bottom_bar(root)

    def _build_title_bar(self, parent):
        frame = tk.Frame(parent, bg=COLORS["title_bg_start"], height=36)
        frame.pack(fill=tk.X)
        frame.pack_propagate(False)
        title_font = tkfont.Font(family=FONT_FAMILY, size=10, weight="bold")
        btn_font = tkfont.Font(family=FONT_FAMILY, size=9)
        left_area = tk.Frame(frame, bg=COLORS["title_bg_start"])
        left_area.pack(side=tk.LEFT, fill=tk.Y, padx=(12, 0))
        tk.Label(left_area, text="Type4Y", font=title_font, fg=COLORS["title_text"], bg=COLORS["title_bg_start"]).pack(side=tk.LEFT)
        self._status_label = tk.Label(
            left_area, text="", font=tkfont.Font(family=FONT_FAMILY, size=9),
            fg="#B3E5FC", bg=COLORS["title_bg_start"]
        )
        self._status_label.pack(side=tk.LEFT, padx=(8, 0))
        right_area = tk.Frame(frame, bg=COLORS["title_bg_start"])
        right_area.pack(side=tk.RIGHT, fill=tk.Y, padx=(0, 6))
        self._pin_btn = tk.Button(
            right_area, text="📌", font=btn_font, fg=COLORS["title_text"],
            bg=COLORS["title_bg_start"], activebackground=COLORS["title_bg_end"],
            activeforeground=COLORS["title_text"], relief=tk.FLAT, cursor="hand2",
            bd=0, padx=6, pady=2, command=self._toggle_pin
        )
        self._pin_btn.pack(side=tk.LEFT, padx=2)
        close_btn = tk.Button(
            right_area, text="✕", font=tkfont.Font(family=FONT_FAMILY, size=9, weight="bold"),
            fg=COLORS["title_text"], bg=COLORS["title_bg_start"],
            activebackground="#E53935", activeforeground=COLORS["title_text"],
            relief=tk.FLAT, cursor="hand2", bd=0, padx=8, pady=2, command=self._on_close_click
        )
        close_btn.pack(side=tk.LEFT, padx=2)
        frame.bind("<ButtonPress-1>", self._on_drag_start)
        left_area.bind("<ButtonPress-1>", self._on_drag_start)
        for child in left_area.winfo_children():
            child.bind("<ButtonPress-1>", self._on_drag_start)

    def _build_source_area(self, parent):
        outer = tk.Frame(parent, bg=COLORS["source_bg"], padx=12, pady=10)
        outer.pack(fill=tk.X, padx=4, pady=(4, 0))
        header = tk.Frame(outer, bg=COLORS["source_bg"])
        header.pack(fill=tk.X, pady=(0, 6))
        tk.Label(
            header, text="原文", font=tkfont.Font(family=FONT_FAMILY, size=9),
            fg=COLORS["text_secondary"], bg=COLORS["source_bg"], anchor=tk.W
        ).pack(side=tk.LEFT)
        char_count = tk.Label(
            header, text="", font=tkfont.Font(family=FONT_FAMILY, size=9),
            fg=COLORS["text_secondary"], bg=COLORS["source_bg"]
        )
        char_count.pack(side=tk.RIGHT)
        self._source_label = tk.Label(
            outer, text="", font=tkfont.Font(family=FONT_FAMILY, size=11),
            fg=COLORS["text_primary"], bg=COLORS["source_bg"], justify=tk.LEFT,
            anchor=tk.NW, wraplength=420
        )
        self._source_label.pack(fill=tk.X)
        self._char_count_label = char_count

    def _build_separator(self, parent):
        sep = tk.Frame(parent, height=1, bg=COLORS["border"])
        sep.pack(fill=tk.X, padx=8, pady=4)

    def _build_translation_area(self, parent):
        outer = tk.Frame(parent, bg=COLORS["trans_bg"], padx=12, pady=10)
        outer.pack(fill=tk.BOTH, expand=True, padx=4, pady=(0, 4))
        tk.Label(
            outer, text="译文", font=tkfont.Font(family=FONT_FAMILY, size=9),
            fg=COLORS["text_secondary"], bg=COLORS["trans_bg"], anchor=tk.W
        ).pack(anchor=tk.W, pady=(0, 6))
        text_frame = tk.Frame(outer, bg=COLORS["trans_bg"])
        text_frame.pack(fill=tk.BOTH, expand=True)
        self._translation_text = tk.Text(
            text_frame, font=tkfont.Font(family=FONT_FAMILY, size=11),
            fg=COLORS["text_primary"], bg=COLORS["trans_bg"],
            relief=tk.FLAT, wrap=tk.WORD, height=3, state=tk.DISABLED,
            padx=0, pady=0, highlightthickness=0, spacing1=2, spacing2=2
        )
        self._translation_text.pack(fill=tk.BOTH, expand=True)
        loading_frame = tk.Frame(outer, bg=COLORS["trans_bg"])
        loading_frame.pack(fill=tk.X, pady=(6, 0))
        self._loading_dots = []
        dot_colors = [COLORS["accent"], COLORS["accent"], COLORS["accent"]]
        for i in range(3):
            dot = tk.Label(
                loading_frame, text="●", font=tkfont.Font(family=FONT_FAMILY, size=10),
                fg=dot_colors[i], bg=COLORS["trans_bg"]
            )
            dot.pack(side=tk.LEFT, padx=2)
            self._loading_dots.append(dot)
        self._loading_outer = outer
        self._hide_loading()

    def _build_bottom_bar(self, parent):
        bar = tk.Frame(parent, bg=COLORS["bg"], height=36)
        bar.pack(fill=tk.X, padx=4, pady=(0, 4))
        bar.pack_propagate(False)
        left = tk.Frame(bar, bg=COLORS["bg"])
        left.pack(side=tk.LEFT, fill=tk.Y, padx=12)
        self._copy_btn = tk.Button(
            left, text="📋 复制译文", font=tkfont.Font(family=FONT_FAMILY, size=9),
            fg=COLORS["accent"], bg=COLORS["bg"], activebackground=COLORS["trans_bg"],
            activeforeground=COLORS["accent"], relief=tk.FLAT, cursor="hand2",
            bd=0, padx=10, pady=4, command=self._on_copy_click
        )
        self._copy_btn.pack(side=tk.LEFT)
        right = tk.Frame(bar, bg=COLORS["bg"])
        right.pack(side=tk.RIGHT, fill=tk.Y, padx=(0, 12))
        self._bottom_status = tk.Label(
            right, text="", font=tkfont.Font(family=FONT_FAMILY, size=9),
            fg=COLORS["text_secondary"], bg=COLORS["bg"]
        )
        self._bottom_status.pack(side=tk.RIGHT)

    def _bind_events(self):
        if self._window is None:
            return
        self._window.bind("<B1-Motion>", self._on_drag_motion)
        self._window.bind("<ButtonRelease-1>", lambda e: None)
        self._window.bind("<Enter>", self._cancel_auto_hide)
        self._window.bind("<Leave>", self._schedule_auto_hide)

    def show(self, source_text: str, cursor_x: int, cursor_y: int):
        self._cancel_auto_hide()
        self._stop_animation()
        self._stop_loading()
        self._pinned = False
        self._update_pin_button()
        self._create_window()
        if self._window is None or not self._window.winfo_exists():
            return
        display_text = source_text[:500] + ("..." if len(source_text) > 500 else "")
        self._source_label.config(text=display_text)
        self._char_count_label.config(text=f"{len(source_text)} 字符")
        self._set_translation_content("")
        self._show_loading()
        self._set_status("翻译中...", COLORS["accent"])
        self._bottom_status.config(text="")
        self._copy_btn.config(state=tk.NORMAL)
        x, y = self._calculate_position(cursor_x, cursor_y)
        base_width = 480
        base_height = self._estimate_height(source_text)
        self._window.geometry(f"{base_width}x{base_height}+{x}+{y}")
        self._window.deiconify()
        self._window.lift()
        self._visible = True
        self._animate_alpha(target=1.0)
        self._start_loading_animation()

    def update_translation(self, partial_text: str):
        if self._translation_text is None:
            return
        if self._window is None or not self._window.winfo_exists():
            return
        self._window.after(0, lambda: self._do_update_translation(partial_text))

    def _do_update_translation(self, text: str):
        if self._translation_text is None or self._window is None or not self._window.winfo_exists():
            return
        self._set_translation_content(text)
        self._adjust_window_size()

    def set_done(self, final_text: str):
        if self._window is None or not self._window.winfo_exists():
            return
        self._window.after(0, lambda: self._do_set_done(final_text))

    def _do_set_done(self, final_text: str):
        if self._window is None or not self._window.winfo_exists():
            return
        self._stop_loading()
        self._hide_loading()
        self._set_translation_content(final_text)
        self._set_status("完成 ✓", COLORS["success"])
        self._bottom_status.config(text="翻译完成")
        self._adjust_window_size()
        self._schedule_auto_hide()

    def set_error(self, error_msg: str):
        if self._window is None or not self._window.winfo_exists():
            return
        self._window.after(0, lambda: self._do_set_error(error_msg))

    def _do_set_error(self, error_msg: str):
        if self._window is None or not self._window.winfo_exists():
            return
        self._stop_loading()
        self._hide_loading()
        self._set_translation_content(error_msg)
        self._set_status("错误 ✗", COLORS["error"])
        self._bottom_status.config(text=f"翻译失败: {error_msg}")
        self._copy_btn.config(state=tk.DISABLED)
        self._schedule_auto_hide()

    def hide(self):
        if not self._visible:
            return
        self._cancel_auto_hide()
        self._stop_loading()
        self._stop_animation()
        self._animate_alpha(target=0.0, callback=self._destroy_window)

    def _calculate_position(self, cursor_x: int, cursor_y: int) -> tuple[int, int]:
        offset_x, offset_y = 20, 20
        preferred_x = cursor_x + offset_x
        preferred_y = cursor_y + offset_y
        win_width, win_height = 480, 300
        screen_w = ctypes.windll.user32.GetSystemMetrics(0)
        screen_h = ctypes.windll.user32.GetSystemMetrics(1)
        point = wintypes.POINT(cursor_x, cursor_y)
        monitor = ctypes.windll.user32.MonitorFromPoint(point, MONITOR_DEFAULTTONEAREST)
        monitor_info = _MONITORINFOEX()
        monitor_info.cbSize = ctypes.sizeof(monitor_info)
        ctypes.windll.user32.GetMonitorInfoW(monitor, ctypes.byref(monitor_info))
        mon_left = monitor_info.rcMonitor.left
        mon_top = monitor_info.rcMonitor.top
        mon_right = monitor_info.rcMonitor.right
        mon_bottom = monitor_info.rcMonitor.bottom
        mon_w = mon_right - mon_left
        mon_h = mon_bottom - mon_top
        if preferred_x + win_width > mon_right:
            preferred_x = cursor_x - win_width - offset_x
        if preferred_y + win_height > mon_bottom:
            preferred_y = cursor_y - win_height - offset_y
        preferred_x = max(mon_left, min(preferred_x, mon_right - win_width))
        preferred_y = max(mon_top, min(preferred_y, mon_bottom - win_height))
        return preferred_x, preferred_y

    def _estimate_height(self, source_text: str) -> int:
        base = 220
        lines = max(1, len(source_text) // 50)
        extra = min(lines * 18, 120)
        return base + extra

    def _set_translation_content(self, text: str):
        if self._translation_text is None:
            return
        self._translation_text.config(state=tk.NORMAL)
        self._translation_text.delete("1.0", tk.END)
        self._translation_text.insert("1.0", text)
        self._translation_text.config(state=tk.DISABLED)

    def _set_status(self, text: str, color: str):
        if self._status_label is not None:
            self._status_label.config(text=text, fg=color)

    def _adjust_window_size(self):
        if self._window is None or not self._window.winfo_exists():
            return
        self._window.update_idletasks()
        req_w = self._container.winfo_reqwidth() + 4
        req_h = self._container.winfo_reqheight() + 4
        cur_geo = self._window.geometry().split("+")
        cur_w, cur_h = map(int, cur_geo[0].split("x"))
        new_w = max(cur_w, req_w)
        new_h = max(cur_h, req_h)
        pos = "+" + "+".join(cur_geo[1:]) if len(cur_geo) > 1 else ""
        self._window.geometry(f"{new_w}x{new_h}{pos}")

    def _animate_alpha(self, target: float, callback=None):
        start = self._alpha
        diff = target - start
        step = diff / ANIMATION_STEPS
        current_step = [0]

        def step_animate():
            current_step[0] += 1
            if current_step[0] <= ANIMATION_STEPS:
                self._alpha = start + step * current_step[0]
                self._alpha = max(0.0, min(1.0, self._alpha))
                if self._window is not None and self._window.winfo_exists():
                    self._window.attributes("-alpha", self._alpha)
                self._animation_id = self._window.after(int(ANIMATION_DURATION_MS / ANIMATION_STEPS), step_animate)
            else:
                self._alpha = target
                if self._window is not None and self._window.winfo_exists():
                    self._window.attributes("-alpha", target)
                self._animation_id = None
                if callback is not None:
                    callback()

        self._animation_id = self._window.after(int(ANIMATION_DURATION_MS / ANIMATION_STEPS), step_animate)

    def _stop_animation(self):
        if self._animation_id is not None and self._window is not None:
            try:
                self._window.after_cancel(self._animation_id)
            except Exception:
                pass
            self._animation_id = None

    def _show_loading(self):
        for dot in self._loading_dots:
            dot.pack_configure(before=None)

    def _hide_loading(self):
        for dot in self._loading_dots:
            dot.pack_forget()

    def _start_loading_animation(self):
        self._loading_frame = 0
        self._do_loading_frame()

    def _do_loading_frame(self):
        if not self._visible or self._window is None:
            return
        for i, dot in enumerate(self._loading_dots):
            phase = (self._loading_frame + i) % 9
            if phase < 3:
                alpha_hex = "CC"
            elif phase < 6:
                alpha_hex = "66"
            else:
                alpha_hex = "22"
            base_color = COLORS["accent"]
            r, g, b = int(base_color[1:3], 16), int(base_color[3:5], 16), int(base_color[5:7], 16)
            dot.config(fg=f"#{r:02X}{g:02X}{b:02X}")
        self._loading_frame += 1
        self._loading_id = self._window.after(150, self._do_loading_frame)

    def _stop_loading(self):
        if self._loading_id is not None and self._window is not None:
            try:
                self._window.after_cancel(self._loading_id)
            except Exception:
                pass
            self._loading_id = None

    def _schedule_auto_hide(self):
        if self._pinned:
            return
        self._cancel_auto_hide()
        delay_ms = int(self.auto_hide_delay * 1000)
        self._auto_hide_id = self._window.after(delay_ms, self.hide)

    def _cancel_auto_hide(self):
        if self._auto_hide_id is not None and self._window is not None:
            try:
                self._window.after_cancel(self._auto_hide_id)
            except Exception:
                pass
            self._auto_hide_id = None

    def _destroy_window(self):
        self._visible = False
        if self._window is not None and self._window.winfo_exists():
            try:
                self._window.destroy()
            except Exception:
                pass
        self._window = None

    def _toggle_pin(self):
        self._pinned = not self._pinned
        self._update_pin_button()
        if self._pinned:
            self._cancel_auto_hide()
            self._bottom_status.config(text="已固定")
        else:
            self._schedule_auto_hide()
        if self.on_pin_callback:
            self.on_pin_callback(self._pinned)

    def _update_pin_button(self):
        if self._pin_btn is None:
            return
        if self._pinned:
            self._pin_btn.config(text="📌", foreground="#FFEB3B")
        else:
            self._pin_btn.config(text="📍", foreground=COLORS["title_text"])

    def _on_copy_click(self):
        if self._translation_text is None:
            return
        text = self._translation_text.get("1.0", tk.END).strip()
        if text and self.on_copy_callback:
            self.on_copy_callback(text)
            self._bottom_status.config(text="已复制到剪贴板")

    def _on_close_click(self):
        if self.on_close_callback:
            self.on_close_callback()
        self.hide()

    def _on_drag_start(self, event):
        self._drag_data["start_x"] = event.x
        self._drag_data["start_y"] = event.y
        if self._window is not None:
            geo = self._window.geometry().split("+")
            if len(geo) >= 3:
                self._drag_data["win_x"] = int(geo[1])
                self._drag_data["win_y"] = int(geo[2])

    def _on_drag_motion(self, event):
        if self._window is None:
            return
        dx = event.x - self._drag_data["start_x"]
        dy = event.y - self._drag_data["start_y"]
        new_x = self._drag_data["win_x"] + dx
        new_y = self._drag_data["win_y"] + dy
        cur_geo = self._window.geometry().split("+")[0]
        self._window.geometry(f"{cur_geo}+{int(new_x)}+{int(new_y)}")
