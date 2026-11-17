import ctypes
import json
import logging
import os
import random
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
WM_APP_REST_READY = win32con.WM_APP + 4     # 最短休息已满，遮罩上可以出现“结束休息”按钮

# win32con 未导出 WM_DPICHANGED，手动定义（0x02E0）
WM_DPICHANGED = 0x02E0
# 分辨率/显示器工作区变化（DPI 不变时 Windows 只发这个，不发 WM_DPICHANGED）
WM_DISPLAYCHANGE = 0x007E

# 提示窗口子控件 ID
IDB_SLEEP = 101         # 立即休息
IDB_POSTPONE = 102      # 推迟N分钟
IDC_DND = 103           # 免打扰复选框
IDC_REST_DONE = 104     # 遮罩上的“结束休息”按钮
IDT_PROMPT_TICK = 1     # 倒计时 SetTimer 标识（仅用于刷新显示）

# 低级键盘钩子：遮罩期间吞掉所有按键（Ctrl+Alt+Del 是系统安全序列，无法拦截）
WH_KEYBOARD_LL = 13
IDC_HAND = 32649

# 统一状态机：锁屏与遮罩都只是“休息”的 blocker（阻断器），不是两种状态
STATE_WORKING = "working"
STATE_PROMPTING = "prompting"
STATE_RESTING = "resting"
BLOCKER_OVERLAY = "overlay"
BLOCKER_LOCK = "lock"

# 置顶但不抢键盘焦点
WS_EX_NOACTIVATE = getattr(win32con, "WS_EX_NOACTIVATE", 0x08000000)

# DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2（HANDLE 特殊值 -4）
DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = -4
MONITOR_DEFAULTTONEAREST = 2
MDT_EFFECTIVE_DPI = 0
MDT_RAW_DPI = 2

__version__ = "1.0.0"

# 脚本/程序所在目录：配置、日志、自启动都按此定位。
# PyInstaller frozen 模式下 __file__ 指向临时解压目录，必须改用 exe 所在目录。
if getattr(sys, "frozen", False):
    SCRIPT_DIR = os.path.dirname(os.path.abspath(sys.executable))
else:
    SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# 提示文本（布局按这些文本实测宽度）
PROMPT_TITLE = "护眼休息提醒"
PROMPT_MESSAGE = "该休息了"
PROMPT_DND = "免打扰"
PROMPT_SLEEP = "休息"

# 全屏休息遮罩
OVERLAY_TEXT = "休息中"
OVERLAY_BUTTON = "结束休息"

# 遮罩文案默认列表：简洁、平静，不做可爱风；可在 config.json 的 rest_messages 中覆盖
DEFAULT_REST_MESSAGES = (
    "起来走走吧",
    "喝口水吧",
    "看看远处",
    "让眼睛歇一会儿",
    "站起来活动一下",
    "望望窗外吧",
    "闭眼放松一下",
    "慢慢呼吸",
)
OVERLAY_BG_TOP = (0x0E, 0x11, 0x16)        # 极暗冷色渐变起点（8-bit RGB）
OVERLAY_BG_BOTTOM = (0x05, 0x07, 0x0A)     # 渐变终点
OVERLAY_TEXT_COLOR = 0x00BFB09F            # COLORREF，对应 RGB(0x9F, 0xB0, 0xBF)
# “结束休息”只画文字，不画任何形状
OVERLAY_BTN_TEXT = 0x00998C7E              # RGB(0x7E, 0x8C, 0x99) 默认偏暗
OVERLAY_BTN_TEXT_HOVER = 0x00DED3C7        # RGB(0xC7, 0xD3, 0xDE) 悬停提亮
OVERLAY_BTN_TEXT_PRESSED = 0x00BFB09F      # RGB(0x9F, 0xB0, 0xBF) 按下
OVERLAY_BTN_UNDERLINE = 0x0074685A         # RGB(0x5A, 0x68, 0x74) 常显下划线
OVERLAY_BTN_UNDERLINE_HOVER = 0x00DED3C7   # 悬停时下划线随文字提亮

# 字号换算优先使用显示器的“真实 PPI”（RAW DPI），而不是含用户缩放的有效 DPI，
# 这样同一字号在任何缩放下物理大小一致。超出 60~400 PPI 视为 EDID 不可信，退回有效 DPI。
PROMPT_RAW_DPI_MIN = 60
PROMPT_RAW_DPI_MAX = 400


class _POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


class _POINTL(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


class _RECT(ctypes.Structure):
    _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                ("right", ctypes.c_long), ("bottom", ctypes.c_long)]


class _MONITORINFO(ctypes.Structure):
    _fields_ = [("cbSize", ctypes.c_ulong), ("rcMonitor", _RECT),
                ("rcWork", _RECT), ("dwFlags", ctypes.c_ulong)]


class _SIZE(ctypes.Structure):
    _fields_ = [("cx", ctypes.c_long), ("cy", ctypes.c_long)]


class _MINMAXINFO(ctypes.Structure):
    _fields_ = [("ptReserved", _POINTL), ("ptMaxSize", _POINTL),
                ("ptMaxPosition", _POINTL), ("ptMinTrackSize", _POINTL),
                ("ptMaxTrackSize", _POINTL)]


class _TRIVERTEX(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long),
                ("Red", ctypes.c_ushort), ("Green", ctypes.c_ushort),
                ("Blue", ctypes.c_ushort), ("Alpha", ctypes.c_ushort)]


class _GRADIENT_RECT(ctypes.Structure):
    _fields_ = [("UpperLeft", ctypes.c_ulong), ("LowerRight", ctypes.c_ulong)]


class _DRAWITEMSTRUCT(ctypes.Structure):
    _fields_ = [("CtlType", ctypes.c_uint), ("CtlID", ctypes.c_uint),
                ("itemID", ctypes.c_uint), ("itemAction", ctypes.c_uint),
                ("itemState", ctypes.c_uint), ("hwndItem", ctypes.c_void_p),
                ("hDC", ctypes.c_void_p), ("rcItem", _RECT),
                ("itemData", ctypes.c_void_p)]


