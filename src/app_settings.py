import copy

APP_NAME = "Type4Y"
APP_VERSION = "2.0.0"

DEFAULT_CONFIG = {
    "model": "Qwen3.5-9B_Q5",
    "model_path": r"E:\local_LLM\Models_Repo\Qwen3.5-9B_Q5\Qwen3.5-9B_Q5\Qwen3.5-9B.Q5_K_S.gguf",
    "python_path": r"E:\local_LLM\qopus\Scripts\python.exe",
    "prompt": "Translate the text into natural English. Preserve formatting and return only the translation without explanations.",
    "temperature": 0.3,
    "max_tokens": 768,
    "context_length": 4096,
    "threads": 6,
    "batch_size": 512,
    "floating_window_enabled": True,
    "floating_auto_hide_delay": 3.0,
    "floating_opacity": 0.95,
    "warmup_on_start": True,
}

LEGACY_CONFIG_KEYS = {"api_key", "base_url"}


def get_default_config():
    return copy.deepcopy(DEFAULT_CONFIG)
