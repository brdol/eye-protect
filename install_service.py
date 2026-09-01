"""安装护眼软件为开机自动启动任务"""
import os
import sys
import subprocess


def install_task_scheduler():
    """使用Windows任务计划程序设置开机自动启动"""

    # 获取当前脚本的绝对路径
    current_dir = os.path.dirname(os.path.abspath(__file__))
    python_exe = sys.executable
    # 任务计划程序在后台运行：用 pythonw.exe（无控制台窗口），找不到则回退到 python.exe
    pythonw_exe = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    if os.path.exists(pythonw_exe):
        python_exe = pythonw_exe
    script_path = os.path.join(current_dir, "eye_protect.py")

    # 任务名称
    task_name = "EyeProtector"

    print(f"正在安装护眼软件自动启动任务...")
    print(f"Python路径: {python_exe}")
    print(f"脚本路径: {script_path}")
    print()

    # 删除已存在的任务（如果有）
    print("检查是否存在旧任务...")
    subprocess.run(
        f'schtasks /Delete /TN "{task_name}" /F',
        shell=True,
        capture_output=True
    )

    # 创建新任务
    # /SC ONLOGON: 用户登录时运行
    # /RL LIMITED: 以最低权限运行（LockWorkStation 无需管理员，避免过度授权）
    # /TR: 要运行的程序
    # /F: 强制创建，覆盖已存在的任务
    cmd = f'''schtasks /Create /TN "{task_name}" /SC ONLOGON /RL LIMITED /TR "\\"{python_exe}\\" \\"{script_path}\\"" /F'''

    print("创建自动启动任务...")
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)

    if result.returncode == 0:
        print("\n[OK] 安装成功！")
        print(f"\n任务名称: {task_name}")
        print("触发条件: 用户登录时自动启动")
        print("运行权限: 最低权限（普通用户；锁屏无需管理员）")
        print("\n下次登录时，护眼软件将自动启动。")
        print("\n管理任务:")
        print("  - 查看任务: 打开'任务计划程序' -> 任务计划程序库")
        print(f"  - 手动运行: schtasks /Run /TN \"{task_name}\"")
        print(f"  - 停止任务: 任务管理器中结束 python.exe 进程")
        print(f"  - 卸载任务: python uninstall_service.py")
    else:
        print("\n[FAIL] 安装失败！")
        print(f"错误信息: {result.stderr}")
        print("\n请尝试以管理员权限运行此脚本。")
        return False

    return True


def test_task():
    """测试任务是否创建成功"""
    task_name = "EyeProtector"
    result = subprocess.run(
        f'schtasks /Query /TN "{task_name}"',
        shell=True,
        capture_output=True,
        text=True
    )

    if result.returncode == 0:
        print("\n任务详情:")
        print(result.stdout)
    else:
        print("\n无法查询任务详情")


if __name__ == "__main__":
    print("=" * 60)
    print("护眼软件 - 自动启动安装程序")
    print("=" * 60)
    print()

    # 检查是否以管理员权限运行
    try:
        import ctypes
        is_admin = ctypes.windll.shell32.IsUserAnAdmin()
        if not is_admin:
            print("警告: 未以管理员权限运行")
            print("建议: 右键点击此脚本，选择'以管理员身份运行'")
            print()
            response = input("是否继续尝试安装? (y/n): ")
            if response.lower() != 'y':
                print("安装已取消")
                sys.exit(0)
    except:
        pass

    if install_task_scheduler():
        print()
        test_task()
        print()
        print("安装完成！")
    else:
        sys.exit(1)
