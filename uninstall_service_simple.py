"""卸载护眼软件自动启动（无需管理员权限）"""
import os
import sys
import subprocess


def get_startup_folder():
    """获取Windows启动文件夹路径"""
    result = subprocess.run(
        'echo %APPDATA%\\Microsoft\\Windows\\Start Menu\\Programs\\Startup',
        shell=True,
        capture_output=True,
        text=True
    )
    startup_path = result.stdout.strip()
    return startup_path


def uninstall_from_startup():
    """从启动文件夹删除"""
    print("正在卸载护眼软件自动启动...")
    print()

    startup_folder = get_startup_folder()
    target_path = os.path.join(startup_folder, "EyeProtector.bat")

    if os.path.exists(target_path):
        try:
            os.remove(target_path)
            print(f"已删除: {target_path}")
            print()
            print("[OK] 卸载成功！")
            print("护眼软件将不再自动启动。")
            return True
        except Exception as e:
            print(f"[FAIL] 删除失败: {e}")
            return False
    else:
        print("未找到自动启动项，可能已经卸载。")
        return True


if __name__ == "__main__":
    print("=" * 60)
    print("护眼软件 - 自动启动卸载程序")
    print("=" * 60)
    print()

    response = input("确定要卸载自动启动吗? (y/n): ")
    if response.lower() != 'y':
        print("卸载已取消")
        sys.exit(0)

    print()
    if uninstall_from_startup():
        print()
        print("卸载完成！")
    else:
        sys.exit(1)
