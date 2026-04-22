import json
import os
import sys
from typing import Any, Dict
from src.app_settings import DEFAULT_CONFIG, LEGACY_CONFIG_KEYS, get_default_config
from src.logger import get_logger

logger = get_logger("config_manager")


class ConfigManager:
    def __init__(self):
        self.config: Dict[str, Any] = {}
        self.config_path: str = self._get_config_path()
        self.load_config()

    def _get_config_path(self) -> str:
        if getattr(sys, 'frozen', False):
            base_path = os.path.dirname(sys.executable)
        else:
            base_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        return os.path.join(base_path, 'config.json')

    def load_config(self) -> None:
        try:
            logger.debug(f"正在加载配置文件: {self.config_path}")
            if not os.path.exists(self.config_path):
                self.config = get_default_config()
                self.save_config()
                logger.info("配置文件不存在，已创建默认本地模型配置")
                return

            with open(self.config_path, 'r', encoding='utf-8') as f:
                raw_config = json.load(f)

            self.config = self._normalize_config(raw_config)
            if self._should_rewrite_config(raw_config):
                self.save_config()
            logger.debug("配置文件加载成功")
        except json.JSONDecodeError as e:
            logger.error(f"配置文件格式错误: {e}", exc_info=True)
            raise RuntimeError("配置文件格式错误，请检查 JSON 格式")
        except Exception as e:
            logger.error(f"加载配置失败: {e}", exc_info=True)
            raise RuntimeError("加载配置失败，请检查配置文件")

    def reload_config(self) -> None:
        logger.debug("重新加载配置文件")
        self.load_config()

    def save_config(self, config: Dict[str, Any] | None = None) -> None:
        if config is not None:
            self.config = self._normalize_config(config)
        os.makedirs(os.path.dirname(self.config_path), exist_ok=True)
        with open(self.config_path, 'w', encoding='utf-8') as f:
            json.dump(self.config, f, indent=2, ensure_ascii=False)
        logger.debug("配置文件保存成功")

    def _normalize_config(self, raw_config: Dict[str, Any]) -> Dict[str, Any]:
        normalized = get_default_config()
        filtered = {k: v for k, v in raw_config.items() if k not in LEGACY_CONFIG_KEYS}
        normalized.update(filtered)

        normalized["model"] = str(normalized.get("model", DEFAULT_CONFIG["model"])).strip() or DEFAULT_CONFIG["model"]
        normalized["model_path"] = str(normalized.get("model_path", DEFAULT_CONFIG["model_path"])).strip() or DEFAULT_CONFIG["model_path"]
        normalized["python_path"] = str(normalized.get("python_path", DEFAULT_CONFIG["python_path"])).strip() or DEFAULT_CONFIG["python_path"]
        normalized["prompt"] = str(normalized.get("prompt", DEFAULT_CONFIG["prompt"])).strip() or DEFAULT_CONFIG["prompt"]
        normalized["temperature"] = max(0.0, min(2.0, self._to_float(normalized.get("temperature"), DEFAULT_CONFIG["temperature"])))
        normalized["max_tokens"] = max(64, self._to_int(normalized.get("max_tokens"), DEFAULT_CONFIG["max_tokens"]))
        normalized["context_length"] = max(1024, self._to_int(normalized.get("context_length"), DEFAULT_CONFIG["context_length"]))
        normalized["threads"] = max(1, self._to_int(normalized.get("threads"), DEFAULT_CONFIG["threads"]))
        normalized["batch_size"] = max(64, self._to_int(normalized.get("batch_size"), DEFAULT_CONFIG["batch_size"]))
        return normalized

    def _should_rewrite_config(self, raw_config: Dict[str, Any]) -> bool:
        if any(key in raw_config for key in LEGACY_CONFIG_KEYS):
            return True
        return raw_config != self.config

    def _to_float(self, value: Any, default: float) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    def _to_int(self, value: Any, default: int) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    def get(self, key: str, default: Any = None) -> Any:
        return self.config.get(key, default)

    def get_all(self) -> Dict[str, Any]:
        return self.config.copy()


def test_config_manager():
    print("=== 测试 ConfigManager ===")
    try:
        manager = ConfigManager()
        print("✓ 配置加载成功")
        print(f"配置文件路径: {manager.config_path}")
        print(f"完整配置: {manager.get_all()}")

        print("\n测试重新加载...")
        manager.reload_config()
        print("✓ 重新加载成功")

        print("\n=== 测试完成 ===")
        return True
    except Exception as e:
        print(f"✗ 测试失败: {e}")
        return False


if __name__ == "__main__":
    test_config_manager()
