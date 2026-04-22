"""
剪贴板管理器模块 - 安全剪贴板模式

核心功能：
1. 安全地获取选中文本（通过模拟 Ctrl+C）
2. 安全地替换选中文本（通过模拟 Ctrl+V）
3. 备份和恢复原剪贴板内容，避免覆盖用户数据

解决的关键问题：
- 剪贴板竞态条件：使用轮询等待机制确保读取到最新内容
- 剪贴板被占用：使用 try...finally 确保正确释放剪贴板资源
"""

import time
import win32clipboard
import win32con
import win32gui
import ctypes
from ctypes import wintypes
from typing import Optional, List, Tuple, Any
from src.logger import get_logger

logger = get_logger("clipboard_manager")

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

VK_CONTROL = 0x11
VK_C = 0x43
VK_V = 0x56
KEYEVENTF_KEYUP = 0x0002


class ClipboardManager:
    """
    剪贴板管理器 - 提供安全的剪贴板操作
    
    特性：
    - 轮询等待机制：确保在读取前剪贴板已更新
    - 完整的异常处理：避免剪贴板资源泄漏
    - 原内容保护：自动备份和恢复原剪贴板内容
    """
    
    def __init__(self, delay: float = 0.05, poll_interval: float = 0.05, poll_timeout: float = 0.5):
        """
        初始化剪贴板管理器
        
        Args:
            delay: 按键操作后的基础延迟时间（秒）
            poll_interval: 轮询剪贴板的间隔时间（秒）
            poll_timeout: 轮询剪贴板的最大超时时间（秒）
        """
        self.delay = delay
        self.poll_interval = poll_interval
        self.poll_timeout = poll_timeout
        self._original_clipboard: Optional[List[Tuple[int, Any]]] = None
        logger.debug(f"ClipboardManager 初始化完成 (delay={delay}, poll_interval={poll_interval}, poll_timeout={poll_timeout})")

    def _press_key(self, vk_code: int) -> None:
        """按下虚拟键"""
        user32.keybd_event(vk_code, 0, 0, 0)

    def _release_key(self, vk_code: int) -> None:
        """释放虚拟键"""
        user32.keybd_event(vk_code, 0, KEYEVENTF_KEYUP, 0)

    def _send_ctrl_c(self) -> None:
        """
        模拟发送 Ctrl+C 复制快捷键
        
        流程：按下 Ctrl -> 按下 C -> 短暂延迟 -> 释放 C -> 释放 Ctrl
        """
        self._press_key(VK_CONTROL)
        self._press_key(VK_C)
        time.sleep(self.delay)
        self._release_key(VK_C)
        self._release_key(VK_CONTROL)
        logger.debug("已发送 Ctrl+C 复制信号")

    def _send_ctrl_v(self) -> None:
        """
        模拟发送 Ctrl+V 粘贴快捷键
        
        流程：按下 Ctrl -> 按下 V -> 短暂延迟 -> 释放 V -> 释放 Ctrl
        """
        self._press_key(VK_CONTROL)
        self._press_key(VK_V)
        time.sleep(self.delay)
        self._release_key(VK_V)
        self._release_key(VK_CONTROL)
        logger.debug("已发送 Ctrl+V 粘贴信号")

    def _open_clipboard_safe(self, hwnd: int = 0) -> bool:
        """
        安全地打开剪贴板
        
        Args:
            hwnd: 关联的窗口句柄，0 表示当前线程
            
        Returns:
            bool: 是否成功打开剪贴板
        """
        max_retries = 3
        retry_delay = 0.05
        
        for attempt in range(max_retries):
            try:
                if win32clipboard.OpenClipboard(hwnd):
                    return True
            except Exception as e:
                logger.debug(f"打开剪贴板失败 (尝试 {attempt + 1}/{max_retries}): {e}")
                if attempt < max_retries - 1:
                    time.sleep(retry_delay)
        
        return False

    def _get_clipboard_text(self) -> str:
        """
        获取剪贴板中的文本内容
        
        Returns:
            str: 剪贴板中的文本，如果无法获取则返回空字符串
        """
        try:
            win32clipboard.OpenClipboard()
            
            if win32clipboard.IsClipboardFormatAvailable(win32con.CF_UNICODETEXT):
                text = win32clipboard.GetClipboardData(win32con.CF_UNICODETEXT)
                logger.debug(f"成功获取 Unicode 文本，长度: {len(text)}")
                return text
            elif win32clipboard.IsClipboardFormatAvailable(win32con.CF_TEXT):
                text = win32clipboard.GetClipboardData(win32con.CF_TEXT)
                if isinstance(text, bytes):
                    text = text.decode('gbk', errors='ignore')
                logger.debug(f"成功获取 ANSI 文本，长度: {len(text)}")
                return text
            else:
                logger.debug("剪贴板中没有文本内容")
                return ''
                
        except Exception as e:
            logger.error(f"获取剪贴板文本失败: {e}", exc_info=True)
            return ''
        finally:
            try:
                win32clipboard.CloseClipboard()
            except Exception as e:
                logger.debug(f"关闭剪贴板时发生异常: {e}")

    def _set_clipboard_text(self, text: str) -> bool:
        """
        设置剪贴板中的文本内容
        
        Args:
            text: 要设置的文本内容
            
        Returns:
            bool: 是否成功设置
        """
        try:
            win32clipboard.OpenClipboard()
            win32clipboard.EmptyClipboard()
            win32clipboard.SetClipboardData(win32con.CF_UNICODETEXT, text)
            logger.debug(f"成功设置剪贴板文本，长度: {len(text)}")
            return True
            
        except Exception as e:
            logger.error(f"设置剪贴板文本失败: {e}", exc_info=True)
            return False
        finally:
            try:
                win32clipboard.CloseClipboard()
            except Exception as e:
                logger.debug(f"关闭剪贴板时发生异常: {e}")

    def _save_original_clipboard(self) -> bool:
        """
        保存原剪贴板内容
        
        Returns:
            bool: 是否成功保存
        """
        try:
            win32clipboard.OpenClipboard()
            
            formats = []
            fmt = 0
            while True:
                fmt = win32clipboard.EnumClipboardFormats(fmt)
                if fmt == 0:
                    break
                formats.append(fmt)
            
            self._original_clipboard = []
            for fmt in formats:
                try:
                    data = win32clipboard.GetClipboardData(fmt)
                    self._original_clipboard.append((fmt, data))
                except Exception as e:
                    logger.debug(f"无法保存剪贴板格式 {fmt}: {e}")
            
            logger.debug(f"已保存原剪贴板内容，包含 {len(self._original_clipboard)} 种格式")
            return True
            
        except Exception as e:
            logger.error(f"保存原剪贴板内容失败: {e}", exc_info=True)
            self._original_clipboard = None
            return False
        finally:
            try:
                win32clipboard.CloseClipboard()
            except Exception as e:
                logger.debug(f"关闭剪贴板时发生异常: {e}")

    def _restore_original_clipboard(self) -> bool:
        """
        恢复原剪贴板内容
        
        Returns:
            bool: 是否成功恢复
        """
        if self._original_clipboard is None:
            logger.debug("没有需要恢复的剪贴板内容")
            return True
            
        try:
            win32clipboard.OpenClipboard()
            win32clipboard.EmptyClipboard()
            
            restored_count = 0
            for fmt, data in self._original_clipboard:
                try:
                    win32clipboard.SetClipboardData(fmt, data)
                    restored_count += 1
                except Exception as e:
                    logger.debug(f"无法恢复剪贴板格式 {fmt}: {e}")
            
            logger.debug(f"已恢复原剪贴板内容，成功恢复 {restored_count}/{len(self._original_clipboard)} 种格式")
            return True
            
        except Exception as e:
            logger.error(f"恢复原剪贴板内容失败: {e}", exc_info=True)
            return False
        finally:
            try:
                win32clipboard.CloseClipboard()
            except Exception as e:
                logger.debug(f"关闭剪贴板时发生异常: {e}")
            self._original_clipboard = None

    def _wait_for_new_clipboard_content(self) -> bool:
        """
        轮询等待剪贴板有新的文本内容
        
        核心逻辑：
        - 在清空剪贴板后，等待剪贴板出现非空内容
        - 这表示 Ctrl+C 成功复制了选中内容
        - 设置最大超时时间避免无限等待
        
        Returns:
            bool: 是否检测到剪贴板有新内容
        """
        start_time = time.time()
        
        while time.time() - start_time < self.poll_timeout:
            try:
                win32clipboard.OpenClipboard()
                
                if win32clipboard.IsClipboardFormatAvailable(win32con.CF_UNICODETEXT):
                    current_content = win32clipboard.GetClipboardData(win32con.CF_UNICODETEXT)
                    win32clipboard.CloseClipboard()
                    
                    if current_content and current_content.strip():
                        elapsed = time.time() - start_time
                        logger.debug(f"检测到剪贴板有新内容，耗时 {elapsed:.3f} 秒，长度: {len(current_content)}")
                        return True
                
                win32clipboard.CloseClipboard()
                
            except Exception as e:
                logger.debug(f"轮询剪贴板时发生异常: {e}")
                try:
                    win32clipboard.CloseClipboard()
                except:
                    pass
            
            time.sleep(self.poll_interval)
        
        logger.warning(f"轮询剪贴板超时 ({self.poll_timeout} 秒)，未检测到新内容")
        return False

    def get_selected_text(self) -> str:
        """
        获取当前选中的文本

        完整流程：
        1. 保存原剪贴板内容
        2. 清空剪贴板（确保能检测到新内容）
        3. 发送 Ctrl+C 复制选中内容
        4. 轮询等待剪贴板有新内容
        5. 读取剪贴板内容
        6. 恢复原剪贴板内容

        安全机制：
        - finally 块确保无论是否异常都会恢复原剪贴板
        - 如果未保存原内容（保存失败），不会尝试恢复，避免覆盖

        Returns:
            str: 选中的文本内容
        """
        logger.debug("开始获取选中文本...")

        original_saved = False
        selected_text = ''

        try:
            if not self._save_original_clipboard():
                logger.error("无法保存原剪贴板内容，中止操作")
                return ''

            original_saved = True

            try:
                win32clipboard.OpenClipboard()
                win32clipboard.EmptyClipboard()
                win32clipboard.CloseClipboard()
                logger.debug("已清空剪贴板")
            except Exception as e:
                logger.debug(f"清空剪贴板时发生异常: {e}")

            time.sleep(self.delay)

            self._send_ctrl_c()

            if not self._wait_for_new_clipboard_content():
                logger.warning("未检测到剪贴板有新内容，可能未选中文本")
                return ''

            selected_text = self._get_clipboard_text()

            if selected_text and selected_text.strip():
                logger.info(f"成功获取选中文本，长度: {len(selected_text)}")
            else:
                logger.warning("未获取到有效选中文本")
                selected_text = ''

            return selected_text

        except Exception as e:
            logger.error(f"获取选中文本失败: {e}", exc_info=True)
            return ''
        finally:
            if original_saved:
                self._restore_original_clipboard()

    def replace_selected_text(self, new_text: str, target_hwnd: Optional[int] = None) -> bool:
        """
        替换当前选中的文本
        
        完整流程：
        1. 保存原剪贴板内容
        2. 设置新文本到剪贴板
        3. 发送 Ctrl+V 粘贴新内容
        4. 恢复原剪贴板内容
        
        Args:
            new_text: 要替换的新文本
            target_hwnd: 目标窗口句柄（可选，用于日志记录）
            
        Returns:
            bool: 是否成功替换
        """
        logger.debug(f"开始替换选中文本，新文本长度: {len(new_text)}")
        
        try:
            if not self._save_original_clipboard():
                logger.error("无法保存原剪贴板内容，中止操作")
                return False
            
            if not self._set_clipboard_text(new_text):
                logger.error("无法设置剪贴板文本，中止操作")
                return False
            
            time.sleep(self.delay)
            
            self._send_ctrl_v()
            
            logger.info("成功替换选中文本")
            return True
            
        except Exception as e:
            logger.error(f"替换选中文本失败: {e}", exc_info=True)
            return False
        finally:
            self._restore_original_clipboard()

    def set_clipboard_only(self, text: str) -> bool:
        """
        仅将文本设置到剪贴板，不执行粘贴操作
        
        用于窗口焦点丢失时的备用方案
        
        Args:
            text: 要设置的文本内容
            
        Returns:
            bool: 是否成功设置
        """
        try:
            if self._set_clipboard_text(text):
                logger.info(f"已将文本复制到剪贴板，长度: {len(text)}")
                return True
            return False
        except Exception as e:
            logger.error(f"设置剪贴板文本失败: {e}", exc_info=True)
            return False


def test_clipboard_manager():
    """测试剪贴板管理器功能"""
    print("=== 测试 ClipboardManager ===")
    print("\n请在任意文本编辑器中选择一些文本，然后按回车继续...")
    input()
    
    manager = ClipboardManager(delay=0.05, poll_interval=0.05, poll_timeout=0.5)
    
    print("\n正在获取选中文本...")
    selected_text = manager.get_selected_text()
    print(f"✓ 获取到的文本: {selected_text[:100] if selected_text else '(空)'}{'...' if len(selected_text) > 100 else ''}")
    
    if selected_text:
        print("\n正在测试文本替换 (将文本转为大写)...")
        uppercase_text = selected_text.upper()
        success = manager.replace_selected_text(uppercase_text)
        if success:
            print("✓ 替换完成，请检查文本是否已转为大写")
        else:
            print("✗ 替换失败")
    
    print("\n=== 测试完成 ===")


if __name__ == "__main__":
    test_clipboard_manager()
