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

# win32con 未导出 WM_DPICHANGED，手动定义（0x02E0）
WM_DPICHANGED = 0x02E0
# 分辨率/显示器工作区变化（DPI 不变时 Windows 只发这个，不发 WM_DPICHANGED）
WM_DISPLAYCHANGE = 0x007E

# 提示窗口子控件 ID
IDB_SLEEP = 101         # 立即休息
IDB_POSTPONE = 102      # 推迟N分钟
IDC_DND = 103           # 免打扰复选框
IDT_PROMPT_TICK = 1     # 倒计时 SetTimer 标识（仅用于刷新显示）

# 置顶但不抢键盘焦点
WS_EX_NOACTIVATE = getattr(win32con, "WS_EX_NOACTIVATE", 0x08000000)

# DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2（HANDLE 特殊值 -4）
DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = -4
MONITOR_DEFAULTTONEAREST = 2
MDT_EFFECTIVE_DPI = 0
MDT_RAW_DPI = 2

# 脚本所在目录：配置/日志按此定位，避免任务计划程序以 System32 为 CWD 时找不到/写不进
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# 提示文本（布局按这些文本实测宽度）
PROMPT_TITLE = "护眼休息提醒"
PROMPT_MESSAGE = "该休息了"
PROMPT_DND = "免打扰"
PROMPT_SLEEP = "休息"

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
        self.dnd_mode = False          # 免打扰：勾选后不锁屏、豁免推迟上限
        self.prompt_hwnd = None
        self.prompt_active = False
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
        self._gdi_setup = False
        self._heartbeat = time.time()
        self._exiting = False

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
        if self.prompt_active or self.is_resting:
            return  # 已在提示/休息中，忽略（重入守卫）
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

        self.prompt_active = True
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
        self._prompt_msg_static = None
        self._prompt_count_static = None
        self._prompt_dnd = None
        self._prompt_btn_sleep = None
        self._prompt_btn_postpone = None

    # ---------- 提示窗口：行为 ----------

    def on_prompt_sleep(self):
        """点击“休息”：立即锁屏进入休息。"""
        if not self.prompt_active:
            return
        self.logger.info("用户选择立即休息")
        self._teardown_prompt()
        self.enter_rest()

    def _postpone_without_prompt(self):
        """按一次推迟处理，但不要求提示窗口仍存在。"""
        if self.dnd_mode:
            # 免打扰：不锁屏，也不计入上限
            self.logger.info(f"免打扰中，跳过本轮，{self.postpone_minutes}分钟后再次提示")
            self.start_work_timer(self.postpone_minutes)
            return
        if self.postpone_count >= self.max_postpones:
            self.logger.warning(f"跳过次数已达上限({self.postpone_count}/{self.max_postpones})，强制锁屏")
            self.enter_rest()
            return
        self.postpone_count += 1
        self.logger.info(f"跳过本轮({self.postpone_count}/{self.max_postpones})，{self.postpone_minutes}分钟后再次提示")
        self.start_work_timer(self.postpone_minutes)

    def on_prompt_postpone(self):
        """点击“推迟”或关闭窗口(X)：临时跳过。"""
        if not self.prompt_active:
            return
        self._teardown_prompt()
        self._postpone_without_prompt()

    def on_grace_expired(self):
        """宽限定时器（工作线程）回调：仅通知主线程。"""
        if self.hwnd:
            win32api.PostMessage(self.hwnd, WM_APP_GRACE_EXPIRED, 0, 0)

    def on_grace_timeout(self):
        """主线程收到宽限期满消息：免打扰则跳过，否则强制锁屏。"""
        if not self.prompt_active:
            return
        self._teardown_prompt()
        if self.dnd_mode:
            self.logger.info(f"宽限期满({self.grace_seconds}秒)，免打扰中，跳过本轮")
            self._postpone_without_prompt()
        else:
            self.logger.warning(f"宽限期满({self.grace_seconds}秒)，强制锁屏")
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
                # 休息时间达标：重置推迟计数与免打扰
                self.is_resting = False
                self.lock_time = None
                self.postpone_count = 0
                self.dnd_mode = False
                self.logger.info("休息达标，重置推迟计数与免打扰")

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
