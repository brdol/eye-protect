"""进程工具：定位/启动/停止本项目的实例。

同时支持两种运行形态：
- 源码运行：进程是 python/pythonw + eye_protect.py
- 打包运行（PyInstaller frozen）：进程是 EyeProtect.exe

Windows 11 可能不再自带 wmic，因此优先使用 PowerShell/CIM。
"""
import os
import subprocess
import sys

FROZEN = bool(getattr(sys, "frozen", False))
APP_EXE = os.path.basename(sys.executable) if FROZEN else ""
SCRIPT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "eye_protect.py")

# 用绝对路径调用 PowerShell：Explorer 双击启动时继承的 PATH 可能不含 WindowsPowerShell 目录，
# 裸 `powershell.exe` 会找不到，进而误判“未运行”并拉起重复实例。
_POWERSHELL = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"),
                           "System32", "WindowsPowerShell", "v1.0", "powershell.exe")
POWERSHELL = _POWERSHELL if os.path.exists(_POWERSHELL) else "powershell.exe"


def _process_filter():
    """PowerShell Where-Object 的匹配条件。"""
    if FROZEN:
        name = APP_EXE.replace("'", "''")
        return f"$_.Name -eq '{name}'"
    return ("$_.Name -in @('python.exe','pythonw.exe') "
            "-and $_.CommandLine -like '*eye_protect.py*'")


def find_eye_protect_pids():
    """返回本项目所有实例的 PID 列表。"""
    try:
        ps = ("Get-CimInstance Win32_Process | "
              "Where-Object { " + _process_filter() + " } | "
              "Select-Object -ExpandProperty ProcessId")
        result = subprocess.run(
            [POWERSHELL, "-NoProfile", "-NonInteractive", "-Command", ps],
            capture_output=True, text=True, check=False)
        if result.returncode == 0:
            # 排除当前进程：以 EyeProtect.exe --stop/--restart 调用时，自己也会命中匹配规则
            return [int(line.strip()) for line in result.stdout.splitlines()
                    if line.strip().isdigit() and int(line.strip()) != os.getpid()]
    except Exception:
        pass

    if FROZEN:
        return []

    # 回退：老系统上的 wmic（仅源码形态需要）
    try:
        result = subprocess.run(
            'wmic process where "commandline like \'%eye_protect.py%\'" get processid',
            shell=True, capture_output=True, text=True, check=False)
        return [int(line.strip()) for line in result.stdout.splitlines()
                if line.strip().isdigit() and int(line.strip()) != os.getpid()]
    except Exception:
        return []


def is_running():
    return len(find_eye_protect_pids()) > 0


def start_background():
    """后台启动本项目实例。返回 True 表示已发出启动命令。"""
    if FROZEN:
        exe = sys.executable
        try:
            subprocess.Popen(
                [exe],
                cwd=os.path.dirname(exe),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            return True
        except Exception as e:
            print(f"[FAIL] 启动失败: {e}")
            return False

    pythonw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    if not os.path.exists(pythonw):
        print(f"[FAIL] 未找到 pythonw.exe: {pythonw}")
        print("       pythonw.exe 是无控制台窗口的 Python，miniconda/官方安装包均自带。")
        return False
    try:
        subprocess.Popen(
            [pythonw, SCRIPT_PATH],
            cwd=os.path.dirname(SCRIPT_PATH),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return True
    except Exception as e:
        print(f"[FAIL] 启动失败: {e}")
        return False


def stop_pids(pids):
    """结束给定 PID 的进程（只应由调用方传入已精确匹配的 PID）。"""
    for pid in pids:
        try:
            subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"],
                           capture_output=True, text=True, check=False)
            print(f"[OK] 已停止旧进程 PID={pid}")
        except Exception as e:
            print(f"[WARN] 停止 PID={pid} 失败: {e}")
