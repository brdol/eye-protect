"""重启护眼软件（后台、无窗口、无需管理员）。

如果 eye_protect 未运行则直接启动；如果已运行则先结束旧进程，再启动新进程。
适合修改 config.json 后立即让配置生效，也可以作为手动启动脚本使用。
"""
import os
import subprocess
import sys
import time

SCRIPT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "eye_protect.py")


def find_processes():
    """返回命令行包含本项目 eye_protect.py 的 Python 进程 PID。

    优先使用 PowerShell/CIM（Windows 11 已移除 wmic），再回退到 wmic。
    """
    marker = os.path.normcase(os.path.abspath(SCRIPT_PATH))
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
        pids = []
        for line in result.stdout.splitlines():
            value = line.strip()
            if value.isdigit():
                pids.append(int(value))
        if pids:
            return pids
    except Exception:
        pass

    try:
        result = subprocess.run(
            'wmic process where "commandline like \'%eye_protect.py%\'" get processid',
            shell=True, capture_output=True, text=True, check=False)
        return [int(line.strip()) for line in result.stdout.splitlines() if line.strip().isdigit()]
    except Exception:
        return []


def stop_processes(pids):
    """结束旧实例；只操作通过命令行精确匹配到的进程。"""
    for pid in pids:
        try:
            subprocess.run(
                ["taskkill", "/PID", str(pid), "/T", "/F"],
                capture_output=True, text=True, check=False)
            print(f"[OK] 已停止旧进程 PID={pid}")
        except Exception as e:
            print(f"[WARN] 停止 PID={pid} 失败: {e}")


def start_process():
    """使用当前 Python 环境的 pythonw.exe 后台启动。"""
    pythonw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    if not os.path.exists(pythonw):
        print(f"[FAIL] 未找到 pythonw.exe: {pythonw}")
        return False
    try:
        subprocess.Popen(
            [pythonw, SCRIPT_PATH],
            cwd=os.path.dirname(SCRIPT_PATH),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        print(f"[OK] 已后台启动 eye_protect（{pythonw}）")
        return True
    except Exception as e:
        print(f"[FAIL] 启动失败: {e}")
        return False


def restart():
    pids = find_processes()
    if pids:
        stop_processes(pids)
        time.sleep(0.5)
    else:
        print("未发现运行中的 eye_protect，直接启动。")
    return start_process()


if __name__ == "__main__":
    sys.exit(0 if restart() else 1)
