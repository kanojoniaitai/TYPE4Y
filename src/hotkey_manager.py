"""
热键管理器模块 - 线程安全的状态锁

核心功能：
1. 监听全局热键 (Ctrl+Y)
2. 触发翻译回调
3. 防止并发翻译请求

解决的关键问题：
- 热键防抖失效：使用 is_processing 状态锁，确保同一时间只有一个翻译任务在执行
- 线程安全：使用 threading.Lock 保护共享状态
- 后台失效：添加心跳检测和自动恢复机制
"""

import time
import threading
from typing import Callable, Optional
import keyboard
from src.logger import get_logger

logger = get_logger("hotkey_manager")


class HotkeyManager:
    """
    热键管理器 - 提供线程安全的热键监听和状态管理

    特性：
    - 全局热键监听：监听 Ctrl+Y 组合键
    - 状态锁机制：防止并发翻译请求
    - 线程安全：所有状态操作都通过锁保护
    - 自动恢复：心跳检测自动恢复失效的热键监听
    """

    PROCESSING_TIMEOUT = 60.0
    HEARTBEAT_INTERVAL = 30.0
    HOTKEY_CHECK_INTERVAL = 300.0

    def __init__(self, debounce_time: float = 1.0):
        """
        初始化热键管理器

        Args:
            debounce_time: 防抖时间（秒），已弃用，保留用于兼容性
        """
        self.hotkey: str = 'ctrl+y'
        self.callback: Optional[Callable] = None
        self.debounce_time: float = debounce_time
        self.last_trigger_time: float = 0.0
        self.is_listening: bool = False

        self._lock: threading.Lock = threading.Lock()
        self._hotkey_handle: Optional[keyboard.KeyboardEvent] = None

        self._is_processing: bool = False
        self._processing_lock: threading.Lock = threading.Lock()
        self._processing_start_time: float = 0.0

        self._heartbeat_thread: Optional[threading.Thread] = None
        self._heartbeat_running: bool = False
        self._last_heartbeat_time: float = 0.0
        self._hotkey_valid: bool = False

        logger.debug("HotkeyManager 初始化完成")

    def register_callback(self, callback: Callable) -> None:
        """
        注册热键触发时的回调函数

        Args:
            callback: 回调函数，无参数
        """
        with self._lock:
            self.callback = callback
            logger.debug("已注册热键回调函数")

    def is_processing(self) -> bool:
        """
        检查当前是否有翻译任务正在处理

        包含超时检测：如果处理时间超过 60 秒，自动释放锁

        Returns:
            bool: 是否正在处理翻译任务
        """
        with self._processing_lock:
            if self._is_processing:
                elapsed = time.time() - self._processing_start_time
                if elapsed > self.PROCESSING_TIMEOUT:
                    logger.warning(f"处理状态超时 ({elapsed:.1f}秒)，自动释放锁")
                    self._is_processing = False
                    return False
            return self._is_processing

    def set_processing(self, processing: bool) -> None:
        """
        设置翻译任务的处理状态

        这是解决热键防抖失效的核心方法：
        - 在翻译开始时设置为 True
        - 在翻译完成（成功或失败）后设置为 False
        - 在处理期间，所有新的热键触发都会被忽略

        Args:
            processing: 是否正在处理
        """
        with self._processing_lock:
            old_state = self._is_processing
            self._is_processing = processing

            if processing:
                self._processing_start_time = time.time()
                logger.debug("翻译任务开始，锁定热键")
            else:
                elapsed = time.time() - self._processing_start_time if self._processing_start_time else 0
                logger.debug(f"翻译任务结束，解锁热键 (耗时: {elapsed:.1f}秒)")
                self._processing_start_time = 0.0

            if old_state != processing:
                logger.info(f"处理状态变更: {old_state} -> {processing}")

    def _on_hotkey_pressed(self) -> None:
        """
        热键按下时的处理函数

        核心逻辑：
        1. 检查是否有翻译任务正在处理（状态锁，含超时检测）
        2. 如果正在处理，忽略本次触发并记录日志
        3. 如果没有处理，执行回调函数
        4. 回调函数会在子线程中执行，不阻塞热键监听
        """
        logger.debug("检测到热键按下 (Ctrl+Y)")
        self._last_heartbeat_time = time.time()
        self._hotkey_valid = True

        if self.is_processing():
            logger.warning("热键触发被忽略：翻译任务正在处理中")
            return

        current_time = time.time()
        with self._lock:
            if current_time - self.last_trigger_time < self.debounce_time:
                logger.debug(f"防抖: 忽略频繁的热键触发 (间隔: {current_time - self.last_trigger_time:.3f}s)")
                return
            self.last_trigger_time = current_time
            callback = self.callback

        if callback:
            try:
                logger.info("热键触发，开始执行翻译回调")
                callback()
            except Exception as e:
                logger.error(f"热键回调执行错误: {e}", exc_info=True)
                self.set_processing(False)

    def _heartbeat_check(self) -> None:
        """
        心跳检测线程 - 监控热键是否正常工作

        机制：
        - 每 HEARTBEAT_INTERVAL 秒检查一次
        - 如果超过 HOTKEY_CHECK_INTERVAL 秒没有收到热键信号，
          且热键监听状态为正在监听，则尝试恢复热键
        """
        logger.debug("心跳检测线程已启动")
        while self._heartbeat_running:
            try:
                time.sleep(self.HEARTBEAT_INTERVAL)

                if not self._heartbeat_running:
                    break

                with self._lock:
                    if not self.is_listening:
                        continue

                    time_since_last_trigger = time.time() - self._last_heartbeat_time
                    if time_since_last_trigger > self.HOTKEY_CHECK_INTERVAL and not self.is_processing():
                        logger.info(f"热键无响应超过 {time_since_last_trigger:.1f} 秒，尝试恢复...")
                        self._force_recover()

            except Exception as e:
                logger.error(f"心跳检测异常: {e}", exc_info=True)

        logger.debug("心跳检测线程已退出")

    def _force_recover(self) -> None:
        """
        强制恢复热键监听

        移除旧的热键注册并重新注册
        """
        logger.info("执行热键强制恢复...")
        try:
            if self._hotkey_handle:
                try:
                    keyboard.remove_hotkey(self._hotkey_handle)
                    logger.debug("旧热键已移除")
                except Exception as e:
                    logger.debug(f"移除旧热键失败（可能已失效）: {e}")

            time.sleep(0.2)

            self._hotkey_handle = keyboard.add_hotkey(
                self.hotkey,
                self._on_hotkey_pressed
            )
            self._hotkey_valid = True
            self._last_heartbeat_time = time.time()
            logger.info("热键监听已恢复")

        except Exception as e:
            logger.error(f"热键恢复失败: {e}", exc_info=True)

    def start_listening(self) -> None:
        """
        开始监听热键

        使用 keyboard 库注册全局热键监听
        """
        with self._lock:
            if self.is_listening:
                logger.debug("热键监听已在运行中")
                return

            try:
                self._hotkey_handle = keyboard.add_hotkey(
                    self.hotkey,
                    self._on_hotkey_pressed
                )
                self.is_listening = True
                self._last_heartbeat_time = time.time()
                self._hotkey_valid = True
                logger.info(f"热键监听已启动，监听组合键: {self.hotkey}")

                self._heartbeat_running = True
                self._heartbeat_thread = threading.Thread(target=self._heartbeat_check, daemon=True)
                self._heartbeat_thread.start()
                logger.debug("心跳检测已启动")

            except Exception as e:
                logger.error(f"启动热键监听失败: {e}", exc_info=True)

    def stop_listening(self) -> None:
        """
        停止监听热键

        移除已注册的热键监听
        """
        self._heartbeat_running = False

        with self._lock:
            if not self.is_listening:
                logger.debug("热键监听未在运行")
                return

            if self._hotkey_handle:
                try:
                    keyboard.remove_hotkey(self._hotkey_handle)
                    logger.debug("热键已移除")
                except Exception as e:
                    logger.error(f"移除热键失败: {e}", exc_info=True)
                self._hotkey_handle = None

            self.is_listening = False
            logger.info("热键监听已停止")

    def restart_listening(self) -> None:
        """
        重启热键监听

        用于恢复失效的热键监听
        无论当前状态如何，都会强制重新注册热键
        """
        logger.info("正在重启热键监听...")

        with self._lock:
            if self._hotkey_handle:
                try:
                    keyboard.remove_hotkey(self._hotkey_handle)
                    logger.debug("旧热键已移除")
                except Exception as e:
                    logger.debug(f"移除旧热键失败（可能已失效）: {e}")
                self._hotkey_handle = None

            self.is_listening = False
            time.sleep(0.1)

            try:
                self._hotkey_handle = keyboard.add_hotkey(
                    self.hotkey,
                    self._on_hotkey_pressed
                )
                self.is_listening = True
                self._last_heartbeat_time = time.time()
                self._hotkey_valid = True
                logger.info("热键监听已成功重启")
            except Exception as e:
                logger.error(f"重启热键监听失败: {e}", exc_info=True)
                raise

    def set_debounce_time(self, debounce_time: float) -> None:
        """
        设置防抖时间

        Args:
            debounce_time: 防抖时间（秒）
        """
        with self._lock:
            self.debounce_time = max(0.1, debounce_time)
            logger.debug(f"防抖时间已设置为: {self.debounce_time}s")

    def is_active(self) -> bool:
        """
        检查热键监听是否活跃

        Returns:
            bool: 是否正在监听
        """
        with self._lock:
            return self.is_listening

    def get_status(self) -> dict:
        """
        获取热键管理器的当前状态

        Returns:
            dict: 包含监听状态和处理状态的字典
        """
        with self._lock:
            with self._processing_lock:
                elapsed = 0.0
                if self._is_processing and self._processing_start_time:
                    elapsed = time.time() - self._processing_start_time
                return {
                    'is_listening': self.is_listening,
                    'is_processing': self._is_processing,
                    'processing_elapsed': elapsed,
                    'hotkey': self.hotkey,
                    'debounce_time': self.debounce_time,
                    'last_trigger_time': self.last_trigger_time,
                    'hotkey_valid': self._hotkey_valid,
                    'time_since_last_trigger': time.time() - self._last_heartbeat_time if self._last_heartbeat_time else 0
                }


