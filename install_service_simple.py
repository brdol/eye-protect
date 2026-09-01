"""安装护眼软件为开机自动启动（无需管理员权限）"""
import os
import sys
import shutil
import subprocess


def get_startup_folder():
    """获取Windows启动文件夹路径"""
    # 使用shell:startup获取启动文件夹
    result = subprocess.run(
        'echo %APPDATA%\\Microsoft\\Windows\\Start Menu\\Programs\\Startup',
        shell=True,
        capture_output=True,
        text=True
    )
    startup_path = result.stdout.strip()
    return startup_path


def create_startup_script():
    """创建启动脚本"""
    current_dir = os.path.dirname(os.path.abspath(__file__))
    python_exe = sys.executable
    script_path = os.path.join(current_dir, "eye_protect.py")

    # 创建启动批处理文件
    startup_bat = os.path.join(current_dir, "eye_protect_startup.bat")

    bat_content = f'''@echo off
cd /d "{current_dir}"
start "" "{python_exe}" "{script_path}"
'''

    with open(startup_bat, 'w', encoding='utf-8') as f:
        f.write(bat_content)

    return startup_bat


def install_to_startup():
    """安装到启动文件夹（无需管理员权限）"""
    print("正在安装护眼软件自动启动...")
    print()

    # 获取启动文件夹
    startup_folder = get_startup_folder()
    print(f"启动文件夹: {startup_folder}")

    if not os.path.exists(startup_folder):
        print(f"[FAIL] 启动文件夹不存在: {startup_folder}")
        return False

    # 创建启动脚本
    startup_bat = create_startup_script()
    print(f"启动脚本: {startup_bat}")

    # 复制到启动文件夹
    target_path = os.path.join(startup_folder, "EyeProtector.bat")

    try:
        shutil.copy2(startup_bat, target_path)
        print(f"已复制到: {target_path}")
        print()
        print("[OK] 安装成功！")
        print()
        print("下次登录时，护眼软件将自动启动。")
        print()
        print("管理:")
        print(f"  - 启动脚本位置: {target_path}")
        print(f"  - 手动启动: 双击 {startup_bat}")
        print(f"  - 停止程序: 任务管理器中结束 python.exe 进程")
        print(f"  - 卸载: python uninstall_service_simple.py")
        return True
    except Exception as e:
        print(f"[FAIL] 复制失败: {e}")
        return False


if __name__ == "__main__":
    print("=" * 60)
    print("护眼软件 - 自动启动安装程序（无需管理员权限）")
    print("=" * 60)
    print()

    if install_to_startup():
        print()
        print("安装完成！")
    else:
        sys.exit(1)