class EyeProtector:
    def __init__(self):
        self._set_dpi_aware()
        self.config_file = os.path.join(SCRIPT_DIR, "config.json")
        self.load_config()
        self.setup_logging()

        self.work_timer = None
        self.hwnd = None
        self.running = True

        # 统一状态机（仅在主线程修改）。锁屏/遮罩只是休息的 blocker。
        self.state = STATE_WORKING
        self.rest_blocker = None
        self.rest_started_at = None
        self.rest_enforced = False

        # 软提示相关状态（仅在主线程修改）
        self._hinstance = win32api.GetModuleHandle(None)
        self.postpone_count = 0
        self.dnd_mode = False          # 免打扰：勾选后不锁屏、豁免推迟上限
        self.prompt_hwnd = None
        self.grace_timer = None
        self.prompt_shown_at = None
        self._prompt_msg_static = None
        self._prompt_count_static = None
        self._prompt_dnd = None
        self._prompt_btn_sleep = None
        self._prompt_btn_postpone = None
        self._prompt_win_w = 0
        self._prompt_win_h = 0
        # 提示窗口类只注册一次；保留引用以防被 GC（否则二次弹窗崩溃）
        self._prompt_wc = None
        self._prompt_proc_ref = None
        self._prompt_atom = None
        self._prompt_font = None
        self._prompt_font_owned = False
        self._prompt_font_dpi = 96
        self._prompt_eff_dpi = 96
        # 全屏休息遮罩状态（仅在主线程修改）
        self.overlays = []
        self._rest_ready = False
        self._hover_hwnd = None
        self._pressed_hwnd = None
        self._rest_message = OVERLAY_TEXT
        self._rest_timer = None
        self._overlay_wc = None
        self._overlay_proc_ref = None
        self._overlay_atom = None
        self._overlay_font = None
        self._overlay_btn_font = None
        self._kbd_hook = None
        self._kbd_proc = None
        self._gdi_setup = False
        self._heartbeat = time.time()
        self._exiting = False

    # ---------- 派生状态（不单独存储，避免多个布尔量彼此漂移） ----------

    @property
    def is_resting(self):
        return self.state == STATE_RESTING

    @property
    def prompt_active(self):
        return self.state == STATE_PROMPTING

    @property
    def overlay_active(self):
        return self.state == STATE_RESTING and self.rest_blocker == BLOCKER_OVERLAY

    def _set_dpi_aware(self):
        """声明 Per-Monitor V2 DPI 感知，避免跨屏时窗口/字体错位。"""
        u = ctypes.windll.user32
        try:
            u.SetProcessDpiAwarenessContext.argtypes = [ctypes.c_void_p]
            u.SetProcessDpiAwarenessContext.restype = ctypes.c_bool
            if u.SetProcessDpiAwarenessContext(
                    ctypes.c_void_p(DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2)):
                return
        except Exception:
            pass
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)  # PER_MONITOR_AWARE (v1)
        except Exception:
            try:
                u.SetProcessDPIAware()
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
        # 窗口尺寸由内容自动决定，不再读 prompt_window_width/height（旧配置中的键会被忽略）
        self.prompt_font_size = max(4, config.get("prompt_font_size", 9))
        self.prompt_position = str(config.get("prompt_position", "top-right")).lower()
        if self.prompt_position not in ("center", "top-left", "top-right", "bottom-left", "bottom-right", "top-center"):
            self.prompt_position = "top-right"

        # 休息的实施方式：overlay=全屏遮罩（默认，不锁屏）；lock=锁屏
        self.rest_style = str(config.get("rest_style", "overlay")).lower()
        if self.rest_style not in ("overlay", "lock"):
            self.rest_style = "overlay"

        # 遮罩文案列表：每次休息随机取一条；非法/为空时回退到默认列表
        raw_msgs = config.get("rest_messages", None)
        msgs = []
        if isinstance(raw_msgs, list):
            for m in raw_msgs:
                text = str(m).strip()
                if text:
                    msgs.append(text)
        self.rest_messages = msgs or list(DEFAULT_REST_MESSAGES)

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

    def enter_rest(self, blocker=None):
        """进入休息会话。blocker 默认取 rest_style；锁屏事件可显式指定 BLOCKER_LOCK。

        只在主线程调用；重复调用是幂等的（已在休息中则不做任何事）。
        """
        if self.state == STATE_RESTING:
            return
        blocker = blocker or self.rest_style
        self.state = STATE_RESTING
        self.rest_blocker = blocker
        self.rest_started_at = time.time()
        self.rest_enforced = True
        if blocker == BLOCKER_OVERLAY:
            self.show_overlay()
        else:
            self.logger.info("进入休息，执行锁屏")
            self.lock_screen()

    def leave_rest(self):
        """离开休息的唯一出口：清理 UI、复位计数、回到工作计时。"""
        if self.state != STATE_RESTING:
            return
        self._teardown_overlay()
        self.state = STATE_WORKING
        self.rest_blocker = None
        self.rest_started_at = None
        self.rest_enforced = False
        self.postpone_count = 0
        self.dnd_mode = False
        self.logger.info("休息结束，重置推迟计数与免打扰，回到工作计时")
        self.start_work_timer()

    # ---------- 全屏休息遮罩 ----------

    def _enum_monitors(self):
        """返回每个显示器的完整矩形 [(x, y, w, h), ...]（含任务栏区域）。"""
        u = ctypes.windll.user32
        result = []
        MONITORENUMPROC = ctypes.WINFUNCTYPE(
            ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p,
            ctypes.POINTER(_RECT), ctypes.c_ssize_t)

        def _cb(hmon, hdc, lprc, data):
            mi = _MONITORINFO()
            mi.cbSize = ctypes.sizeof(_MONITORINFO)
            if u.GetMonitorInfoW(hmon, ctypes.byref(mi)):
                r = mi.rcMonitor
                result.append((r.left, r.top, r.right - r.left, r.bottom - r.top))
            return True

        proc = MONITORENUMPROC(_cb)
        u.EnumDisplayMonitors(None, None, proc, 0)
        if not result:
            result.append((0, 0, win32api.GetSystemMetrics(0), win32api.GetSystemMetrics(1)))
        return result

    def _measure_with_font(self, hfont, text):
        if not hfont:
            return 1, 1
        self._setup_gdi()
        u = ctypes.windll.user32
        g = ctypes.windll.gdi32
        hdc = u.GetDC(None)
        size = _SIZE(0, 0)
        try:
            old = g.SelectObject(hdc, ctypes.c_void_p(hfont))
            g.GetTextExtentPoint32W(hdc, text, len(text), ctypes.byref(size))
            if old:
                g.SelectObject(hdc, old)
        finally:
            u.ReleaseDC(None, hdc)
        return max(1, size.cx), max(1, size.cy)

    def _ensure_overlay_fonts(self, dpi):
        if self._overlay_font:
            return
        self._setup_gdi()
        g = ctypes.windll.gdi32
        base = self._font_px(dpi)
        big = g.CreateFontW(-max(1, base * 2), 0, 0, 0, 400, 0, 0, 0, 1,
                            0, 0, 0, 0, "Microsoft YaHei") & 0xFFFFFFFF
        btn = g.CreateFontW(-max(1, (base * 4) // 3), 0, 0, 0, 400, 0, 0, 0, 1,
                            0, 0, 0, 0, "Microsoft YaHei") & 0xFFFFFFFF
        self._overlay_font = big or None
        self._overlay_btn_font = btn or None

    def _release_overlay_fonts(self):
        g = ctypes.windll.gdi32
        for h in (self._overlay_font, self._overlay_btn_font):
            if h:
                try:
                    g.DeleteObject(ctypes.c_void_p(h))
                except Exception:
                    pass
        self._overlay_font = None
        self._overlay_btn_font = None

    def _pick_rest_message(self):
        """从配置的文案列表中随机取一条。"""
        if not self.rest_messages:
            return OVERLAY_TEXT
        return random.choice(self.rest_messages)

    def _rest_button_size(self):
        tw, th = self._measure_with_font(self._overlay_btn_font, OVERLAY_BUTTON)
        px = max(36, (th * 5) // 2)     # 横向留白更足，胶囊更舒展
        py = max(14, th // 2 + 4)
        return (tw + 2 * px, th + 2 * py)

    def _overlay_layout(self, cw, ch):
        """返回（文字矩形, 按钮矩形）。文字在 40% 高度，按钮下移到 75% 高度。"""
        tw, th = self._measure_with_font(self._overlay_font, self._rest_message)
        text_y = int(ch * 0.40) - th // 2
        text_rect = ((cw - tw) // 2, text_y, tw, th)
        bw, bh = self._rest_button_size()
        btn_y = int(ch * 0.75) - bh // 2
        btn_rect = ((cw - bw) // 2, btn_y, bw, bh)
        return text_rect, btn_rect

    def _fill_gradient(self, hdc, cw, ch):
        if cw <= 0 or ch <= 0:
            return
        verts = (_TRIVERTEX * 2)()
        top, bottom = OVERLAY_BG_TOP, OVERLAY_BG_BOTTOM
        verts[0].x, verts[0].y = 0, 0
        verts[0].Red, verts[0].Green, verts[0].Blue = (top[0] * 257, top[1] * 257, top[2] * 257)
        verts[0].Alpha = 0
        verts[1].x, verts[1].y = cw, ch
        verts[1].Red, verts[1].Green, verts[1].Blue = (bottom[0] * 257, bottom[1] * 257, bottom[2] * 257)
        verts[1].Alpha = 0
        rect = _GRADIENT_RECT(0, 1)
        ctypes.windll.msimg32.GradientFill(hdc, verts, 2, ctypes.byref(rect), 1, 0)

    def _draw_rest_label(self, hdc, rect, pressed, hover):
        """只画文字：默认偏暗，悬停提亮并加一条细下划线，按下变暗。"""
        if not self._overlay_btn_font:
            return
        g = ctypes.windll.gdi32
        u = ctypes.windll.user32
        if pressed:
            color = OVERLAY_BTN_TEXT_PRESSED
        elif hover:
            color = OVERLAY_BTN_TEXT_HOVER
        else:
            color = OVERLAY_BTN_TEXT
        g.SetBkMode(hdc, 1)
        g.SetTextColor(hdc, color)
        old = g.SelectObject(hdc, ctypes.c_void_p(self._overlay_btn_font))
        r = _RECT(rect[0], rect[1], rect[0] + rect[2], rect[1] + rect[3])
        u.DrawTextW(hdc, OVERLAY_BUTTON, -1, ctypes.byref(r),
                    win32con.DT_CENTER | win32con.DT_VCENTER | win32con.DT_SINGLELINE)
        if old:
            g.SelectObject(hdc, old)
        # 下划线常显（悬停时与文字一起提亮），让“这是可点的”更明显
        tw, th = self._measure_with_font(self._overlay_btn_font, OVERLAY_BUTTON)
        cx = rect[0] + rect[2] // 2
        ty = rect[1] + (rect[3] - th) // 2
        line = _RECT(cx - tw // 2, ty + th + 5, cx + tw // 2, ty + th + 6)
        color = OVERLAY_BTN_UNDERLINE_HOVER if (hover and not pressed) else OVERLAY_BTN_UNDERLINE
        brush = g.CreateSolidBrush(color)
        try:
            u.FillRect(hdc, ctypes.byref(line), ctypes.c_void_p(brush))
        finally:
            g.DeleteObject(ctypes.c_void_p(brush))

    def _paint_overlay(self, hwnd):
        hdc, ps = win32gui.BeginPaint(hwnd)
        try:
            cr = win32gui.GetClientRect(hwnd)
            cw, ch = cr[2], cr[3]
            self._fill_gradient(hdc, cw, ch)
            g = ctypes.windll.gdi32
            u = ctypes.windll.user32
            g.SetBkMode(hdc, 1)
            text_rect, btn_rect = self._overlay_layout(cw, ch)

            if self._overlay_font:
                g.SetTextColor(hdc, OVERLAY_TEXT_COLOR)
                old = g.SelectObject(hdc, ctypes.c_void_p(self._overlay_font))
                r = _RECT(text_rect[0], text_rect[1],
                          text_rect[0] + text_rect[2], text_rect[1] + text_rect[3])
                u.DrawTextW(hdc, self._rest_message, -1, ctypes.byref(r),
                            win32con.DT_CENTER | win32con.DT_VCENTER | win32con.DT_SINGLELINE)
                if old:
                    g.SelectObject(hdc, old)

            if self._rest_ready:
                self._draw_rest_label(hdc, btn_rect,
                                      self._pressed_hwnd == hwnd,
                                      self._hover_hwnd == hwnd)
        finally:
            win32gui.EndPaint(hwnd, ps)

    def _hit_test_button(self, hwnd, x, y):
        cr = win32gui.GetClientRect(hwnd)
        _, br = self._overlay_layout(cr[2], cr[3])
        return br[0] <= x < br[0] + br[2] and br[1] <= y < br[1] + br[3]

    def _install_kbd_hook(self):
        """安装全局低级键盘钩子：遮罩期间吞掉所有按键。"""
        if self._kbd_hook:
            return
        u = ctypes.windll.user32
        HOOKPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, ctypes.c_int,
                                      ctypes.c_size_t, ctypes.c_ssize_t)

        def _proc(nCode, wparam, lparam):
            if nCode >= 0 and self.overlay_active:
                return 1  # 吞掉按键（Ctrl+Alt+Del 由系统处理，钩子拦不到）
            return u.CallNextHookEx(None, nCode, wparam, lparam)

        self._kbd_proc = HOOKPROC(_proc)
        u.SetWindowsHookExW.argtypes = [ctypes.c_int, HOOKPROC,
                                        ctypes.c_void_p, ctypes.c_uint]
        u.SetWindowsHookExW.restype = ctypes.c_void_p
        u.CallNextHookEx.argtypes = [ctypes.c_void_p, ctypes.c_int,
                                     ctypes.c_size_t, ctypes.c_ssize_t]
        u.CallNextHookEx.restype = ctypes.c_ssize_t
        self._kbd_hook = u.SetWindowsHookExW(
            WH_KEYBOARD_LL, self._kbd_proc, ctypes.c_void_p(self._hinstance), 0)
        if not self._kbd_hook:
            self.logger.warning("键盘钩子安装失败（遮罩仍显示，但 Alt+Tab 等可能逃逸）")

    def _uninstall_kbd_hook(self):
        if self._kbd_hook:
            try:
                ctypes.windll.user32.UnhookWindowsHookEx(ctypes.c_void_p(self._kbd_hook))
            except Exception:
                pass
            self._kbd_hook = None
        self._kbd_proc = None

    def _fit_overlays(self):
        monitors = self._enum_monitors()
        for hwnd, (x, y, w, h) in zip(self.overlays, monitors):
            try:
                win32gui.SetWindowPos(hwnd, win32con.HWND_TOPMOST, x, y, w, h,
                                      win32con.SWP_NOACTIVATE)
            except Exception:
                pass

    def show_overlay(self):
        """显示全屏休息遮罩（每台显示器一个窗口），不锁屏。仅在主线程调用。"""
        # 这里必须用 UI 级守卫（是否已有窗口），不能用派生属性 overlay_active：
        # enter_rest 会先置 state/blocker 再调用本方法，此时 overlay_active 已经为 True，
        # 用它会把自己挡掉，导致遮罩永远不出现。
        if self.overlays:
            return
        self._rest_message = self._pick_rest_message()
        _, eff_dpi, raw_dpi = self._get_target_monitor()
        self._ensure_overlay_fonts(self._font_dpi(eff_dpi, raw_dpi))

        if self._overlay_atom is None:
            wc = win32gui.WNDCLASS()
            wc.lpfnWndProc = self.overlay_wnd_proc
            wc.lpszClassName = "EyeProtectorOverlayClass"
            wc.hInstance = self._hinstance
            wc.hbrBackground = 0  # 背景全部自绘
            # 明确指定窗口光标，否则系统会沿用启动时的“应用启动中”漏斗光标
            wc.hCursor = win32gui.LoadCursor(0, win32con.IDC_ARROW)
            self._overlay_wc = wc
            self._overlay_proc_ref = self.overlay_wnd_proc
            self._overlay_atom = win32gui.RegisterClass(wc)

        style = win32con.WS_POPUP | win32con.WS_VISIBLE
        ex = (win32con.WS_EX_TOPMOST | WS_EX_NOACTIVATE |
              getattr(win32con, "WS_EX_TOOLWINDOW", 0x00000080))
        for (x, y, w, h) in self._enum_monitors():
            hwnd = win32gui.CreateWindowEx(
                ex, self._overlay_atom, OVERLAY_TEXT, style, x, y, w, h,
                0, 0, self._hinstance, None)
            if hwnd:
                self.overlays.append(hwnd)

        self._rest_ready = False
        self._hover_hwnd = None
        self._pressed_hwnd = None
        self._install_kbd_hook()
        self._rest_timer = threading.Timer(self.min_rest_duration, self.on_rest_min_elapsed)
        self._rest_timer.daemon = True
        self._rest_timer.start()
        self.logger.info(
            f"进入休息：显示全屏遮罩（{len(self.overlays)} 个显示器，"
            f"{self.min_rest_duration} 秒后出现结束按钮）")

    def on_rest_min_elapsed(self):
        """最短休息已满（工作线程）：通知主线程添加按钮。"""
        if self.hwnd:
            win32api.PostMessage(self.hwnd, WM_APP_REST_READY, 0, 0)

    def _add_rest_buttons(self):
        if not self.overlay_active or self._rest_ready:
            return
        self._rest_ready = True
        self._hover_hwnd = None
        self._pressed_hwnd = None
        for hwnd in list(self.overlays):
            try:
                win32gui.InvalidateRect(hwnd, None, False)
            except Exception:
                pass
        self.logger.info("最短休息已满，遮罩上显示“结束休息”按钮")

    def on_overlay_release(self):
        """点击“结束休息”：离开休息会话。"""
        if not self.overlay_active or not self._rest_ready:
            return
        rest = time.time() - (self.rest_started_at or time.time())
        self.logger.info(f"用户结束休息（已休息 {rest:.0f} 秒）")
        self.leave_rest()

    def _teardown_overlay(self):
        """仅拆除遮罩 UI：取消计时器、卸载钩子、销毁窗口、释放字体（不改状态）。"""
        if self._rest_timer:
            self._rest_timer.cancel()
            self._rest_timer = None
        self._uninstall_kbd_hook()
        for hwnd in list(self.overlays):
            try:
                win32gui.DestroyWindow(hwnd)
            except Exception:
                pass
        self.overlays = []
        self._rest_ready = False
        self._hover_hwnd = None
        self._pressed_hwnd = None
        self._release_overlay_fonts()

    def overlay_wnd_proc(self, hwnd, msg, wparam, lparam):
        """遮罩窗口过程（主线程）。"""
        try:
            if msg == win32con.WM_ERASEBKGND:
                return 1  # 全部在 WM_PAINT 中绘制，避免闪烁
            if msg == win32con.WM_PAINT:
                self._paint_overlay(hwnd)
                return 0
            if msg == win32con.WM_MOUSEMOVE:
                if self._rest_ready:
                    x, y = win32api.LOWORD(lparam), win32api.HIWORD(lparam)
                    inside = self._hit_test_button(hwnd, x, y)
                    if inside and self._hover_hwnd != hwnd:
                        self._hover_hwnd = hwnd
                        win32gui.InvalidateRect(hwnd, None, False)
                    elif not inside and self._hover_hwnd == hwnd:
                        self._hover_hwnd = None
                        win32gui.InvalidateRect(hwnd, None, False)
                return 0
            if msg == win32con.WM_LBUTTONDOWN:
                if self._rest_ready:
                    x, y = win32api.LOWORD(lparam), win32api.HIWORD(lparam)
                    if self._hit_test_button(hwnd, x, y):
                        self._pressed_hwnd = hwnd
                        try:
                            win32gui.SetCapture(hwnd)
                        except Exception:
                            pass
                        win32gui.InvalidateRect(hwnd, None, False)
                return 0
            if msg == win32con.WM_LBUTTONUP:
                if self._pressed_hwnd == hwnd:
                    x, y = win32api.LOWORD(lparam), win32api.HIWORD(lparam)
                    inside = self._hit_test_button(hwnd, x, y)
                    self._pressed_hwnd = None
                    try:
                        win32gui.ReleaseCapture()
                    except Exception:
                        pass
                    if inside:
                        self.on_overlay_release()
                    else:
                        win32gui.InvalidateRect(hwnd, None, False)
                return 0
            if msg == win32con.WM_SETCURSOR:
                if (lparam & 0xFFFF) == win32con.HTCLIENT:
                    px, py = win32api.GetCursorPos()
                    cx, cy = win32gui.ScreenToClient(hwnd, (px, py))
                    if self._rest_ready and self._hit_test_button(hwnd, cx, cy):
                        win32gui.SetCursor(win32gui.LoadCursor(0, IDC_HAND))
                    else:
                        win32gui.SetCursor(win32gui.LoadCursor(0, win32con.IDC_ARROW))
                    return 1
            if msg == WM_DISPLAYCHANGE:
                self._fit_overlays()
                return 0
            if msg == win32con.WM_DESTROY:
                if hwnd in self.overlays:
                    self.overlays.remove(hwnd)
                return 0
        except Exception as e:
            self.logger.error("overlay_wnd_proc 异常: %s", e, exc_info=True)
        return win32gui.DefWindowProc(hwnd, msg, wparam, lparam)

    # ---------- 提示窗口：DPI / 字体 / 度量 ----------

    def _setup_gdi(self):
        """一次性声明 GDI/User32 的 argtypes，避免 64 位句柄被截断。"""
        if self._gdi_setup:
            return
        u = ctypes.windll.user32
        g = ctypes.windll.gdi32
        g.CreateFontW.restype = ctypes.c_void_p
        g.CreateFontW.argtypes = [ctypes.c_int] * 13 + [ctypes.c_wchar_p]
        g.DeleteObject.argtypes = [ctypes.c_void_p]
        g.DeleteObject.restype = ctypes.c_bool
        g.SelectObject.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        g.SelectObject.restype = ctypes.c_void_p
        g.GetTextExtentPoint32W.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p,
                                            ctypes.c_int, ctypes.POINTER(_SIZE)]
        g.GetTextExtentPoint32W.restype = ctypes.c_bool
        g.SetBkMode.argtypes = [ctypes.c_void_p, ctypes.c_int]
        g.SetBkMode.restype = ctypes.c_int
        g.SetTextColor.argtypes = [ctypes.c_void_p, ctypes.c_uint]
        g.SetTextColor.restype = ctypes.c_uint
        u.GetDC.argtypes = [ctypes.c_void_p]
        u.GetDC.restype = ctypes.c_void_p
        u.ReleaseDC.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        u.ReleaseDC.restype = ctypes.c_int
        u.GetSysColorBrush.restype = ctypes.c_void_p
        u.DrawTextW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_int,
                                ctypes.POINTER(_RECT), ctypes.c_uint]
        u.DrawTextW.restype = ctypes.c_int
        # GradientFill 在 msimg32.dll，不在 gdi32
        ms = ctypes.windll.msimg32
        ms.GradientFill.argtypes = [ctypes.c_void_p, ctypes.POINTER(_TRIVERTEX),
                                    ctypes.c_ulong, ctypes.POINTER(_GRADIENT_RECT),
                                    ctypes.c_ulong, ctypes.c_ulong]
        ms.GradientFill.restype = ctypes.c_bool
        g.CreateSolidBrush.argtypes = [ctypes.c_uint]
        g.CreateSolidBrush.restype = ctypes.c_void_p
        g.CreatePen.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_uint]
        g.CreatePen.restype = ctypes.c_void_p
        g.RoundRect.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int,
                                ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int]
        g.RoundRect.restype = ctypes.c_bool
        g.GetStockObject.restype = ctypes.c_void_p
        u.FillRect.argtypes = [ctypes.c_void_p, ctypes.POINTER(_RECT), ctypes.c_void_p]
        u.FillRect.restype = ctypes.c_int
        self._gdi_setup = True

    def _monitor_info(self, hmon):
        """由 HMONITOR 取（工作区矩形, 有效 DPI, 真实 PPI）。"""
        u = ctypes.windll.user32
        u.GetMonitorInfoW.argtypes = [ctypes.c_void_p, ctypes.POINTER(_MONITORINFO)]
        u.GetMonitorInfoW.restype = ctypes.c_bool

        work = (0, 0, win32api.GetSystemMetrics(0), win32api.GetSystemMetrics(1))
        if hmon:
            mi = _MONITORINFO()
            mi.cbSize = ctypes.sizeof(_MONITORINFO)
            if u.GetMonitorInfoW(hmon, ctypes.byref(mi)):
                rc = mi.rcWork
                work = (rc.left, rc.top, rc.right, rc.bottom)

        eff_dpi = 96
        raw_dpi = 0
        try:
            shcore = ctypes.windll.shcore
            shcore.GetDpiForMonitor.argtypes = [ctypes.c_void_p, ctypes.c_int,
                                                ctypes.POINTER(ctypes.c_uint),
                                                ctypes.POINTER(ctypes.c_uint)]
            shcore.GetDpiForMonitor.restype = ctypes.c_long
            if hmon:
                dx = ctypes.c_uint()
                dy = ctypes.c_uint()
                if shcore.GetDpiForMonitor(hmon, MDT_EFFECTIVE_DPI,
                                           ctypes.byref(dx), ctypes.byref(dy)) == 0:
                    eff_dpi = dx.value or 96
                rx = ctypes.c_uint()
                ry = ctypes.c_uint()
                if shcore.GetDpiForMonitor(hmon, MDT_RAW_DPI,
                                           ctypes.byref(rx), ctypes.byref(ry)) == 0:
                    raw_dpi = rx.value
        except Exception:
            try:
                u.GetDpiForSystem.restype = ctypes.c_uint
                eff_dpi = u.GetDpiForSystem() or 96
            except Exception:
                eff_dpi = 96
        return work, eff_dpi, raw_dpi

    @staticmethod
    def _font_dpi(effective_dpi, raw_dpi):
        """字号换算用的 DPI：优先真实 PPI；超出合理范围说明 EDID 不可信，退回有效 DPI。"""
        if PROMPT_RAW_DPI_MIN <= (raw_dpi or 0) <= PROMPT_RAW_DPI_MAX:
            return raw_dpi
        return effective_dpi

    def _get_target_monitor(self):
        """按光标所在显示器返回（工作区, DPI），便于多屏时出现在正在工作的屏幕上。"""
        u = ctypes.windll.user32
        u.MonitorFromPoint.argtypes = [_POINT, ctypes.c_ulong]
        u.MonitorFromPoint.restype = ctypes.c_void_p
        try:
            mx, my = win32api.GetCursorPos()
            hmon = u.MonitorFromPoint(_POINT(mx, my), MONITOR_DEFAULTTONEAREST)
        except Exception:
            hmon = None
        return self._monitor_info(hmon)

    def _get_window_monitor(self, hwnd):
        """按窗口当前所在显示器返回（工作区, DPI）。"""
        u = ctypes.windll.user32
        u.MonitorFromWindow.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
        u.MonitorFromWindow.restype = ctypes.c_void_p
        try:
            hmon = u.MonitorFromWindow(ctypes.c_void_p(hwnd), MONITOR_DEFAULTTONEAREST)
        except Exception:
            hmon = None
        return self._monitor_info(hmon)

    def _font_px(self, dpi):
        """字号（磅）→ 像素。dpi 传真实 PPI 时，同一字号在任何缩放下物理大小一致。"""
        return max(1, (self.prompt_font_size * dpi) // 72)

    def _set_prompt_font(self, dpi):
        """按指定 DPI 重建字体，返回旧句柄（由调用方在控件销毁后释放）。"""
        self._setup_gdi()
        g = ctypes.windll.gdi32
        px = self._font_px(dpi)
        # GDI 句柄是 32 位，但 c_void_p 读取 64 位 RAX，高位是不确定的垃圾；
        # 掩码到 32 位得到真实句柄，否则 WM_SETFONT 会因句柄非法而失效（文字不显示）。
        hfont = g.CreateFontW(-px, 0, 0, 0, 400, 0, 0, 0, 1, 0, 0, 0, 0,
                              "Microsoft YaHei") & 0xFFFFFFFF
        owned = bool(hfont != 0)
        if not hfont:
            g.GetStockObject.restype = ctypes.c_void_p
            hfont = g.GetStockObject(17) & 0xFFFFFFFF  # DEFAULT_GUI_FONT 兜底
            owned = False
        old = self._prompt_font
        old_owned = self._prompt_font_owned
        self._prompt_font = hfont
        self._prompt_font_owned = owned
        self._prompt_font_dpi = dpi
        return old if old_owned else None

    def _release_font(self, hfont):
        if hfont:
            try:
                ctypes.windll.gdi32.DeleteObject(ctypes.c_void_p(hfont))
            except Exception:
                pass

    def _text_size(self, text):
        """用当前字体实测文本像素尺寸。"""
        self._setup_gdi()
        u = ctypes.windll.user32
        g = ctypes.windll.gdi32
        hdc = u.GetDC(None)
        size = _SIZE(0, 0)
        try:
            old = g.SelectObject(hdc, ctypes.c_void_p(self._prompt_font))
            g.GetTextExtentPoint32W(hdc, text, len(text), ctypes.byref(size))
            if old:
                g.SelectObject(hdc, old)
        finally:
            u.ReleaseDC(None, hdc)
        return max(1, size.cx), max(1, size.cy)

    def _measure_prompt_layout(self, dpi):
        """按字体实测文本，算出客户区尺寸与各控件矩形（全部由字体度量派生）。"""
        fh = self._text_size(PROMPT_MESSAGE)[1]
        # 所有间距/尺寸都是实测字高 fh 的纯比例，没有任何绝对像素常量；
        # max(1, ...) 仅用于防止整除结果为 0。
        margin = max(1, fh // 3)
        gap = max(1, fh // 4)
        pad = max(1, fh)
        row_h = fh + max(1, fh // 8)
        btn_h = fh + max(1, (fh * 2) // 3)

        msg_w = self._text_size(PROMPT_MESSAGE)[0]
        cnt_w = self._text_size(f"{self.grace_seconds} 秒")[0]
        dnd_w = (fh + 4) + self._text_size(PROMPT_DND)[0] + 6
        # 两个按钮等宽：以较长文案为准，避免一宽一窄
        btn_w = max(self._text_size(PROMPT_SLEEP)[0],
                    self._text_size(f"推迟{self.postpone_minutes}分钟")[0]) + 2 * pad

        # 分层布局（自上而下）：消息 / 倒计时 / 免打扰 / 按钮，均居中。
        # 宽度完全由内容决定；由于两个按钮等宽且按较长文案取宽，按钮行天然足够宽，
        # 不再需要额外的固定基准宽度。
        row_msg_w = msg_w + 2 * margin
        row_cnt_w = cnt_w + 2 * margin
        row_dnd_w = dnd_w + 2 * margin
        row_btn_w = 2 * btn_w + gap + 2 * margin
        client_w = max(row_msg_w, row_cnt_w, row_dnd_w, row_btn_w)

        # 消息与倒计时属于一组，间距收紧；与免打扰、按钮之间留常规间距
        small_gap = max(1, gap // 2)
        y1 = margin
        y2 = y1 + row_h + small_gap
        y3 = y2 + row_h + gap
        y4 = y3 + row_h + gap
        client_h = y4 + btn_h + margin

        msg_rect = ((client_w - msg_w) // 2, y1, msg_w, row_h)
        cnt_rect = ((client_w - cnt_w) // 2, y2, cnt_w, row_h)
        dnd_rect = ((client_w - dnd_w) // 2, y3, dnd_w, row_h)
        bx = (client_w - (2 * btn_w + gap)) // 2
        b1_rect = (bx, y4, btn_w, btn_h)
        b2_rect = (bx + btn_w + gap, y4, btn_w, btn_h)

        style = win32con.WS_CAPTION | win32con.WS_SYSMENU | win32con.WS_VISIBLE
        ex = WS_EX_NOACTIVATE | win32con.WS_EX_TOPMOST | win32con.WS_EX_DLGMODALFRAME
        u = ctypes.windll.user32
        # 用带 DPI 参数的版本，否则非客户区会按调用线程的 DPI（而非目标显示器）计算
        r = _RECT(0, 0, client_w, client_h)
        ok = False
        try:
            u.AdjustWindowRectExForDpi.argtypes = [ctypes.POINTER(_RECT), ctypes.c_ulong,
                                                   ctypes.c_bool, ctypes.c_ulong, ctypes.c_uint]
            u.AdjustWindowRectExForDpi.restype = ctypes.c_bool
            ok = u.AdjustWindowRectExForDpi(ctypes.byref(r), style, False, ex, dpi)
        except Exception:
            ok = False
        if not ok:
            # 注意：user32 导出的名字是 AdjustWindowRectEx（没有 W 后缀）
            u.AdjustWindowRectEx.argtypes = [ctypes.POINTER(_RECT), ctypes.c_ulong,
                                             ctypes.c_bool, ctypes.c_ulong]
            r = _RECT(0, 0, client_w, client_h)
            u.AdjustWindowRectEx(ctypes.byref(r), style, False, ex)
        win_w = r.right - r.left
        win_h = r.bottom - r.top

        return {
            "client_w": client_w, "client_h": client_h,
            "win_w": win_w, "win_h": win_h,
            "msg": msg_rect, "dnd": dnd_rect, "count": cnt_rect,
            "btn_sleep": b1_rect, "btn_postpone": b2_rect,
        }

    def _prompt_position(self, work, win_w, win_h, dpi):
        """在目标显示器工作区内计算窗口左上角。"""
        left, top, right, bottom = work
        m = max(8, (dpi * 12) // 96)
        p = self.prompt_position
        if p == "center":
            return (left + (right - left - win_w) // 2, top + (bottom - top - win_h) // 2)
        if p == "top-left":
            return (left + m, top + m)
        if p == "bottom-left":
            return (left + m, bottom - win_h - m)
        if p == "bottom-right":
            return (right - win_w - m, bottom - win_h - m)
        if p == "top-center":
            return (left + (right - left - win_w) // 2, top + m)
        return (right - win_w - m, top + m)  # top-right（默认）

    # ---------- 提示窗口：创建 / 销毁 ----------

    def show_prompt(self):
        """显示休息提示窗口（主线程）。窗口尺寸由内容实测决定。"""
        if self.state != STATE_WORKING:
            return  # 只有工作状态才会弹提示；迟到的消息直接忽略
        if self.work_timer:
            self.work_timer.cancel()
            self.work_timer = None

        self._setup_gdi()
        work, eff_dpi, raw_dpi = self._get_target_monitor()
        self._prompt_eff_dpi = eff_dpi
        old = self._set_prompt_font(self._font_dpi(eff_dpi, raw_dpi))
        self._release_font(old)
        metrics = self._measure_prompt_layout(eff_dpi)
        self._prompt_win_w = metrics["win_w"]
        self._prompt_win_h = metrics["win_h"]

        # 懒注册提示窗口类（仅一次），保留引用以防被 GC
        if self._prompt_atom is None:
            wc = win32gui.WNDCLASS()
            wc.lpfnWndProc = self.prompt_wnd_proc
            wc.lpszClassName = "EyeProtectorPromptClass"
            wc.hInstance = self._hinstance
            wc.hbrBackground = win32con.COLOR_BTNFACE + 1  # 系统色画刷，避免窗口背景未绘制
            wc.hCursor = win32gui.LoadCursor(0, win32con.IDC_ARROW)
            self._prompt_wc = wc
            self._prompt_proc_ref = self.prompt_wnd_proc
            self._prompt_atom = win32gui.RegisterClass(wc)

        x, y = self._prompt_position(work, metrics["win_w"], metrics["win_h"], eff_dpi)
        style = win32con.WS_CAPTION | win32con.WS_SYSMENU | win32con.WS_VISIBLE
        ex = WS_EX_NOACTIVATE | win32con.WS_EX_TOPMOST | win32con.WS_EX_DLGMODALFRAME
        self.prompt_hwnd = win32gui.CreateWindowEx(
            ex, self._prompt_atom, PROMPT_TITLE,
            style, x, y, metrics["win_w"], metrics["win_h"],
            0, 0, self._hinstance, None)

        self.state = STATE_PROMPTING
        self.prompt_shown_at = time.time()
        # 直接创建子控件（pywin32 的 CreateWindowEx 不保证同步派发 WM_CREATE）
        self._create_prompt_controls(self.prompt_hwnd, metrics)

        # 宽限定时器仍由独立守护线程执行，避免依赖 UI 事件循环
        self.grace_timer = threading.Timer(self.grace_seconds, self.on_grace_expired)
        self.grace_timer.daemon = True
        self.grace_timer.start()
        # 仅用于刷新倒计时显示的 1 秒定时器（非权威）
        ctypes.windll.user32.SetTimer(int(self.prompt_hwnd), IDT_PROMPT_TICK, 1000, 0)

        behavior = "自动跳过（免打扰）" if self.dnd_mode else "自动锁屏"
        self.logger.info(f"显示休息提示，{self.grace_seconds}秒无操作将{behavior}")

    def _create_prompt_controls(self, hwnd, metrics):
        """按度量结果创建子控件：消息与免打扰同一行（左 / 右），倒计时居中，按钮贴底。"""
        font = self._prompt_font
        u = ctypes.windll.user32

        def make(cls, text, style, rect, cid):
            x, y, w, h = rect
            hw = win32gui.CreateWindowEx(
                0, cls, text, win32con.WS_CHILD | win32con.WS_VISIBLE | style,
                x, y, w, h, hwnd, cid, self._hinstance, None)
            win32gui.SendMessage(hw, win32con.WM_SETFONT, font, 1)
            return hw

        self._prompt_msg_static = make(
            "Static", PROMPT_MESSAGE,
            win32con.SS_LEFT | win32con.SS_CENTERIMAGE,
            metrics["msg"], 0)

        self._prompt_dnd = make(
            "Button", PROMPT_DND,
            win32con.WS_TABSTOP | win32con.BS_AUTOCHECKBOX,
            metrics["dnd"], IDC_DND)
        win32gui.SendMessage(
            self._prompt_dnd, win32con.BM_SETCHECK,
            win32con.BST_CHECKED if self.dnd_mode else win32con.BST_UNCHECKED, 0)

        self._prompt_count_static = make(
            "Static", f"{self.grace_seconds} 秒",
            win32con.SS_CENTER | win32con.SS_CENTERIMAGE,
            metrics["count"], 0)

        self._prompt_btn_sleep = make(
            "Button", PROMPT_SLEEP,
            win32con.WS_TABSTOP | win32con.BS_PUSHBUTTON,
            metrics["btn_sleep"], IDB_SLEEP)

        self._prompt_btn_postpone = make(
            "Button", f"推迟{self.postpone_minutes}分钟",
            win32con.WS_TABSTOP | win32con.BS_PUSHBUTTON,
            metrics["btn_postpone"], IDB_POSTPONE)

    def _destroy_prompt_controls(self):
        for h in (self._prompt_msg_static, self._prompt_count_static,
                  self._prompt_dnd, self._prompt_btn_sleep, self._prompt_btn_postpone):
            if h:
                try:
                    win32gui.DestroyWindow(h)
                except Exception:
                    pass
        self._prompt_msg_static = None
        self._prompt_count_static = None
        self._prompt_dnd = None
        self._prompt_btn_sleep = None
        self._prompt_btn_postpone = None

    def _on_dpi_changed(self, hwnd, wparam, lparam):
        """窗口跨到不同 DPI 的显示器：重建字体、重算尺寸、重排控件。"""
        _, eff_dpi, raw_dpi = self._get_window_monitor(hwnd)
        dpi = (wparam & 0xFFFF) or eff_dpi or 96
        self._prompt_eff_dpi = dpi
        old = self._set_prompt_font(self._font_dpi(dpi, raw_dpi))
        metrics = self._measure_prompt_layout(dpi)
        self._prompt_win_w = metrics["win_w"]
        self._prompt_win_h = metrics["win_h"]
        try:
            rect = ctypes.cast(ctypes.c_void_p(lparam), ctypes.POINTER(_RECT)).contents
            x, y = rect.left, rect.top
        except Exception:
            x, y = 0, 0
        self._destroy_prompt_controls()
        win32gui.SetWindowPos(
            hwnd, 0, x, y, metrics["win_w"], metrics["win_h"],
            win32con.SWP_NOZORDER | win32con.SWP_NOACTIVATE)
        self._create_prompt_controls(hwnd, metrics)
        self._release_font(old)
        self.logger.info(f"提示窗口 DPI 变化，已按 {dpi} DPI 重排")

    def _on_display_change(self, hwnd):
        """分辨率/工作区变化：DPI 变了就重建字体与控件，否则只重新定位到新的工作区角落。"""
        work, eff_dpi, raw_dpi = self._get_window_monitor(hwnd)
        font_dpi = self._font_dpi(eff_dpi, raw_dpi)
        if eff_dpi != self._prompt_eff_dpi or font_dpi != self._prompt_font_dpi:
            self._prompt_eff_dpi = eff_dpi
            old = self._set_prompt_font(font_dpi)
            metrics = self._measure_prompt_layout(eff_dpi)
            self._prompt_win_w = metrics["win_w"]
            self._prompt_win_h = metrics["win_h"]
            self._destroy_prompt_controls()
            x, y = self._prompt_position(work, metrics["win_w"], metrics["win_h"], eff_dpi)
            win32gui.SetWindowPos(
                hwnd, 0, x, y, metrics["win_w"], metrics["win_h"],
                win32con.SWP_NOZORDER | win32con.SWP_NOACTIVATE)
            self._create_prompt_controls(hwnd, metrics)
            self._release_font(old)
        else:
            rect = win32gui.GetWindowRect(hwnd)
            w = rect[2] - rect[0]
            h = rect[3] - rect[1]
            x, y = self._prompt_position(work, w, h, eff_dpi)
            win32gui.SetWindowPos(
                hwnd, 0, x, y, 0, 0,
                win32con.SWP_NOSIZE | win32con.SWP_NOZORDER | win32con.SWP_NOACTIVATE)
        self.logger.info(f"显示设置变化，提示窗口已重新定位（dpi={eff_dpi}）")

    def _teardown_prompt(self):
        """仅销毁提示窗口 UI（幂等）；状态由调用方负责。"""
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
        self._prompt_msg_static = None
        self._prompt_count_static = None
        self._prompt_dnd = None
        self._prompt_btn_sleep = None
        self._prompt_btn_postpone = None

    # ---------- 提示窗口：行为 ----------

    def on_prompt_sleep(self):
        """点击“休息”：进入休息。"""
        if self.state != STATE_PROMPTING:
            return
        self.logger.info("用户选择立即休息")
        self._teardown_prompt()
        self.enter_rest()

    def _postpone_without_prompt(self):
        """按一次推迟处理，但不要求提示窗口仍存在。"""
        if self.dnd_mode:
            # 免打扰：不打断，也不计入上限
            self.logger.info(f"免打扰中，跳过本轮，{self.postpone_minutes}分钟后再次提示")
            self.state = STATE_WORKING
            self.start_work_timer(self.postpone_minutes)
            return
        if self.postpone_count >= self.max_postpones:
            self.logger.warning(f"跳过次数已达上限({self.postpone_count}/{self.max_postpones})，强制休息")
            self.enter_rest()
            return
        self.postpone_count += 1
        self.logger.info(f"跳过本轮({self.postpone_count}/{self.max_postpones})，{self.postpone_minutes}分钟后再次提示")
        self.state = STATE_WORKING
        self.start_work_timer(self.postpone_minutes)

    def on_prompt_postpone(self):
        """点击“推迟”或关闭窗口(X)：临时跳过。"""
        if self.state != STATE_PROMPTING:
            return
        self._teardown_prompt()
        self._postpone_without_prompt()

    def on_grace_expired(self):
        """宽限定时器（工作线程）回调：仅通知主线程。"""
        if self.hwnd:
            win32api.PostMessage(self.hwnd, WM_APP_GRACE_EXPIRED, 0, 0)

    def on_grace_timeout(self):
        """主线程收到宽限期满消息：免打扰则跳过，否则强制休息。"""
        if self.state != STATE_PROMPTING:
            return
        self._teardown_prompt()
        if self.dnd_mode:
            self.logger.info(f"宽限期满({self.grace_seconds}秒)，免打扰中，跳过本轮")
            self._postpone_without_prompt()
        else:
            self.logger.warning(f"宽限期满({self.grace_seconds}秒)，强制休息")
            self.enter_rest()

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
                elif ctrl == IDC_DND:
                    checked = (win32gui.SendMessage(self._prompt_dnd, win32con.BM_GETCHECK, 0, 0)
                               == win32con.BST_CHECKED)
                    self.dnd_mode = checked
                    self.logger.info("免打扰已" + ("开启" if checked else "关闭"))
                return 0
            if msg == win32con.WM_CLOSE:
                self.on_prompt_postpone()  # 关闭(X) == 推迟
                return 0  # 不走 DefWindowProc，避免二次 DestroyWindow
            if msg in (win32con.WM_CTLCOLORSTATIC, win32con.WM_CTLCOLORBTN):
                hdc = wparam
                ctypes.windll.gdi32.SetBkMode(hdc, 1)  # TRANSPARENT
                ctypes.windll.gdi32.SetTextColor(
                    hdc, ctypes.windll.user32.GetSysColor(win32con.COLOR_WINDOWTEXT))
                return ctypes.windll.user32.GetSysColorBrush(win32con.COLOR_BTNFACE)
            if msg == win32con.WM_TIMER:
                remaining = self.grace_seconds - int(time.time() - self.prompt_shown_at)
                if remaining < 0:
                    remaining = 0
                if remaining > 0:
                    text = f"{remaining} 秒"
                else:
                    text = "正在跳过…" if self.dnd_mode else "正在锁屏…"
                if self._prompt_count_static:
                    win32gui.SetWindowText(self._prompt_count_static, text)
                return 0
            if msg == WM_DPICHANGED:
                self._on_dpi_changed(hwnd, wparam, lparam)
                return 0
            if msg == WM_DISPLAYCHANGE:
                self._on_display_change(hwnd)
                return 0
            if msg == win32con.WM_GETMINMAXINFO:
                info = ctypes.cast(ctypes.c_void_p(lparam),
                                   ctypes.POINTER(_MINMAXINFO)).contents
                info.ptMinTrackSize.x = self._prompt_win_w or 1
                info.ptMinTrackSize.y = self._prompt_win_h or 1
                return 0
            if msg == win32con.WM_DESTROY:
                self.prompt_hwnd = None
                return 0
        except Exception as e:
            self.logger.error("prompt_wnd_proc 异常: %s", e, exc_info=True)
        return win32gui.DefWindowProc(hwnd, msg, wparam, lparam)

    # ---------- 会话事件（主线程） ----------

    def on_unlock(self):
        """解锁事件处理：锁屏休息按停留时长判定；自愿锁屏只恢复工作计时。"""
        if self.state == STATE_RESTING and self.rest_blocker == BLOCKER_LOCK:
            elapsed = time.time() - (self.rest_started_at or time.time())
            if self.rest_enforced and elapsed < self.min_rest_duration:
                self.logger.warning(f"休息时间不足（仅{elapsed:.1f}秒），重置休息并再次锁屏")
                # 重新锁屏会触发 on_lock，由它重新开始计时（解锁过早不累计）
                self.rest_started_at = None
                t = threading.Timer(1, self.lock_screen)
                t.daemon = True
                t.start()
                return
            self.logger.info(f"休息结束（{elapsed:.0f} 秒）")
            self.leave_rest()
            return

        if self.state == STATE_WORKING:
            self.start_work_timer()

    def on_lock(self):
        """锁屏事件处理：按当前状态决定是“休息继续/开始”还是“自愿暂停”。"""
        now = time.time()

        if self.state == STATE_RESTING:
            if self.rest_blocker != BLOCKER_LOCK:
                # 遮罩休息期间锁屏：切换 blocker，休息不中断
                self._teardown_overlay()
                self.rest_blocker = BLOCKER_LOCK
                self.logger.info("遮罩期间锁屏，转入锁屏休息")
            if self.rest_started_at is None:
                self.rest_started_at = now  # 提前解锁后的重新锁屏：重新计时
            return

        if self.state == STATE_PROMPTING:
            self._teardown_prompt()
            self.state = STATE_RESTING
            self.rest_blocker = BLOCKER_LOCK
            self.rest_started_at = now
            self.rest_enforced = True
            self.logger.info("提示期间锁屏，进入休息")
            return

        # WORKING：自愿锁屏，暂停工作计时，不强制最短休息
        self.state = STATE_RESTING
        self.rest_blocker = BLOCKER_LOCK
        self.rest_started_at = now
        self.rest_enforced = False
        if self.work_timer:
            self.work_timer.cancel()
            self.work_timer = None
        self.logger.info("工作中锁屏，暂停工作计时")

    def stop(self):
        """停止程序"""
        self.running = False

        # 取消所有定时器
        if self.grace_timer:
            self.grace_timer.cancel()
        if self.work_timer:
            self.work_timer.cancel()
        self._teardown_prompt()
        self._teardown_overlay()

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
                if self.state == STATE_WORKING:
                    self.show_prompt()
                else:
                    self.logger.info("忽略迟到的休息提示（当前不在工作状态）")
                return 0
            if msg == WM_APP_HARD_LOCK:
                if self.state == STATE_WORKING:
                    self.enter_rest()
                else:
                    self.logger.info("忽略迟到的强制休息（当前不在工作状态）")
                return 0
            if msg == WM_APP_GRACE_EXPIRED:
                self.on_grace_timeout()
                return 0
            if msg == WM_APP_REST_READY:
                self._add_rest_buttons()
                return 0
        except Exception as e:
            self.logger.error("wnd_proc 异常: %s", e, exc_info=True)
        return win32gui.DefWindowProc(hwnd, msg, wparam, lparam)


def _cli(argv):
    """命令行入口：安装版与分发脚本复用同一套逻辑。返回进程退出码。"""
    cmd = argv[0] if argv else ""
    if cmd in ("--version", "-V"):
        print(__version__)
        return 0
    if cmd == "--install":
        import install_service
        return 0 if install_service.install_shortcut() else 1
    if cmd == "--uninstall":
        import uninstall_service
        uninstall_service.uninstall()
        return 0
    if cmd == "--start":
        import procutil
        if procutil.is_running():
            print("eye_protect 已在运行")
            return 0
        return 0 if procutil.start_background() else 1
    if cmd == "--stop":
        import procutil
        pids = procutil.find_eye_protect_pids()
        if not pids:
            print("eye_protect 未在运行")
            return 0
        procutil.stop_pids(pids)
        return 0
    if cmd == "--restart":
        import restart_service
        return 0 if restart_service.restart() else 1
    if cmd == "--upgrade":
        import updater
        return updater.run_upgrade(__version__)
    print(f"未知参数: {cmd}")
    print("用法: EyeProtect.exe [--version|--install|--uninstall|--start|--stop|--restart|--upgrade]")
    return 2


if __name__ == "__main__":
    if len(sys.argv) > 1:
        sys.exit(_cli(sys.argv[1:]))

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
