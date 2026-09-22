import ctypes
import json
import logging
import os
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

import win32api
import win32con
import win32gui
import win32ts

# Windows 消息常量
WM_WTSSESSION_CHANGE = 0x02B1
WTS_SESSION_LOCK = 0x7
WTS_SESSION_UNLOCK = 0x8

# 应用私有窗口消息（WM_APP 段，跨线程：工作线程 → 主线程）
WM_APP_PROMPT = win32con.WM_APP + 1         # 显示休息提示（软提示模式）
WM_APP_HARD_LOCK = win32con.WM_APP + 2      # 直接锁屏（硬锁模式）
WM_APP_GRACE_EXPIRED = win32con.WM_APP + 3  # 宽限期满（工作线程通知主线程）

# 提示窗口子控件 ID
IDB_SLEEP = 101         # 立即休息
IDB_POSTPONE = 102      # 推迟N分钟
IDT_PROMPT_TICK = 1     # 倒计时 SetTimer 标识（仅用于刷新显示）

# 置顶但不抢键盘焦点
WS_EX_NOACTIVATE = getattr(win32con, "WS_EX_NOACTIVATE", 0x08000000)

# 脚本所在目录：配置/日志按此定位，避免任务计划程序以 System32 为 CWD 时找不到/写不进
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


