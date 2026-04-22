import json
import os
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from typing import Any, Callable, Dict, Optional
from src.app_settings import DEFAULT_CONFIG, get_default_config
from src.logger import get_logger

logger = get_logger("config_ui")


class ConfigUI:
    def __init__(self, config_path: str, on_save: Optional[Callable] = None):
        self.config_path = config_path
        self.on_save = on_save
        self.config: Dict[str, Any] = get_default_config()
        self.window: Optional[tk.Tk] = None
        self._load_config()

    def _load_config(self) -> None:
        try:
            if os.path.exists(self.config_path):
                with open(self.config_path, 'r', encoding='utf-8') as f:
                    loaded_config = json.load(f)
                self.config.update(loaded_config)
                logger.debug("配置加载成功")
            else:
                logger.warning(f"配置文件不存在: {self.config_path}")
        except Exception as e:
            logger.error(f"加载配置失败: {e}", exc_info=True)
            self.config = get_default_config()

    def _save_config(self) -> None:
        try:
            with open(self.config_path, 'w', encoding='utf-8') as f:
                json.dump(self.config, f, indent=2, ensure_ascii=False)
            logger.info("配置保存成功")
            if self.on_save:
                self.on_save()
            messagebox.showinfo("成功", "配置已保存！")
        except Exception as e:
            logger.error(f"保存配置失败: {e}", exc_info=True)
            messagebox.showerror("错误", f"保存配置失败: {e}")

    def _browse_python_path(self) -> None:
        file_path = filedialog.askopenfilename(
            title="选择本地环境 Python",
            filetypes=[("Python 可执行文件", "python.exe"), ("所有文件", "*.*")],
        )
        if file_path:
            self.python_path_entry.delete(0, tk.END)
            self.python_path_entry.insert(0, file_path)

    def _browse_model_path(self) -> None:
        file_path = filedialog.askopenfilename(
            title="选择 GGUF 模型文件",
            filetypes=[("GGUF 模型", "*.gguf"), ("所有文件", "*.*")],
        )
        if file_path:
            self.model_path_entry.delete(0, tk.END)
            self.model_path_entry.insert(0, file_path)

    def _restore_defaults(self) -> None:
        defaults = DEFAULT_CONFIG.copy()
        self.model_entry.delete(0, tk.END)
        self.model_entry.insert(0, defaults["model"])
        self.python_path_entry.delete(0, tk.END)
        self.python_path_entry.insert(0, defaults["python_path"])
        self.model_path_entry.delete(0, tk.END)
        self.model_path_entry.insert(0, defaults["model_path"])
        self.temp_entry.delete(0, tk.END)
        self.temp_entry.insert(0, str(defaults["temperature"]))
        self.max_tokens_entry.delete(0, tk.END)
        self.max_tokens_entry.insert(0, str(defaults["max_tokens"]))
        self.context_entry.delete(0, tk.END)
        self.context_entry.insert(0, str(defaults["context_length"]))
        self.threads_entry.delete(0, tk.END)
        self.threads_entry.insert(0, str(defaults["threads"]))
        self.batch_entry.delete(0, tk.END)
        self.batch_entry.insert(0, str(defaults["batch_size"]))
        self.prompt_text.delete("1.0", tk.END)
        self.prompt_text.insert("1.0", defaults["prompt"])
        self.floating_enabled_var.set(True)
        self.floating_delay_entry.delete(0, tk.END)
        self.floating_delay_entry.insert(0, "3.0")
        self.floating_opacity_entry.delete(0, tk.END)
        self.floating_opacity_entry.insert(0, "0.95")
        self.warmup_var.set(True)

    def _get_float(self, entry: ttk.Entry, default: float, field_name: str) -> float:
        try:
            return float(entry.get().strip())
        except ValueError:
            messagebox.showwarning("警告", f"{field_name} 必须是数字，已恢复为默认值 {default}")
            return default

    def _get_int(self, entry: ttk.Entry, default: int, field_name: str, minimum: int) -> int:
        try:
            return max(minimum, int(entry.get().strip()))
        except ValueError:
            messagebox.showwarning("警告", f"{field_name} 必须是整数，已恢复为默认值 {default}")
            return default

    def _on_save_clicked(self) -> None:
        self.config["model"] = self.model_entry.get().strip() or DEFAULT_CONFIG["model"]
        self.config["python_path"] = self.python_path_entry.get().strip() or DEFAULT_CONFIG["python_path"]
        self.config["model_path"] = self.model_path_entry.get().strip() or DEFAULT_CONFIG["model_path"]
        self.config["prompt"] = self.prompt_text.get("1.0", tk.END).strip() or DEFAULT_CONFIG["prompt"]
        self.config["temperature"] = max(0.0, min(2.0, self._get_float(self.temp_entry, DEFAULT_CONFIG["temperature"], "温度")))
        self.config["max_tokens"] = self._get_int(self.max_tokens_entry, DEFAULT_CONFIG["max_tokens"], "最大输出", 64)
        self.config["context_length"] = self._get_int(self.context_entry, DEFAULT_CONFIG["context_length"], "上下文长度", 1024)
        self.config["threads"] = self._get_int(self.threads_entry, DEFAULT_CONFIG["threads"], "线程数", 1)
        self.config["batch_size"] = self._get_int(self.batch_entry, DEFAULT_CONFIG["batch_size"], "批处理大小", 64)
        self.config["floating_window_enabled"] = self.floating_enabled_var.get()
        self.config["floating_auto_hide_delay"] = max(1.0, min(30.0, float(self.floating_delay_entry.get().strip() or "3.0")))
        self.config["floating_opacity"] = max(0.5, min(1.0, float(self.floating_opacity_entry.get().strip() or "0.95")))
        self.config["warmup_on_start"] = self.warmup_var.get()
        self._save_config()

    def _on_cancel_clicked(self) -> None:
        if self.window:
            self.window.destroy()
            self.window = None

    def _create_path_row(self, parent: ttk.Frame, row: int, label: str, value: str, browse_command: Callable[[], None]):
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky=tk.W, pady=(4, 4))
        entry = ttk.Entry(parent)
        entry.insert(0, value)
        entry.grid(row=row, column=1, sticky=(tk.W, tk.E), padx=(0, 10), pady=(4, 4))
        ttk.Button(parent, text="浏览", command=browse_command).grid(row=row, column=2, sticky=tk.E, pady=(4, 4))
        return entry

    def show(self) -> None:
        if self.window and self.window.winfo_exists():
            self.window.lift()
            self.window.focus_force()
            return

        self.window = tk.Tk()
        self.window.title("Type4Y 本地模型配置")
        self.window.geometry("760x620")
        self.window.minsize(700, 560)
        self.window.resizable(True, True)

        style = ttk.Style(self.window)
        if "clam" in style.theme_names():
            style.theme_use("clam")
        style.configure("Title.TLabel", font=("Microsoft YaHei UI", 16, "bold"))
        style.configure("Hint.TLabel", foreground="#5f6b7a")

        main_frame = ttk.Frame(self.window, padding=16)
        main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        self.window.columnconfigure(0, weight=1)
        self.window.rowconfigure(0, weight=1)
        main_frame.columnconfigure(0, weight=1)
        main_frame.rowconfigure(3, weight=1)
        main_frame.rowconfigure(4, weight=0)

        header_frame = ttk.Frame(main_frame)
        header_frame.grid(row=0, column=0, sticky=(tk.W, tk.E), pady=(0, 14))
        header_frame.columnconfigure(0, weight=1)

        ttk.Label(header_frame, text="Type4Y 本地翻译助手", style="Title.TLabel").grid(row=0, column=0, sticky=tk.W)
        ttk.Label(
            header_frame,
            text="已切换为本地模型模式，首次翻译会加载模型到内存，耗时会略长。",
            style="Hint.TLabel",
        ).grid(row=1, column=0, sticky=tk.W, pady=(6, 0))

        runtime_frame = ttk.LabelFrame(main_frame, text="运行环境")
        runtime_frame.grid(row=1, column=0, sticky=(tk.W, tk.E), pady=(0, 12))
        runtime_frame.columnconfigure(1, weight=1)

        self.python_path_entry = self._create_path_row(
            runtime_frame,
            0,
            "Python 环境",
            self.config.get("python_path", DEFAULT_CONFIG["python_path"]),
            self._browse_python_path,
        )
        self.model_path_entry = self._create_path_row(
            runtime_frame,
            1,
            "模型文件",
            self.config.get("model_path", DEFAULT_CONFIG["model_path"]),
            self._browse_model_path,
        )

        generation_frame = ttk.LabelFrame(main_frame, text="推理参数")
        generation_frame.grid(row=2, column=0, sticky=(tk.W, tk.E), pady=(0, 12))
        for column in range(4):
            generation_frame.columnconfigure(column, weight=1 if column % 2 == 1 else 0)

        ttk.Label(generation_frame, text="模型名称").grid(row=0, column=0, sticky=tk.W, padx=(0, 10), pady=(8, 6))
        self.model_entry = ttk.Entry(generation_frame)
        self.model_entry.insert(0, self.config.get("model", DEFAULT_CONFIG["model"]))
        self.model_entry.grid(row=0, column=1, sticky=(tk.W, tk.E), padx=(0, 14), pady=(8, 6))

        ttk.Label(generation_frame, text="温度").grid(row=0, column=2, sticky=tk.W, padx=(0, 10), pady=(8, 6))
        self.temp_entry = ttk.Entry(generation_frame, width=12)
        self.temp_entry.insert(0, str(self.config.get("temperature", DEFAULT_CONFIG["temperature"])))
        self.temp_entry.grid(row=0, column=3, sticky=(tk.W, tk.E), pady=(8, 6))

        ttk.Label(generation_frame, text="最大输出").grid(row=1, column=0, sticky=tk.W, padx=(0, 10), pady=6)
        self.max_tokens_entry = ttk.Entry(generation_frame, width=12)
        self.max_tokens_entry.insert(0, str(self.config.get("max_tokens", DEFAULT_CONFIG["max_tokens"])))
        self.max_tokens_entry.grid(row=1, column=1, sticky=(tk.W, tk.E), padx=(0, 14), pady=6)

        ttk.Label(generation_frame, text="上下文长度").grid(row=1, column=2, sticky=tk.W, padx=(0, 10), pady=6)
        self.context_entry = ttk.Entry(generation_frame, width=12)
        self.context_entry.insert(0, str(self.config.get("context_length", DEFAULT_CONFIG["context_length"])))
        self.context_entry.grid(row=1, column=3, sticky=(tk.W, tk.E), pady=6)

        ttk.Label(generation_frame, text="线程数").grid(row=2, column=0, sticky=tk.W, padx=(0, 10), pady=(6, 10))
        self.threads_entry = ttk.Entry(generation_frame, width=12)
        self.threads_entry.insert(0, str(self.config.get("threads", DEFAULT_CONFIG["threads"])))
        self.threads_entry.grid(row=2, column=1, sticky=(tk.W, tk.E), padx=(0, 14), pady=(6, 10))

        ttk.Label(generation_frame, text="批处理大小").grid(row=2, column=2, sticky=tk.W, padx=(0, 10), pady=(6, 10))
        self.batch_entry = ttk.Entry(generation_frame, width=12)
        self.batch_entry.insert(0, str(self.config.get("batch_size", DEFAULT_CONFIG["batch_size"])))
        self.batch_entry.grid(row=2, column=3, sticky=(tk.W, tk.E), pady=(6, 10))

        prompt_frame = ttk.LabelFrame(main_frame, text="翻译提示词")
        prompt_frame.grid(row=3, column=0, sticky=(tk.W, tk.E, tk.N, tk.S), pady=(0, 12))
        prompt_frame.columnconfigure(0, weight=1)
        prompt_frame.rowconfigure(1, weight=1)

        ttk.Label(
            prompt_frame,
            text="可以自定义翻译方向、语气和保留格式规则，模型会直接输出译文。",
            style="Hint.TLabel",
        ).grid(row=0, column=0, sticky=tk.W, pady=(6, 8))

        self.prompt_text = tk.Text(
            prompt_frame,
            height=10,
            wrap=tk.WORD,
            relief=tk.FLAT,
            bd=0,
            font=("Microsoft YaHei UI", 10),
            padx=10,
            pady=10,
        )
        self.prompt_text.insert("1.0", self.config.get("prompt", DEFAULT_CONFIG["prompt"]))
        self.prompt_text.grid(row=1, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))

        floating_frame = ttk.LabelFrame(main_frame, text="悬浮窗设置")
        floating_frame.grid(row=4, column=0, sticky=(tk.W, tk.E), pady=(0, 12))
        floating_frame.columnconfigure(1, weight=1)

        self.floating_enabled_var = tk.BooleanVar(value=self.config.get("floating_window_enabled", True))
        ttk.Checkbutton(floating_frame, text="启用悬浮窗显示翻译结果", variable=self.floating_enabled_var).grid(row=0, column=0, columnspan=3, sticky=tk.W, pady=(8, 6))

        ttk.Label(floating_frame, text="自动隐藏延时(秒)").grid(row=1, column=0, sticky=tk.W, padx=(0, 10), pady=6)
        self.floating_delay_entry = ttk.Entry(floating_frame, width=12)
        self.floating_delay_entry.insert(0, str(self.config.get("floating_auto_hide_delay", 3.0)))
        self.floating_delay_entry.grid(row=1, column=1, sticky=(tk.W, tk.E), pady=6)

        ttk.Label(floating_frame, text="窗口透明度").grid(row=1, column=2, sticky=tk.W, padx=(14, 10), pady=6)
        self.floating_opacity_entry = ttk.Entry(floating_frame, width=8)
        self.floating_opacity_entry.insert(0, str(self.config.get("floating_opacity", 0.95)))
        self.floating_opacity_entry.grid(row=1, column=3, sticky=(tk.W, tk.E), pady=6)

        self.warmup_var = tk.BooleanVar(value=self.config.get("warmup_on_start", True))
        ttk.Checkbutton(floating_frame, text="启动时预加载模型（减少首次翻译等待时间）", variable=self.warmup_var).grid(row=2, column=0, columnspan=3, sticky=tk.W, pady=(6, 10))

        footer_frame = ttk.Frame(main_frame)
        footer_frame.grid(row=5, column=0, sticky=(tk.W, tk.E))
        footer_frame.columnconfigure(0, weight=1)

        ttk.Label(
            footer_frame,
            text="热键仍然是 Ctrl+Y。保存后立即生效，若模型路径或环境路径发生变化，将重新加载本地工作进程。",
            style="Hint.TLabel",
        ).grid(row=0, column=0, sticky=tk.W, pady=(2, 0))

        button_frame = ttk.Frame(footer_frame)
        button_frame.grid(row=1, column=0, sticky=tk.E, pady=(12, 0))

        ttk.Button(button_frame, text="恢复默认", command=self._restore_defaults).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(button_frame, text="取消", command=self._on_cancel_clicked).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(button_frame, text="保存并应用", command=self._on_save_clicked).pack(side=tk.LEFT)

        logger.debug("配置界面已显示")
        self.window.protocol("WM_DELETE_WINDOW", self._on_cancel_clicked)
        self.window.mainloop()


def test_config_ui():
    config_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'config.json')

    def on_save():
        print("配置已保存！")

    ui = ConfigUI(config_path, on_save=on_save)
    ui.show()


if __name__ == "__main__":
    test_config_ui()