def test_hotkey_manager():
    """测试热键管理器功能"""
    print("=== 测试 HotkeyManager ===")
    print("\n说明:")
    print("1. 热键: CTRL+Y")
    print("2. 状态锁: 同一时间只能有一个翻译任务")
    print("3. 按 CTRL+Y 测试触发")
    print("4. 按 ESC 停止测试\n")

    trigger_count = 0
    lock = threading.Lock()

    def test_callback():
        nonlocal trigger_count

        manager.set_processing(True)

        try:
            print(f"\n[开始] 模拟翻译任务...")
            for i in range(3):
                print(f"  处理中... {i+1}/3")
                time.sleep(1)

            with lock:
                trigger_count += 1
                print(f"[完成] 翻译任务完成! 总次数: {trigger_count}")
        finally:
            manager.set_processing(False)

    manager = HotkeyManager(debounce_time=0.5)
    manager.register_callback(test_callback)

    print("正在启动监听...")
    manager.start_listening()
    print("✓ 监听已启动")
    print(f"监听状态: {manager.is_active()}")
    print("\n等待热键触发... (按 ESC 退出)\n")

    try:
        keyboard.wait('esc')
    except KeyboardInterrupt:
        pass

    print("\n正在停止监听...")
    manager.stop_listening()
    print("✓ 监听已停止")
    print(f"监听状态: {manager.is_active()}")
    print(f"\n总计触发次数: {trigger_count}")
    print("\n=== 测试完成 ===")


if __name__ == "__main__":
    test_hotkey_manager()
