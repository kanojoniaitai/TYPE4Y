"""
托盘管理器模块 - 系统托盘图标和菜单

核心功能：
1. 创建和管理系统托盘图标
2. 提供托盘菜单（配置、关于、重启热键、退出）
3. 显示托盘通知
4. 确保单例运行，防止重复托盘
"""

import threading
import time
from typing import Callable, Optional
from PIL import Image, ImageDraw, ImageFont
import pystray
from src.app_settings import APP_NAME, APP_VERSION
from src.logger import get_logger

logger = get_logger("tray_manager")

_icon_instance: Optional['TrayManager'] = None


class TrayManager:
    """
    托盘管理器 - 提供系统托盘图标和菜单管理

    特性：
    - 自定义图标设计
    - 丰富的托盘菜单
    - 托盘气泡通知
    - 单例检测，防止重复托盘
    """

    def __init__(
        self,
        on_exit: Optional[Callable] = None,
        on_open_config: Optional[Callable] = None,
        on_restart_hotkey: Optional[Callable] = None
    ):
        """
        初始化托盘管理器

        Args:
            on_exit: 退出回调
            on_open_config: 打开配置回调
            on_restart_hotkey: 重启热键回调
        """
        global _icon_instance
        if _icon_instance is not None:
            logger.warning("已存在托盘实例，尝试关闭旧实例...")
            try:
                _icon_instance.stop()
            except:
                pass

        self.icon: Optional[pystray.Icon] = None
        self.on_exit: Optional[Callable] = on_exit
        self.on_open_config: Optional[Callable] = on_open_config
        self.on_restart_hotkey: Optional[Callable] = on_restart_hotkey
        self._thread: Optional[threading.Thread] = None
        self._running: bool = False
        self._exit_done: bool = False
        _icon_instance = self
        logger.debug("TrayManager 初始化完成")

    def _create_icon(self) -> Image.Image:
        """
        创建托盘图标

        Returns:
            Image.Image: 图标图像
        """
        size = 64
        image = Image.new('RGBA', (size, size), color=(0, 0, 0, 0))
        draw = ImageDraw.Draw(image)

        draw.rounded_rectangle(
            [(0, 0), (size - 1, size - 1)],
            radius=14,
            fill=(255, 255, 255, 255),
        )

        try:
            emoji_font = ImageFont.truetype("seguiemj.ttf", 40)
        except Exception:
            try:
                emoji_font = ImageFont.truetype("C:\\Windows\\Fonts\\seguiemj.ttf", 40)
            except Exception:
                try:
                    emoji_font = ImageFont.truetype("arial.ttf", 36)
                except Exception:
                    emoji_font = ImageFont.load_default()

        text = "🥵"
        bbox = draw.textbbox((0, 0), text, font=emoji_font)
        text_width = bbox[2] - bbox[0]
        text_height = bbox[3] - bbox[1]
        x = (size - text_width) // 2
        y = (size - text_height) // 2 - 3
        draw.text((x, y), text, font=emoji_font, fill=(0, 0, 0, 255))

        return image.convert('RGB')

    def _on_config_clicked(self, icon: pystray.Icon, item: pystray.MenuItem) -> None:
        """配置菜单点击处理"""
        logger.debug("托盘配置按钮被点击")
        if self.on_open_config:
            self.on_open_config()

    def _on_restart_hotkey_clicked(self, icon: pystray.Icon, item: pystray.MenuItem) -> None:
        """重启热键菜单点击处理"""
        logger.debug("托盘重启热键按钮被点击")
        if self.on_restart_hotkey:
            self.on_restart_hotkey()

    def _on_about_clicked(self, icon: pystray.Icon, item: pystray.MenuItem) -> None:
        """关于菜单点击处理"""
        logger.debug("托盘关于按钮被点击")
        self.show_notification(f"{APP_NAME} 本地翻译助手", f"版本 {APP_VERSION}\n快捷键: Ctrl+Y\n\n当前模式: 本地模型\n如热键失效，请点击“重启热键”")

    def _on_exit_clicked(self, icon: pystray.Icon, item: pystray.MenuItem) -> None:
        """退出菜单点击处理"""
        if self._exit_done:
            logger.debug("退出已完成，忽略重复点击")
            return

        logger.debug("托盘退出按钮被点击")
        self._exit_done = True

        if self.on_exit:
            self.on_exit()

        time.sleep(0.1)
        self.stop()

    def _run_icon(self) -> None:
        """运行托盘图标（在线程中执行）"""
        try:
            self.icon.run()
        except Exception as e:
            logger.error(f"托盘图标运行错误: {e}", exc_info=True)

    def show_notification(self, title: str, message: str) -> None:
        """
        显示托盘通知
        
        Args:
            title: 通知标题
            message: 通知内容
        """
        if self.icon and self._running:
            try:
                self.icon.notify(title, message)
                logger.debug(f"显示通知: {title} - {message}")
            except Exception as e:
                logger.error(f"显示通知失败: {e}", exc_info=True)

    def start(self) -> None:
        """启动托盘图标"""
        if self._running:
            logger.debug("托盘图标已在运行中")
            return
        
        menu_items = []
        
        if self.on_open_config:
            menu_items.append(pystray.MenuItem("配置", self._on_config_clicked))
        
        if self.on_restart_hotkey:
            menu_items.append(pystray.MenuItem("重启热键", self._on_restart_hotkey_clicked))
        
        menu_items.append(pystray.MenuItem("关于", self._on_about_clicked))
        menu_items.append(pystray.Menu.SEPARATOR)
        menu_items.append(pystray.MenuItem("退出", self._on_exit_clicked))
        
        self.icon = pystray.Icon(
            APP_NAME,
            self._create_icon(),
            f"{APP_NAME} 本地翻译助手 (Ctrl+Y)",
            menu=pystray.Menu(*menu_items)
        )
        
        self._running = True
        self._thread = threading.Thread(target=self._run_icon, daemon=True)
        self._thread.start()
        logger.debug("托盘图标已启动")

    def stop(self) -> None:
        """停止托盘图标"""
        if not self._running:
            logger.debug("托盘图标未在运行")
            return
        
        self._running = False
        if self.icon:
            try:
                self.icon.stop()
                logger.debug("托盘图标已停止")
            except Exception as e:
                logger.error(f"停止托盘图标失败: {e}", exc_info=True)
            self.icon = None
        
        if self._thread and self._thread.is_alive():
            try:
                self._thread.join(timeout=1)
                self._thread = None
            except Exception as e:
                logger.error(f"等待托盘线程结束失败: {e}", exc_info=True)


def test_tray_manager():
    """测试托盘管理器功能"""
    print("=== 测试 TrayManager ===")
    print("启动系统托盘图标...")
    print("右键点击托盘图标选择'退出'来结束测试")
    print("\n提示: 如果看不到图标，请检查系统托盘区域")
    
    def on_exit():
        print("\n接收到退出信号...")
    
    def on_restart():
        print("\n重启热键...")
    
    tray = TrayManager(on_exit=on_exit, on_restart_hotkey=on_restart)
    
    try:
        tray.start()
        print("✓ 托盘图标已启动")
        print("\n按 Ctrl+C 也可以退出")
        
        import time
        while tray._running:
            time.sleep(0.1)
        
    except KeyboardInterrupt:
        print("\n检测到 Ctrl+C，正在停止...")
    finally:
        tray.stop()
        print("✓ 托盘图标已停止")
        print("\n=== 测试完成 ===")


if __name__ == "__main__":
    test_tray_manager()
