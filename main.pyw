"""
Type4Y 翻译助手 - 主程序入口

核心功能：
1. 初始化各模块
2. 协调翻译工作流
3. 窗口焦点锁定
4. 状态管理

解决的关键问题：
- 窗口焦点丢失：通过窗口句柄比对，防止翻译结果粘贴到错误位置
- 热键防抖：使用状态锁机制，防止并发翻译
"""

import sys
import time
import threading
import os
from typing import Optional
import ctypes
from ctypes import wintypes
import win32gui
import win32process
import win32api
import win32event

from src.app_settings import APP_NAME, DEFAULT_CONFIG
from src.logger import setup_logger, get_logger
from src.config_manager import ConfigManager
from src.config_ui import ConfigUI
from src.translator import Translator
from src.clipboard_manager import ClipboardManager
from src.hotkey_manager import HotkeyManager
from src.tray_manager import TrayManager
from src.floating_window import FloatingWindow

setup_logger()
logger = get_logger("main")

MUTEX_NAME = "Type4Y_SingleInstance_Mutex"


class SingleInstanceChecker:
    """
    单例检测器 - 确保程序只有一个实例在运行
    """
    def __init__(self):
        self.mutex = None
        self.has_instance = False

    def check(self) -> bool:
        """
        检查是否已存在运行实例

        Returns:
            bool: True 表示这是第一个实例，False 表示已存在实例
        """
        try:
            self.mutex = win32event.CreateMutex(None, False, MUTEX_NAME)
            last_error = win32api.GetLastError()
            if last_error == 183:
                self.has_instance = True
                return False
            return True
        except Exception as e:
            logger.warning(f"单例检测失败: {e}")
            return True

    def release(self) -> None:
        """释放互斥锁"""
        if self.mutex:
            try:
                win32api.CloseHandle(self.mutex)
            except:
                pass
            self.mutex = None