class EyeProtector:
    def __init__(self):
        self._set_dpi_aware()
        self.config_file = os.path.join(SCRIPT_DIR, "config.json")
        self.load_config()
        self.setup_logging()

        self.work_timer = None
        self.lock_time = None
        self.is_resting = False
        self.hwnd = None
        self.running = True

        # 软提示相关状态（仅在主线程修改）
        self._hinstance = win32api.GetModuleHandle(None)
        self.postpone_count = 0
        self.prompt_hwnd = None
        self.prompt_active = False
        self.grace_timer = None
        self.prompt_shown_at = None
        self._prompt_msg_static = None
        self._prompt_count_static = None
        # 提示窗口类只注册一次；保留引用以防被 GC（否则二次弹窗崩溃）
        self._prompt_wc = None
        self._prompt_proc_ref = None
        self._prompt_atom = None
        self._prompt_font = None
        self._gdi_setup = False
        self._heartbeat = time.time()
        self._exiting = False

    def _set_dpi_aware(self):
        """声明进程 DPI 感知，避免系统整体放大导致窗口/字体偏大。必须在创建窗口前调用。"""
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)  # PER_MONITOR_AWARE
        except Exception:
            try:
                ctypes.windll.user32.SetProcessDPIAware()
            except Exception:
                pass

    def load_config(self):
        default_config = {
            "work_duration_minutes": 20,
            "min_rest_duration_seconds": 20,
            "log_dir": "logs",
            "lock_mode": "prompt",
            "grace_seconds": 60,
            "postpone_minutes": 5,
            "max_postpones": 3,
            "prompt_window_width": 360,
            "prompt_window_height": 160,
            "prompt_font_size": 9,
            "prompt_position": "top-right",
        }

        if os.path.exists(self.config_file):
            # utf-8-sig tolerates a UTF-8 BOM (some Windows editors / Set-Content write one),
            # and reads BOM-less files identically to plain utf-8.
            with open(self.config_file, 'r', encoding='utf-8-sig') as f:
                config = json.load(f)
        else:
            # 首次运行：优先从 config.example.json 复制（带示例值的模板），
            # 否则用代码内默认值。config.json 始终是本地文件（gitignored）。
            example = os.path.join(SCRIPT_DIR, "config.example.json")
            if os.path.exists(example):
                with open(example, 'r', encoding='utf-8-sig') as f:
                    config = json.load(f)
            else:
                config = default_config
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(config, f, indent=4, ensure_ascii=False)

        self.work_duration = config.get("work_duration_minutes", 20)
        self.min_rest_duration = config.get("min_rest_duration_seconds", 20)
        log_dir = config.get("log_dir", "logs")
        self.log_dir = log_dir if os.path.isabs(log_dir) else os.path.join(SCRIPT_DIR, log_dir)

        # 锁屏模式：prompt=软提示（默认），hard=到点直接锁屏（家庭用）
        self.lock_mode = str(config.get("lock_mode", "prompt")).lower()
        if self.lock_mode not in ("prompt", "hard"):
            self.lock_mode = "prompt"
        # 钳制零/负值，避免边界配置导致异常
        self.grace_seconds = max(1, config.get("grace_seconds", 60))
        self.postpone_minutes = max(1, config.get("postpone_minutes", 5))
        self.max_postpones = max(0, config.get("max_postpones", 3))
        self.prompt_window_width = max(300, config.get("prompt_window_width", 360))
        self.prompt_window_height = max(160, config.get("prompt_window_height", 160))
        self.prompt_font_size = max(4, config.get("prompt_font_size", 9))
        self.prompt_position = str(config.get("prompt_position", "top-right")).lower()
        if self.prompt_position not in ("center", "top-left", "top-right", "bottom-left", "bottom-right", "top-center"):
            self.prompt_position = "top-right"

    def setup_logging(self):
        Path(self.log_dir).mkdir(exist_ok=True)
        log_file = os.path.join(self.log_dir, f"eye_protect_{datetime.now().strftime('%Y%m%d')}.log")

        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s [%(levelname)s] %(message)s',
            handlers=[
                logging.FileHandler(log_file, encoding='utf-8'),
                logging.StreamHandler()
            ]
        )
        self.logger = logging.getLogger(__name__)

    # ---------- 计时与锁屏 ----------

    def lock_screen(self):
        """强制锁屏（LockWorkStation 线程安全，可由任意线程调用）。"""
        ctypes.windll.user32.LockWorkStation()

    def start_work_timer(self, duration_minutes=None):
        """开始工作计时。duration_minutes 为 None 时用完整工作时长；否则用于推迟后的短计时。"""
        if self.work_timer:
            self.work_timer.cancel()

        minutes = self.work_duration if duration_minutes is None else duration_minutes
        self.work_timer = threading.Timer(minutes * 60, self.on_work_timeout)
        self.work_timer.daemon = True
        self.work_timer.start()
        action = "显示休息提示" if self.lock_mode == "prompt" else "强制锁屏"
        self.logger.info(f"开始工作计时，{minutes}分钟后将{action}")

    def _route_work_timeout(self):
        """根据锁屏模式返回应投递的私有消息常量（纯函数，便于测试）。"""
        if self.lock_mode == "hard":
            return WM_APP_HARD_LOCK
        return WM_APP_PROMPT

    def on_work_timeout(self):
        """工作时间到（工作线程）。仅向主线程投递消息，绝不在此修改共享状态（消除原 is_resting 竞态）。"""
        if not self.hwnd:
            return
        self.logger.warning(f"工作时长已达{self.work_duration}分钟")
        win32api.PostMessage(self.hwnd, self._route_work_timeout(), 0, 0)

    def enter_rest(self):
        """进入休息：标记状态并锁屏。仅在主线程调用。"""
        self.is_resting = True
        self.logger.info("进入休息，执行锁屏")
        self.lock_screen()

    # ---------- 软提示：窗口与状态 ----------

    def _ensure_prompt_font(self):
        """按配置字号（磅）与系统 DPI 创建字体，使不同缩放下尺寸一致。"""
        if self._prompt_font is not None:
            return
        u = ctypes.windll.user32
        g = ctypes.windll.gdi32
        u.GetDpiForSystem.restype = ctypes.c_uint
        dpi = u.GetDpiForSystem() or 96
        px = (self.prompt_font_size * dpi) // 72
        g.CreateFontW.restype = ctypes.c_void_p
        g.CreateFontW.argtypes = [ctypes.c_int] * 13 + [ctypes.c_wchar_p]
        # GDI 句柄是 32 位，但 c_void_p 读取 64 位 RAX，高位是不确定的垃圾；
        # 掩码到 32 位得到真实句柄，否则 WM_SETFONT 会因句柄非法而失效（文字不显示）。
        self._prompt_font = g.CreateFontW(
            -px, 0, 0, 0, 400, 0, 0, 0, 1, 0, 0, 0, 0, "Microsoft YaHei") & 0xFFFFFFFF

        # WM_CTLCOLORSTATIC 用到的 GDI 函数参数类型（HDC/HBRUSH 为指针尺寸，避免 64 位截断）
        g.SetBkMode.argtypes = [ctypes.c_void_p, ctypes.c_int]
        g.SetBkMode.restype = ctypes.c_int
        g.SetTextColor.argtypes = [ctypes.c_void_p, ctypes.c_uint]
        g.SetTextColor.restype = ctypes.c_uint
        u.GetSysColorBrush.restype = ctypes.c_void_p
        self._gdi_setup = True

    def show_prompt(self):
        """显示休息提示窗口（主线程）。"""
        if self.prompt_active or self.is_resting:
            return  # 已在提示/休息中，忽略（重入守卫）
        if self.work_timer:
            self.work_timer.cancel()
            self.work_timer = None

        self._ensure_prompt_font()

        # 懒注册提示窗口类（仅一次），保留引用以防被 GC
        if self._prompt_atom is None:
            wc = win32gui.WNDCLASS()
            wc.lpfnWndProc = self.prompt_wnd_proc
            wc.lpszClassName = "EyeProtectorPromptClass"
            wc.hInstance = self._hinstance
            wc.hbrBackground = win32con.COLOR_BTNFACE + 1  # 系统色画刷，避免窗口背景未绘制
            self._prompt_wc = wc
            self._prompt_proc_ref = self.prompt_wnd_proc
            self._prompt_atom = win32gui.RegisterClass(wc)

        cx = win32api.GetSystemMetrics(win32con.SM_CXSCREEN)
        cy = win32api.GetSystemMetrics(win32con.SM_CYSCREEN)
        w, h = self.prompt_window_width, self.prompt_window_height
        m = 12  # 距屏幕边缘
        p = self.prompt_position
        if p == "center":
            x, y = (cx - w) // 2, (cy - h) // 2
        elif p == "top-left":
            x, y = m, m
        elif p == "bottom-left":
            x, y = m, cy - h - m
        elif p == "bottom-right":
            x, y = cx - w - m, cy - h - m
        elif p == "top-center":
            x, y = (cx - w) // 2, m
        else:  # top-right（默认）
            x, y = cx - w - m, m

        style = win32con.WS_CAPTION | win32con.WS_SYSMENU | win32con.WS_VISIBLE
        ex = WS_EX_NOACTIVATE | win32con.WS_EX_TOPMOST | win32con.WS_EX_DLGMODALFRAME
        self.prompt_hwnd = win32gui.CreateWindowEx(
            ex, self._prompt_atom, "护眼休息提醒",
            style, x, y, w, h, 0, 0, self._hinstance, None)

        self.prompt_active = True
        self.prompt_shown_at = time.time()
        # 直接创建子控件（pywin32 的 CreateWindowEx 不保证同步派发 WM_CREATE）
        self._create_prompt_controls(self.prompt_hwnd)

        # 宽限超时只负责“跳过”本轮，不锁屏；仍由独立守护定时器执行，避免依赖 UI 事件循环
        self.grace_timer = threading.Timer(self.grace_seconds, self.on_grace_expired)
        self.grace_timer.daemon = True
        self.grace_timer.start()
        # 仅用于刷新倒计时显示的 1 秒定时器（非权威）
        ctypes.windll.user32.SetTimer(int(self.prompt_hwnd), IDT_PROMPT_TICK, 1000, 0)

        self.logger.info(f"显示休息提示，{self.grace_seconds}秒无操作将自动跳过")

    def _create_prompt_controls(self, hwnd):
        """创建子控件（在 show_prompt 中直接调用，主线程）。文字框居中变窄、内容精简。"""
        font = self._prompt_font
        cr = win32gui.GetClientRect(hwnd)
        cw, ch = cr[2], cr[3]

        # 消息文字：精简，窄框居中（不占满整行）
        msg_w = 150
        self._prompt_msg_static = win32gui.CreateWindowEx(
            0, "Static", "该休息了",
            win32con.WS_CHILD | win32con.WS_VISIBLE | win32con.SS_CENTER,
            (cw - msg_w) // 2, 10, msg_w, 22, hwnd, 0, self._hinstance, None)
        win32gui.SendMessage(self._prompt_msg_static, win32con.WM_SETFONT, font, 1)

        # 倒计时：窄框居中
        cnt_w = 90
        self._prompt_count_static = win32gui.CreateWindowEx(
            0, "Static", f"{self.grace_seconds} 秒",
            win32con.WS_CHILD | win32con.WS_VISIBLE | win32con.SS_CENTER,
            (cw - cnt_w) // 2, 36, cnt_w, 22, hwnd, 0, self._hinstance, None)
        win32gui.SendMessage(self._prompt_count_static, win32con.WM_SETFONT, font, 1)

        # 两个按钮：贴底，窄而精简
        b1w, b2w, gap, bh = 80, 110, 16, 34
        by = ch - bh - 12
        bx = (cw - (b1w + gap + b2w)) // 2
        btn = win32gui.CreateWindowEx(
            0, "Button", "休息",
            win32con.WS_CHILD | win32con.WS_VISIBLE | win32con.WS_TABSTOP | win32con.BS_PUSHBUTTON,
            bx, by, b1w, bh, hwnd, IDB_SLEEP, self._hinstance, None)
        win32gui.SendMessage(btn, win32con.WM_SETFONT, font, 1)

        btn = win32gui.CreateWindowEx(
            0, "Button", f"推迟{self.postpone_minutes}分钟",
            win32con.WS_CHILD | win32con.WS_VISIBLE | win32con.WS_TABSTOP | win32con.BS_PUSHBUTTON,
            bx + b1w + gap, by, b2w, bh, hwnd, IDB_POSTPONE, self._hinstance, None)
        win32gui.SendMessage(btn, win32con.WM_SETFONT, font, 1)

    def _teardown_prompt(self):
        """唯一且幂等的提示关闭路径。按钮/宽限/锁屏/停止都走这里。"""
        if not self.prompt_active:
            return
        self.prompt_active = False  # 先置位，防止重入
        if self.grace_timer:
            self.grace_timer.cancel()
            self.grace_timer = None
        if self.prompt_hwnd:
            try:
                ctypes.windll.user32.KillTimer(int(self.prompt_hwnd), IDT_PROMPT_TICK)
                win32gui.DestroyWindow(self.prompt_hwnd)
            except Exception as e:
                self.logger.error("提示窗口清理异常: %s", e, exc_info=True)
            self.prompt_hwnd = None

    def on_prompt_sleep(self):
        """点击“立即休息”：立即锁屏进入休息。"""
        if not self.prompt_active:
            return
        self.logger.info("用户选择立即休息")
        self._teardown_prompt()
        self.enter_rest()

    def _postpone_without_prompt(self):
        """按一次推迟处理，但不要求提示窗口仍存在。"""
        if self.postpone_count >= self.max_postpones:
            self.logger.warning(f"跳过次数已达上限({self.postpone_count}/{self.max_postpones})，强制锁屏")
            self.enter_rest()
            return
        self.postpone_count += 1
        self.logger.info(f"跳过本轮({self.postpone_count}/{self.max_postpones})，{self.postpone_minutes}分钟后再次提示")
        self.start_work_timer(self.postpone_minutes)

    def on_prompt_postpone(self):
        """点击“推迟”或关闭窗口(X)：临时跳过，计入上限。"""
        if not self.prompt_active:
            return
        self._teardown_prompt()
        self._postpone_without_prompt()

    def on_grace_expired(self):
        """宽限定时器（工作线程）回调：按“跳过”处理，不锁屏。"""
        if self.hwnd:
            win32api.PostMessage(self.hwnd, WM_APP_GRACE_EXPIRED, 0, 0)

    def on_grace_timeout(self):
        """主线程收到宽限期满消息：关闭提示并按一次推迟处理。"""
        if not self.prompt_active:
            return
        self.logger.info(f"宽限期满({self.grace_seconds}秒)，按跳过处理")
        self._teardown_prompt()
        self._postpone_without_prompt()

    def prompt_wnd_proc(self, hwnd, msg, wparam, lparam):
        """提示窗口过程（主线程）。"""
        try:
            if msg == win32con.WM_CREATE:
                return 0  # 子控件已在 show_prompt 中直接创建
            if msg == win32con.WM_COMMAND:
                ctrl = wparam & 0xFFFF  # LOWORD(wparam) = 控件 ID
                if ctrl == IDB_SLEEP:
                    self.on_prompt_sleep()
                elif ctrl == IDB_POSTPONE:
                    self.on_prompt_postpone()
                return 0
            if msg == win32con.WM_CLOSE:
                self.on_prompt_postpone()  # 关闭(X) == 推迟
                return 0  # 不走 DefWindowProc，避免二次 DestroyWindow
            if msg == win32con.WM_CTLCOLORSTATIC:
                hdc = wparam
                ctypes.windll.gdi32.SetBkMode(hdc, 1)  # TRANSPARENT
                ctypes.windll.gdi32.SetTextColor(hdc, ctypes.windll.user32.GetSysColor(win32con.COLOR_WINDOWTEXT))
                return ctypes.windll.user32.GetSysColorBrush(win32con.COLOR_BTNFACE)
            if msg == win32con.WM_TIMER:
                remaining = self.grace_seconds - int(time.time() - self.prompt_shown_at)
                if remaining < 0:
                    remaining = 0
                text = f"{remaining} 秒" if remaining > 0 else "正在跳过…"
                if self._prompt_count_static:
                    win32gui.SetWindowText(self._prompt_count_static, text)
                return 0
            if msg == win32con.WM_DESTROY:
                self.prompt_hwnd = None
                self.prompt_active = False
                return 0
        except Exception as e:
            self.logger.error("prompt_wnd_proc 异常: %s", e, exc_info=True)
        return win32gui.DefWindowProc(hwnd, msg, wparam, lparam)

    # ---------- 会话事件（主线程） ----------

    def on_unlock(self):
        """解锁事件处理"""
        current_time = time.time()

        if self.is_resting and self.lock_time:
            # 检查休息时长（锁屏时长）
            rest_duration = current_time - self.lock_time
            if rest_duration < self.min_rest_duration:
                self.logger.warning(f"休息时间不足（仅{rest_duration:.1f}秒），重置休息并再次锁屏")
                # 延迟1秒后锁屏，避免立即锁屏
                t = threading.Timer(1, self.lock_screen)
                t.daemon = True
                t.start()
                return
            else:
                # 休息时间达标
                self.is_resting = False
                self.lock_time = None
                self.postpone_count = 0
                self.logger.info("休息达标，重置推迟计数")

        # 正常解锁，开始工作计时
        if not self.is_resting:
            self.start_work_timer()

    def on_lock(self):
        """锁屏事件处理"""
        current_time = time.time()
        self.lock_time = current_time

        # 提示期间手动锁屏：视为开始休息，并清理提示
        if self.prompt_active:
            self._teardown_prompt()
            self.is_resting = True
            self.logger.info("提示期间锁屏，进入休息")
            return

        if not self.is_resting:
            # 非休息状态的锁屏，暂停工作计时
            if self.work_timer:
                self.work_timer.cancel()
                self.work_timer = None
                self.logger.info("检测到锁屏事件，暂停工作计时")

    def stop(self):
        """停止程序"""
        self.running = False

        # 取消所有定时器
        if self.grace_timer:
            self.grace_timer.cancel()
        if self.work_timer:
            self.work_timer.cancel()
        self._teardown_prompt()

        # 发送退出消息
        if self.hwnd:
            win32gui.PostMessage(self.hwnd, win32con.WM_QUIT, 0, 0)

    def _watchdog(self):
        """看门狗：主线程若长时间不泵消息(卡死)则重启进程自愈。"""
        while self.running and not self._exiting:
            time.sleep(60)
            if self._exiting or not self.running:
                return
            stale = time.time() - self._heartbeat
            if stale > 180:
                self.logger.error(f"watchdog: 主线程无响应({stale:.0f}s)，重启进程自愈")
                try:
                    subprocess.Popen([sys.executable, os.path.join(SCRIPT_DIR, "eye_protect.py")])
                except Exception as e:
                    self.logger.error(f"watchdog: 重启失败: {e}")
                os._exit(2)

    def run(self):
        """主循环"""
        # 初始状态：假设刚启动时是解锁状态
        self.start_work_timer()

        # 创建消息窗口
        wc = win32gui.WNDCLASS()
        wc.lpfnWndProc = self.wnd_proc
        wc.lpszClassName = "EyeProtectorClass"
        wc.hInstance = self._hinstance

        class_atom = win32gui.RegisterClass(wc)
        self.hwnd = win32gui.CreateWindow(
            class_atom,
            "EyeProtector",
            0, 0, 0, 0, 0, 0, 0,
            wc.hInstance,
            None
        )

        # 注册会话通知
        win32ts.WTSRegisterSessionNotification(self.hwnd, win32ts.NOTIFY_FOR_THIS_SESSION)

        # 看门狗：主线程若卡死则重启进程自愈
        threading.Thread(target=self._watchdog, daemon=True).start()

        # 非阻塞消息循环
        try:
            while self.running:
                self._heartbeat = time.time()
                # 处理所有待处理的消息
                if win32gui.PumpWaitingMessages():
                    break
                # 短暂休眠避免CPU占用过高
                time.sleep(0.1)
        except KeyboardInterrupt:
            pass

        self._exiting = True
        self.logger.info("程序已退出")

    def wnd_proc(self, hwnd, msg, wparam, lparam):
        """窗口消息处理"""
        try:
            if msg == WM_WTSSESSION_CHANGE:
                if wparam == WTS_SESSION_UNLOCK:
                    self.on_unlock()
                elif wparam == WTS_SESSION_LOCK:
                    self.on_lock()
                return win32gui.DefWindowProc(hwnd, msg, wparam, lparam)
            if msg == WM_APP_PROMPT:
                self.show_prompt()
                return 0
            if msg == WM_APP_HARD_LOCK:
                self.enter_rest()
                return 0
            if msg == WM_APP_GRACE_EXPIRED:
                self.on_grace_timeout()
                return 0
        except Exception as e:
            self.logger.error("wnd_proc 异常: %s", e, exc_info=True)
        return win32gui.DefWindowProc(hwnd, msg, wparam, lparam)


if __name__ == "__main__":
    protector = None
    try:
        protector = EyeProtector()
        protector.run()
    except KeyboardInterrupt:
        if protector:
            protector.stop()
        print("\n程序退出")
    except Exception as e:
        logging.error(f"程序异常: {e}", exc_info=True)
        if protector:
            protector.stop()
