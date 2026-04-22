import json
import os
import queue
import re
import subprocess
import threading
from typing import Any, Dict, Optional
from src.app_settings import DEFAULT_CONFIG
from src.logger import get_logger

logger = get_logger("translator")

READY_TIMEOUT = 180
STREAM_MESSAGE_TIMEOUT = 60


class Translator:
    def __init__(self, config: Dict[str, Any]):
        self.config: Dict[str, Any] = {}
        self.process: Optional[subprocess.Popen] = None
        self.stdout_queue: queue.Queue[str] = queue.Queue()
        self.stderr_buffer: list[str] = []
        self._stdout_thread: Optional[threading.Thread] = None
        self._stderr_thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self._is_warmed: bool = False
        self.update_config(config)
        logger.debug("Translator 初始化完成")

    def update_config(self, config: Dict[str, Any]) -> None:
        merged = DEFAULT_CONFIG.copy()
        merged.update(config or {})
        restart_required = any(
            merged.get(key) != self.config.get(key)
            for key in ("python_path", "model_path", "context_length", "threads", "batch_size")
        )
        self.config = merged
        if restart_required:
            self.close()

    def _worker_script_path(self) -> str:
        return os.path.join(os.path.dirname(os.path.abspath(__file__)), "local_model_worker.py")

    def _project_root(self) -> str:
        return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    def _collect_stream(self, stream, buffer_queue: Optional[queue.Queue[str]] = None, buffer_list: Optional[list[str]] = None) -> None:
        try:
            for line in iter(stream.readline, ""):
                text = line.rstrip()
                if buffer_queue is not None:
                    buffer_queue.put(text)
                if buffer_list is not None and text:
                    buffer_list.append(text)
                    if len(buffer_list) > 60:
                        del buffer_list[:-60]
        finally:
            try:
                stream.close()
            except Exception:
                pass

    def _ensure_runtime_paths(self) -> None:
        python_path = self.config.get("python_path", "").strip()
        model_path = self.config.get("model_path", "").strip()

        if not python_path:
            raise RuntimeError("未配置本地运行环境 Python 路径")
        if not os.path.exists(python_path):
            raise RuntimeError(f"找不到本地运行环境: {python_path}")
        if not model_path:
            raise RuntimeError("未配置本地模型文件路径")
        if not os.path.exists(model_path):
            raise RuntimeError(f"找不到模型文件: {model_path}")

    def _start_worker(self) -> None:
        self._ensure_runtime_paths()
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        command = [
            self.config["python_path"],
            self._worker_script_path(),
            "--model-path",
            self.config["model_path"],
            "--context-length",
            str(self.config["context_length"]),
            "--threads",
            str(self.config["threads"]),
            "--batch-size",
            str(self.config["batch_size"]),
        ]

        self.process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=self._project_root(),
            creationflags=creationflags,
        )
        self.stdout_queue = queue.Queue()
        self.stderr_buffer = []
        self._stdout_thread = threading.Thread(
            target=self._collect_stream,
            args=(self.process.stdout, self.stdout_queue, None),
            daemon=True,
        )
        self._stderr_thread = threading.Thread(
            target=self._collect_stream,
            args=(self.process.stderr, None, self.stderr_buffer),
            daemon=True,
        )
        self._stdout_thread.start()
        self._stderr_thread.start()

        ready_payload = self._read_message(timeout=READY_TIMEOUT)
        if not ready_payload.get("ok") or ready_payload.get("type") != "ready":
            error = ready_payload.get("error") or "本地模型启动失败"
            self.close()
            raise RuntimeError(error)
        logger.info("本地模型工作进程已就绪")

    def _ensure_worker(self) -> None:
        if self.process and self.process.poll() is None:
            return
        self.close()
        logger.info("正在启动本地模型工作进程...")
        self._start_worker()

    def _send_message(self, payload: Dict[str, Any]) -> None:
        if not self.process or not self.process.stdin:
            raise RuntimeError("本地模型工作进程不可用")
        self.process.stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
        self.process.stdin.flush()

    def _read_message(self, timeout: int) -> Dict[str, Any]:
        try:
            raw_message = self.stdout_queue.get(timeout=timeout)
        except queue.Empty:
            self.close()
            raise RuntimeError("等待本地模型响应超时")

        try:
            return json.loads(raw_message)
        except json.JSONDecodeError:
            logger.error(f"无法解析工作进程输出: {raw_message}")
            raise RuntimeError("本地模型返回了无法解析的结果")

    def _build_prompt(self, text: str, prompt: str) -> str:
        instruction = prompt.strip() if prompt and prompt.strip() else self.config.get("prompt", DEFAULT_CONFIG["prompt"])
        system_prompt = (
            "You are a precise translation assistant. "
            "Return only the translated text. "
            "Do not output explanations, analysis, or thinking tags."
        )
        user_prompt = f"{instruction}\n\n---\n\nTEXT TO TRANSLATE:\n{text}\n\nTRANSLATION:"
        return (
            f"<|im_start|>system\n{system_prompt}<|im_end|>\n"
            f"<|im_start|>user\n{user_prompt}<|im_end|>\n"
            f"<|im_start|>assistant\n"
        )

    def _clean_output(self, text: str) -> str:
        cleaned = text.strip()
        cleaned = re.sub(r"^<think>[\s\S]*?</think>\s*", "", cleaned, flags=re.IGNORECASE)
        return cleaned.strip()

    def _tail_stderr(self) -> str:
        if not self.stderr_buffer:
            return ""
        return "\n".join(self.stderr_buffer[-8:])

    def translate(
        self,
        text: str,
        prompt: str,
        model: str = DEFAULT_CONFIG["model"],
        temperature: float = DEFAULT_CONFIG["temperature"],
        max_tokens: Optional[int] = None
    ) -> str:
        try:
            logger.debug(f"准备翻译: model={model}, temperature={temperature}")
            effective_temperature = float(temperature)
            effective_max_tokens = max_tokens if max_tokens is not None else self.config.get("max_tokens", DEFAULT_CONFIG["max_tokens"])
            request_payload = {
                "type": "translate",
                "model": model,
                "prompt": self._build_prompt(text, prompt),
                "temperature": effective_temperature,
                "max_tokens": int(effective_max_tokens),
            }

            with self._lock:
                self._ensure_worker()
                self._send_message(request_payload)
                response = self._read_message(timeout=300)

            if not response.get("ok"):
                error = response.get("error") or "本地模型调用失败"
                detail = self._tail_stderr()
                if detail:
                    error = f"{error}\n{detail}"
                raise RuntimeError(error)

            translated_text = self._clean_output(response.get("text", ""))
            if not translated_text:
                raise RuntimeError("本地模型未返回可用结果")

            logger.debug("翻译成功")
            return translated_text
        except Exception as e:
            logger.error(f"翻译过程中发生错误: {e}", exc_info=True)
            raise RuntimeError(str(e))

    def translate_stream(
        self,
        text: str,
        prompt: str,
        model: str = DEFAULT_CONFIG["model"],
        temperature: float = DEFAULT_CONFIG["temperature"],
        max_tokens: Optional[int] = None
    ):
        """
        流式翻译 - 逐 token 生成器

        Yields:
            str: 每个 token 的文本内容

        Raises:
            RuntimeError: 翻译过程中发生错误
        """
        logger.debug(f"准备流式翻译: model={model}, temperature={temperature}")
        effective_temperature = float(temperature)
        effective_max_tokens = max_tokens if max_tokens is not None else self.config.get("max_tokens", DEFAULT_CONFIG["max_tokens"])
        request_payload = {
            "type": "translate",
            "model": model,
            "prompt": self._build_prompt(text, prompt),
            "temperature": effective_temperature,
            "max_tokens": int(effective_max_tokens),
        }

        with self._lock:
            self._ensure_worker()
            self._send_message(request_payload)

            while True:
                msg = self._read_message(timeout=STREAM_MESSAGE_TIMEOUT)
                msg_type = msg.get("type")

                if msg_type == "token":
                    yield msg.get("text", "")
                elif msg_type == "result":
                    if not msg.get("ok"):
                        error = msg.get("error") or "本地模型调用失败"
                        detail = self._tail_stderr()
                        if detail:
                            error = f"{error}\n{detail}"
                        raise RuntimeError(error)
                    return
                else:
                    if not msg.get("ok"):
                        error = msg.get("error") or "本地模型调用失败"
                        detail = self._tail_stderr()
                        if detail:
                            error = f"{error}\n{detail}"
                        raise RuntimeError(error)

    def warmup(self, blocking: bool = False) -> bool:
        """
        预热模型 - 在后台启动工作进程并发送预热请求

        Args:
            blocking: 是否阻塞等待预热完成（默认 False，非阻塞模式）

        Returns:
            bool: 预热是否成功（非阻塞模式下返回是否成功启动预热线程）
        """
        def _do_warmup():
            try:
                with self._lock:
                    self._ensure_worker()
                    self._send_message({
                        "type": "translate",
                        "model": DEFAULT_CONFIG["model"],
                        "prompt": self._build_prompt("hi", "Reply with 'ok'"),
                        "temperature": 0.1,
                        "max_tokens": 2,
                    })
                response = self._read_message(timeout=STREAM_MESSAGE_TIMEOUT)
                while response.get("type") == "token":
                    response = self._read_message(timeout=STREAM_MESSAGE_TIMEOUT)
                if response.get("ok") and response.get("type") == "result":
                    self._is_warmed = True
                    logger.info("模型预热完成")
                    return True
                logger.warning(f"模型预热失败: {response}")
                return False
            except Exception as e:
                logger.warning(f"模型预热过程中发生错误: {e}")
                return False

        thread = threading.Thread(target=_do_warmup, daemon=True)
        thread.start()
        if blocking:
            thread.join(timeout=READY_TIMEOUT + 30)
        return self._is_warmed

    def is_ready(self) -> bool:
        """
        检查 worker 进程是否存在且已预热

        Returns:
            bool: 是否就绪
        """
        return self.process is not None and self.process.poll() is None and self._is_warmed

    def close(self) -> None:
        process = self.process
        self.process = None
        if not process:
            return

        try:
            if process.poll() is None and process.stdin:
                process.stdin.write(json.dumps({"type": "shutdown"}, ensure_ascii=False) + "\n")
                process.stdin.flush()
        except Exception:
            pass

        try:
            process.wait(timeout=2)
        except Exception:
            try:
                process.terminate()
                process.wait(timeout=3)
            except Exception:
                process.kill()


def test_translator():
    print("=== 测试 Translator ===")
    try:
        translator = Translator(DEFAULT_CONFIG.copy())
        print("✓ Translator 初始化成功")
        test_text = "你好，世界！"
        test_prompt = "Translate the following Chinese text into English naturally:"
        print(f"\n输入文本: {test_text}")
        print(f"系统提示词: {test_prompt}")
        print("\n正在翻译...")
        result = translator.translate(
            text=test_text,
            prompt=test_prompt,
            model=DEFAULT_CONFIG["model"],
            max_tokens=128
        )
        print(f"✓ 翻译成功!")
        print(f"翻译结果: {result}")
        translator.close()
        print("\n=== 测试完成 ===")
        return True
    except Exception as e:
        print(f"✗ 测试失败: {e}")
        return False


if __name__ == "__main__":
    test_translator()
