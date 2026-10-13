"""进程工具：定位/启动/停止本项目的 eye_protect 实例。

统一放在这里，避免 install_service.py 与 restart_service.py 各写一份
（曾因一处用 wmic、一处用 CIM 导致行为不一致）。
Windows 11 可能不再自带 wmic，因此统一使用 PowerShell/CIM。
"""
import os
import subprocess
import sys

SCRIPT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "eye_protect.py")


def find_eye_protect_pids():
    """返回命令行包含本项目 eye_protect.py 的 Python 进程 PID 列表。"""
    try:
        ps = (
            "Get-CimInstance Win32_Process | "
            "Where-Object { $_.Name -in @('python.exe','pythonw.exe') "
            "-and $_.CommandLine -like '*eye_protect.py*' } | "
            "Select-Object -ExpandProperty ProcessId"
        )
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", ps],
            capture_output=True, text=True, check=False)
        pids = [int(line.strip()) for line in result.stdout.splitlines() if line.strip().isdigit()]
        if pids:
            return pids
    except Exception:
        pass

    # 回退：老系统上的 wmic
    try:
        result = subprocess.run(
            'wmic process where "commandline like \'%eye_protect.py%\'" get processid',
            shell=True, capture_output=True, text=True, check=False)
        return [int(line.strip()) for line in result.stdout.splitlines() if line.strip().isdigit()]
    except Exception:
        return []


def is_running():
    return len(find_eye_protect_pids()) > 0


def start_background():
    """用 pythonw.exe 后台启动 eye_protect。返回 True 表示已发出启动命令。"""
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
    """结束给定 PID 的进程（只应由调用方传入已精确匹配 eye_protect.py 的 PID）。"""
    for pid in pids:
        try:
            subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"],
                           capture_output=True, text=True, check=False)
            print(f"[OK] 已停止旧进程 PID={pid}")
        except Exception as e:
            print(f"[WARN] 停止 PID={pid} 失败: {e}")
