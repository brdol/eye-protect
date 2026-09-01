"""卸载护眼软件开机自启动（删除启动文件夹快捷方式；并清理旧方式残留）"""
import os
import subprocess
import sys

TASK_NAME = "EyeProtector"


def get_startup_folder():
    return os.path.join(os.environ["APPDATA"],
                        "Microsoft", "Windows", "Start Menu", "Programs", "Startup")


def uninstall():
    startup_folder = get_startup_folder()
    print("正在卸载护眼软件开机自启动...")
    print()
    removed = False

    # 1) 删除快捷方式（当前方式）
    lnk = os.path.join(startup_folder, "EyeProtect.lnk")
    if os.path.exists(lnk):
        try:
            os.remove(lnk)
            print(f"[OK] 已删除快捷方式: {lnk}")
            removed = True
        except Exception as e:
            print(f"[FAIL] 删除快捷方式失败: {e}")

    # 2) 清理旧方式残留
    old_bat = os.path.join(startup_folder, "EyeProtector.bat")
    if os.path.exists(old_bat):
        try:
            os.remove(old_bat)
            print(f"[OK] 已清理旧启动脚本: {old_bat}")
            removed = True
        except Exception as e:
            print(f"[FAIL] 删除旧脚本失败: {e}")

    q = subprocess.run(f'schtasks /Query /TN "{TASK_NAME}"',
                       shell=True, capture_output=True, text=True)
    if q.returncode == 0:
        subprocess.run(f'schtasks /Delete /TN "{TASK_NAME}" /F',
                       shell=True, capture_output=True, text=True)
        print(f"[OK] 已清理旧任务计划程序任务: {TASK_NAME}")
        removed = True

    if not removed:
        print("未发现自启动项（可能已卸载）。")
    else:
        print()
        print("护眼软件将不再开机自启动。")
    return True


if __name__ == "__main__":
    print("=" * 60)
    print("护眼软件 - 开机自启动卸载程序")
    print("=" * 60)
    print()
    uninstall()
