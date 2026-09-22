"""测试服务安装和管理功能"""
import os
import subprocess
import time
import sys
from _bootstrap import *

STARTUP_FOLDER = os.path.expandvars(
    r"%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"
)
LNK_PATH = os.path.join(STARTUP_FOLDER, "EyeProtect.lnk")


def test_installation():
    """测试1: 验证安装（快捷方式 .lnk）"""
    print("=" * 60)
    print("测试1: 验证安装")
    print("=" * 60)

    if os.path.exists(LNK_PATH):
        print(f"[OK] 启动快捷方式存在: {LNK_PATH}")
        try:
            import win32com.client
            shell = win32com.client.Dispatch("WScript.Shell")
            sc = shell.CreateShortcut(LNK_PATH)
            if "eye_protect.py" in (sc.Arguments or "") and "pythonw" in (sc.TargetPath or "").lower():
                print("[OK] 快捷方式目标正确（pythonw + eye_protect.py）")
            else:
                print(f"[FAIL] 快捷方式目标不正确: {sc.TargetPath} {sc.Arguments}")
                return False
        except Exception as e:
            print(f"[WARN] 读取快捷方式失败(忽略): {e}")
    else:
        print(f"[FAIL] 启动快捷方式不存在: {LNK_PATH}")
        print("       请先运行: python install_service.py")
        return False

    print()
    return True


def test_manual_start():
    """测试2: 手动启动程序（通过 .lnk 后台拉起）"""
    print("=" * 60)
    print("测试2: 手动启动程序")
    print("=" * 60)

    if not os.path.exists(LNK_PATH):
        print(f"[FAIL] 快捷方式不存在: {LNK_PATH}")
        return False

    print(f"快捷方式: {LNK_PATH}")
    print("正在后台启动程序...")
    subprocess.Popen(
        [LNK_PATH],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    print("等待3秒让程序启动...")
    time.sleep(3)

    # 检查进程（pythonw.exe，命令行含 eye_protect.py）
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command",
         "Get-CimInstance Win32_Process | Where-Object { $_.Name -in @('python.exe','pythonw.exe') -and $_.CommandLine -like '*eye_protect.py*' } | Select-Object -ExpandProperty Name"],
        capture_output=True, text=True
    )

    if "python" in result.stdout.lower():
        print("[OK] eye_protect 进程正在运行")

        log_dir = os.path.join(PROJECT_ROOT, "logs")
        if os.path.exists(log_dir):
            log_files = sorted(os.listdir(log_dir))
            if log_files:
                latest_log = os.path.join(log_dir, log_files[-1])
                print(f"[OK] 日志文件存在: {latest_log}")
                with open(latest_log, 'r', encoding='utf-8') as f:
                    lines = f.readlines()
                    if lines:
                        print(f"[OK] 最新日志: {lines[-1].strip()}")
            else:
                print("[WARN] 日志目录为空")
        return True
    else:
        print("[FAIL] 未找到 eye_protect 进程")
        return False


def test_process_check():
    """测试3: 检查进程详情"""
    print()
    print("=" * 60)
    print("测试3: 检查进程详情")
    print("=" * 60)

    result = subprocess.run(
        'wmic process where "commandline like \'%eye_protect.py%\'" get processid,commandline',
        shell=True, capture_output=True, text=True
    )

    if "eye_protect.py" in result.stdout:
        print("[OK] 找到 eye_protect.py 进程")
        print("进程信息:")
        for line in result.stdout.split('\n'):
            if 'eye_protect.py' in line:
                print(f"  {line.strip()}")
        return True
    else:
        print("[WARN] 未找到 eye_protect.py 进程（可能已经退出或未启动）")
        return False


def test_uninstallation(auto_confirm=False):
    """测试4: 卸载功能"""
    print()
    print("=" * 60)
    print("测试4: 卸载功能")
    print("=" * 60)

    if not auto_confirm:
        print("跳过卸载测试（使用 --uninstall 参数来测试卸载）")
        return True

    print("运行卸载脚本...")
    result = subprocess.run(
        [sys.executable, os.path.join(PROJECT_ROOT, "uninstall_service.py")],
        capture_output=True, text=True
    )
    print(result.stdout)

    if not os.path.exists(LNK_PATH):
        print("[OK] 启动快捷方式已删除")
        return True
    else:
        print("[FAIL] 启动快捷方式仍然存在")
        return False


if __name__ == "__main__":
    print("护眼软件 - 服务管理功能测试")
    print()

    test_uninstall = "--uninstall" in sys.argv

    results = []
    results.append(("安装验证", test_installation()))
    results.append(("手动启动", test_manual_start()))
    results.append(("进程检查", test_process_check()))
    results.append(("卸载功能", test_uninstallation(test_uninstall)))

    print()
    print("=" * 60)
    print("测试结果汇总")
    print("=" * 60)

    for name, result in results:
        status = "[PASS]" if result else "[FAIL]"
        print(f"{status} {name}")

    passed = sum(1 for _, r in results if r)
    total = len(results)
    print()
    print(f"通过: {passed}/{total}")

    if test_uninstall:
        print()
        print("注意: 已执行卸载测试，自动启动已被移除")