class TranslationApp:
    """
    翻译应用主类 - 协调各模块完成翻译工作流
    
    特性：
    - 窗口焦点锁定：防止翻译结果粘贴到错误位置
    - 状态锁机制：防止并发翻译请求
    - 友好的用户提示：通过托盘通知反馈翻译状态
    """
    
    def __init__(self):
        self.config_manager: Optional[ConfigManager] = None
        self.translator: Optional[Translator] = None
        self.clipboard_manager: Optional[ClipboardManager] = None
        self.hotkey_manager: Optional[HotkeyManager] = None
        self.tray_manager: Optional[TrayManager] = None
        self.floating_window: Optional[FloatingWindow] = None
        self.running: bool = False
        self._lock: threading.Lock = threading.Lock()

    def initialize(self) -> bool:
        """
        初始化所有模块
        
        Returns:
            bool: 是否初始化成功
        """
        try:
            logger.info("正在初始化配置管理器...")
            self.config_manager = ConfigManager()
            logger.info("配置管理器初始化成功")

            logger.info("正在初始化翻译器...")
            self.translator = Translator(self.config_manager.get_all())
            logger.info("翻译器初始化成功")

            logger.info("正在初始化剪贴板管理器...")
            self.clipboard_manager = ClipboardManager(
                delay=0.05,
                poll_interval=0.05,
                poll_timeout=0.5
            )
            logger.info("剪贴板管理器初始化成功")

            logger.info("正在初始化热键管理器...")
            self.hotkey_manager = HotkeyManager(debounce_time=0.5)
            self.hotkey_manager.register_callback(self._on_translate_hotkey)
            logger.info("热键管理器初始化成功")

            logger.info("正在初始化托盘管理器...")
            self.tray_manager = TrayManager(
                on_exit=self.shutdown,
                on_open_config=self._open_config,
                on_restart_hotkey=self._restart_hotkey
            )
            logger.info("托盘管理器初始化成功")

            floating_config = self.config_manager.get_all()
            self.floating_window = FloatingWindow(
                on_copy_callback=self._on_floating_copy,
                on_pin_callback=self._on_floating_pin,
                on_close_callback=self._on_floating_close,
                auto_hide_delay=floating_config.get("floating_auto_hide_delay", 3.0),
            )
            logger.info("悬浮窗组件初始化成功")

            return True

        except Exception as e:
            logger.error(f"初始化失败: {e}", exc_info=True)
            self._show_error_message("程序初始化失败，请检查配置文件是否正确")
            return False

    def _show_info_message(self, message: str) -> None:
        """
        显示信息提示框
        
        Args:
            message: 提示信息
        """
        try:
            ctypes.windll.user32.MessageBoxW(0, message, "Type4Y 翻译助手", 0x00000040 | 0x00000000)
        except Exception:
            logger.info(message)

    def _show_error_message(self, message: str) -> None:
        """
        显示错误提示框
        
        Args:
            message: 错误信息
        """
        try:
            ctypes.windll.user32.MessageBoxW(0, message, "Type4Y 错误", 0x00000010 | 0x00000000)
        except Exception:
            logger.error(message)

    def _get_window_info(self, hwnd: int) -> str:
        """
        获取窗口信息（用于日志记录）

        Args:
            hwnd: 窗口句柄

        Returns:
            str: 窗口信息字符串
        """
        info = {"hwnd": hwnd}
        try:
            info["title"] = win32gui.GetWindowText(hwnd)
        except Exception:
            info["title"] = "<无法获取>"
        try:
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            info["pid"] = pid
        except Exception:
            info["pid"] = "<无法获取>"

        return f"HWND={info['hwnd']}, Title='{info['title']}', PID={info['pid']}"

    def _on_translate_hotkey(self) -> None:
        """
        热键触发回调

        在子线程中执行翻译工作流，不阻塞热键监听
        """
        if self.hotkey_manager.is_processing():
            logger.warning("翻译任务正在处理中，忽略本次触发")
            return

        self.hotkey_manager.set_processing(True)
        threading.Thread(target=self._translate_workflow, daemon=True).start()

    def _open_config(self) -> None:
        """
        打开配置界面
        """
        logger.info("打开配置界面")
        if self.config_manager:
            def on_config_saved():
                logger.info("配置已保存，重新加载...")
                self.config_manager.reload_config()
                if self.translator:
                    self.translator.update_config(self.config_manager.get_all())
                logger.info("配置重新加载完成")
            
            config_ui = ConfigUI(self.config_manager.config_path, on_save=on_config_saved)
            threading.Thread(target=config_ui.show, daemon=True).start()

    def _restart_hotkey(self) -> None:
        """
        重启热键监听

        用于解决长时间后台运行后热键失效的问题
        """
        logger.info("重启热键监听...")

        def _do_restart():
            try:
                if self.hotkey_manager:
                    self.hotkey_manager.restart_listening()
                    logger.info("热键监听重启成功")
                    if self.tray_manager:
                        self.tray_manager.show_notification("Type4Y", "热键已恢复，请尝试 Ctrl+Y")
                else:
                    logger.error("热键管理器未初始化")
            except Exception as e:
                logger.error(f"重启热键失败: {e}", exc_info=True)
                if self.tray_manager:
                    self.tray_manager.show_notification("Type4Y", f"重启热键失败: {e}")

        threading.Thread(target=_do_restart, daemon=True).start()

    def _on_floating_copy(self, text: str) -> None:
        """悬浮窗复制按钮回调"""
        self.clipboard_manager.set_clipboard_only(text)
        if self.tray_manager:
            self.tray_manager.show_notification(APP_NAME, "译文已复制到剪贴板")

    def _on_floating_pin(self, pinned: bool) -> None:
        """悬浮窗固定按钮回调"""
        logger.debug(f"悬浮窗固定状态: {pinned}")

    def _on_floating_close(self) -> None:
        """悬浮窗关闭按钮回调"""
        logger.debug("悬浮窗被用户关闭")

    def _get_cursor_position(self) -> tuple:
        """获取当前鼠标光标位置"""
        class POINT(ctypes.Structure):
            _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]
        pt = POINT()
        ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
        return pt.x, pt.y

    def _translate_workflow(self) -> None:
        """
        翻译工作流 - 异步流式模式

        新流程：
        1. 获取选中文本
        2. 立即显示悬浮窗（含原文和加载状态）
        3. 流式调用翻译，实时更新悬浮窗译文
        4. 翻译完成后执行剪贴板替换
        5. 悬浮窗显示完整结果并自动隐藏
        """
        try:
            original_hwnd = win32gui.GetForegroundWindow()
            original_window_info = self._get_window_info(original_hwnd)
            logger.info(f"记录原始窗口: {original_window_info}")

            selected_text = self.clipboard_manager.get_selected_text()
            if not selected_text or not selected_text.strip():
                logger.debug("未选中文本")
                self._show_info_message("请先选择要翻译的文本")
                return

            logger.debug(f"获取到选中文本: {selected_text[:100]}{'...' if len(selected_text) > 100 else ''}")

            floating_enabled = self.config_manager.get('floating_window_enabled', True)
            cursor_x, cursor_y = self._get_cursor_position()

            if floating_enabled and self.floating_window:
                self.floating_window.show(selected_text, cursor_x, cursor_y)
            elif self.tray_manager:
                self.tray_manager.show_notification(APP_NAME, "正在调用本地模型...")

            prompt = self.config_manager.get('prompt', DEFAULT_CONFIG['prompt'])
            model = self.config_manager.get('model', DEFAULT_CONFIG['model'])
            temperature = self.config_manager.get('temperature', DEFAULT_CONFIG['temperature'])
            max_tokens = self.config_manager.get('max_tokens', DEFAULT_CONFIG['max_tokens'])

            logger.debug("正在调用本地模型（流式模式）...")
            translated_parts = []
            translated_text = None

            try:
                for token_text in self.translator.translate_stream(
                    text=selected_text,
                    prompt=prompt,
                    model=model,
                    temperature=temperature,
                    max_tokens=max_tokens,
                ):
                    translated_parts.append(token_text)
                    partial = "".join(translated_parts)

                    if floating_enabled and self.floating_window:
                        self.floating_window.update_translation(partial)

                translated_text = "".join(translated_parts)
                translated_text = self.translator._clean_output(translated_text)

            except RuntimeError as stream_error:
                error_str = str(stream_error)
                if "超时" in error_str or "timeout" in error_str.lower():
                    logger.error(f"翻译超时: {stream_error}")
                    raise RuntimeError("翻译超时，模型可能正在加载中，请稍后重试")
                elif "启动失败" in error_str or "不可用" in error_str:
                    logger.error(f"模型启动失败: {stream_error}")
                    raise RuntimeError("本地模型启动失败，请检查模型路径和Python环境配置")
                else:
                    logger.error(f"流式翻译失败，尝试使用同步模式: {stream_error}")
                    try:
                        translated_text = self.translator.translate(
                            text=selected_text,
                            prompt=prompt,
                            model=model,
                            temperature=temperature,
                            max_tokens=max_tokens,
                        )
                    except Exception as sync_error:
                        logger.error(f"同步翻译也失败: {sync_error}")
                        raise RuntimeError(f"翻译失败: {str(sync_error)}")

            except Exception as stream_error:
                logger.error(f"流式翻译失败，尝试使用同步模式: {stream_error}")
                try:
                    translated_text = self.translator.translate(
                        text=selected_text,
                        prompt=prompt,
                        model=model,
                        temperature=temperature,
                        max_tokens=max_tokens,
                    )
                except Exception as sync_error:
                    logger.error(f"同步翻译也失败: {sync_error}")
                    raise RuntimeError(f"翻译失败: {str(sync_error)}")

            if not translated_text or not translated_text.strip():
                raise RuntimeError("本地模型未返回有效结果，请检查模型是否正确加载")

            logger.debug(f"翻译完成: {translated_text[:100]}{'...' if len(translated_text) > 100 else ''}")

            if floating_enabled and self.floating_window:
                self.floating_window.set_done(translated_text)

            current_hwnd = win32gui.GetForegroundWindow()
            current_window_info = self._get_window_info(current_hwnd)
            logger.info(f"当前窗口: {current_window_info}")

            if current_hwnd == original_hwnd:
                logger.info("窗口焦点未变化，执行替换操作")
                success = self.clipboard_manager.replace_selected_text(translated_text, target_hwnd=current_hwnd)

                if success:
                    logger.info("翻译工作流完成")
                    if self.tray_manager and not floating_enabled:
                        self.tray_manager.show_notification(APP_NAME, "翻译完成！")
                else:
                    logger.warning("替换文本失败，将结果复制到剪贴板")
                    self.clipboard_manager.set_clipboard_only(translated_text)
                    if self.tray_manager:
                        self.tray_manager.show_notification(APP_NAME, "替换失败，结果已复制到剪贴板")
                    if floating_enabled and self.floating_window:
                        self.floating_window.set_error("替换失败，结果已复制到剪贴板")
            else:
                logger.warning(f"窗口焦点已变化！原始: {original_window_info}, 当前: {current_window_info}")
                self.clipboard_manager.set_clipboard_only(translated_text)
                if self.tray_manager:
                    self.tray_manager.show_notification(APP_NAME, "焦点已切换，结果已复制到剪贴板")
                logger.info("翻译结果已复制到剪贴板，用户可手动粘贴")

        except Exception as e:
            logger.error(f"翻译失败: {e}", exc_info=True)
            error_msg = str(e) if str(e).strip() else "翻译失败，请检查本地模型配置"
            self._show_error_message(error_msg)
            if self.tray_manager:
                self.tray_manager.show_notification(APP_NAME, error_msg)
            floating_enabled = self.config_manager.get('floating_window_enabled', True)
            if floating_enabled and self.floating_window:
                self.floating_window.set_error(error_msg)

        finally:
            self.hotkey_manager.set_processing(False)
            logger.debug("翻译工作流结束，状态锁已释放")

    def start(self) -> None:
        """
        启动应用
        
        初始化各模块并进入主循环
        """
        if not self.initialize():
            return

        self.running = True

        logger.info("\n正在启动热键监听...")
        self.hotkey_manager.start_listening()
        logger.info("热键监听已启动 (Ctrl+Y)")

        if self.config_manager.get('warmup_on_start', True):
            logger.info("正在后台预热本地模型...")
            threading.Thread(target=self._do_warmup, daemon=True).start()

        logger.info("正在启动托盘图标...")
        self.tray_manager.start()
        logger.info("托盘图标已启动")

        logger.info("\n=== Type4Y 翻译助手已启动 ===")
        logger.info("使用说明:")
        logger.info("1. 选中要翻译的文本")
        logger.info("2. 按 Ctrl+Y 调用本地模型并替换")
        logger.info("3. 右键点击系统托盘图标选择'退出'关闭程序")
        logger.info("\n安全特性:")
        logger.info("- 窗口焦点锁定：防止翻译结果粘贴到错误位置")
        logger.info("- 状态锁机制：防止并发翻译请求\n")

        try:
            while self.running and self.tray_manager._running:
                time.sleep(0.1)
        except KeyboardInterrupt:
            logger.info("\n检测到中断信号，正在退出...")
            self.shutdown()

    def _do_warmup(self) -> None:
        """后台执行模型预热"""
        try:
            if self.translator and self.translator.warmup():
                logger.info("模型预热完成")
                if self.tray_manager:
                    self.tray_manager.show_notification(APP_NAME, "模型已就绪，可以开始翻译")
            else:
                logger.info("模型预热未完成（将在首次翻译时加载）")
        except Exception as e:
            logger.warning(f"模型预热失败: {e}")

    def shutdown(self) -> None:
        """
        关闭应用

        优雅地停止各模块
        """
        logger.info("\n正在关闭程序...")

        with self._lock:
            if not self.running:
                logger.debug("关闭请求已处理，跳过")
                return
            self.running = False

        if self.hotkey_manager:
            logger.info("正在停止热键监听...")
            self.hotkey_manager.stop_listening()
            logger.info("热键监听已停止")

        if self.tray_manager:
            logger.info("正在停止托盘图标...")
            self.tray_manager.stop()
            logger.info("托盘图标已停止")

        if self.floating_window:
            logger.info("正在关闭悬浮窗...")
            self.floating_window.hide()
            self.floating_window = None
            logger.info("悬浮窗已关闭")

        if self.translator:
            logger.info("正在停止本地模型工作进程...")
            self.translator.close()
            logger.info("本地模型工作进程已停止")

        logger.info("程序已优雅退出")


def main():
    """程序入口"""
    single_instance = SingleInstanceChecker()
    if not single_instance.check():
        logger.warning("检测到已运行的 Type4Y 实例，正在激活该窗口...")
        ctypes.windll.user32.MessageBoxW(0, "Type4Y 已在运行中！\n请通过系统托盘访问程序。", f"{APP_NAME} 提示", 0x00000040)
        single_instance.release()
        sys.exit(0)

    app = TranslationApp()
    app.start()
    single_instance.release()


if __name__ == "__main__":
    main()
