"""安装护眼软件为开机自启动（启动文件夹快捷方式，无需管理员，后台无窗口）

原理：在用户启动文件夹创建指向 pythonw.exe 的快捷方式（.lnk），登录时由
资源管理器拉起，pythonw 无控制台窗口 → 纯后台。全程零管理员。
"""
import os
import subprocess
import sys

try:
    import win32com.client  # pywin32：创建快捷方式
except ImportError:
    print("[FAIL] 缺少 pywin32，请先运行: python -m pip install -r requirements.txt")
    sys.exit(1)

import procutil

TASK_NAME = "EyeProtector"
SCRIPT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "eye_protect.py")


def get_startup_folder():
    return os.path.join(os.environ["APPDATA"],
                        "Microsoft", "Windows", "Start Menu", "Programs", "Startup")


def _cleanup_old_methods(startup_folder):
    """迁移清理：删除旧方式残留（旧 EyeProtector.bat、旧任务计划任务）。失败忽略，不影响安装。"""
    old_bat = os.path.join(startup_folder, "EyeProtector.bat")
    if os.path.exists(old_bat):
        try:
            os.remove(old_bat)
            print(f"已清理旧启动脚本: {old_bat}")
        except Exception as e:
            print(f"警告: 清理旧脚本失败(可手动删): {old_bat}  ({e})")
    # 旧的任务计划程序方式（删除可能需要管理员；失败忽略）
    q = subprocess.run(f'schtasks /Query /TN "{TASK_NAME}"',
                       shell=True, capture_output=True, text=True)
    if q.returncode == 0:
        subprocess.run(f'schtasks /Delete /TN "{TASK_NAME}" /F',
                       shell=True, capture_output=True, text=True)
        print(f"已清理旧任务计划程序任务: {TASK_NAME}")


def install_shortcut():
    current_dir = os.path.dirname(os.path.abspath(__file__))
    pythonw_exe = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    if not os.path.exists(pythonw_exe):
        print(f"[FAIL] 未找到 pythonw.exe: {pythonw_exe}")
        print("       pythonw.exe 是无控制台窗口的 Python，miniconda/官方安装包均自带。")
        return False
    script_path = os.path.join(current_dir, "eye_protect.py")
    startup_folder = get_startup_folder()
    shortcut_path = os.path.join(startup_folder, "EyeProtect.lnk")

    print("正在安装护眼软件开机自启动（启动文件夹快捷方式，无需管理员，后台运行）...")
    print(f"解释器: {pythonw_exe}")
    print(f"脚本:   {script_path}")
    print(f"启动文件夹: {startup_folder}")
    print()

    if not os.path.exists(startup_folder):
        print(f"[FAIL] 启动文件夹不存在: {startup_folder}")
        return False

    _cleanup_old_methods(startup_folder)

    shell = win32com.client.Dispatch("WScript.Shell")
    shortcut = shell.CreateShortcut(shortcut_path)
    shortcut.TargetPath = pythonw_exe
    shortcut.Arguments = f'"{script_path}"'
    shortcut.WorkingDirectory = current_dir
    shortcut.WindowStyle = 7  # 最小化（pythonw 无窗口，此项无影响）
    shortcut.Description = "护眼软件 eye-protect 自启动"
    shortcut.Save()

    print(f"[OK] 已创建快捷方式: {shortcut_path}")
    print("下次登录时，护眼软件将以后台方式（无终端窗口）自动启动。")
    print()
    print("管理:")
    print(f"  - 快捷方式位置: {shortcut_path}")
    print("  - 任务管理器 → 启动应用: 可启用/禁用 EyeProtect")
    print("  - 停止运行: 任务管理器结束 pythonw.exe（命令行含 eye_protect.py）")
    print("  - 卸载: python uninstall_service.py")

    # 安装即生效：若未在跑，后台启动一次（首次会生成 config.json）
    if procutil.is_running():
        print()
        print("检测到 eye_protect 已在运行，无需重复启动。")
    else:
        print()
        if procutil.start_background():
            print("[OK] 已后台启动 eye_protect。")
    return True


if __name__ == "__main__":
    print("=" * 60)
    print("护眼软件 - 开机自启动安装程序（无需管理员，后台运行）")
    print("=" * 60)
    print()
    if not install_shortcut():
        sys.exit(1)
