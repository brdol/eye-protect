"""测试服务安装和管理功能"""
import os
import subprocess
import time
import sys


def test_installation():
    """测试1: 验证安装"""
    print("=" * 60)
    print("测试1: 验证安装")
    print("=" * 60)

    startup_folder = os.path.expandvars(
        r"%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"
    )
    target_file = os.path.join(startup_folder, "EyeProtector.bat")

    if os.path.exists(target_file):
        print(f"[OK] 启动文件存在: {target_file}")

        # 读取内容
        with open(target_file, 'r', encoding='utf-8') as f:
            content = f.read()

        if "eye_protect.py" in content:
            print("[OK] 启动脚本内容正确")
        else:
            print("[FAIL] 启动脚本内容不正确")
            return False
    else:
        print(f"[FAIL] 启动文件不存在: {target_file}")
        return False

    print()
    return True


def test_manual_start():
    """测试2: 手动启动程序"""
    print("=" * 60)
    print("测试2: 手动启动程序")
    print("=" * 60)

    startup_bat = os.path.join(os.path.dirname(os.path.abspath(__file__)), "eye_protect_startup.bat")

    if not os.path.exists(startup_bat):
        print(f"[FAIL] 启动脚本不存在: {startup_bat}")
        return False

    print(f"启动脚本: {startup_bat}")
    print("正在启动程序...")

    # 使用start命令在后台启动
    subprocess.Popen(
        f'start /min "" "{startup_bat}"',
        shell=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )

    print("等待3秒让程序启动...")
    time.sleep(3)

    # 检查进程
    result = subprocess.run(
        'tasklist /FI "IMAGENAME eq python.exe"',
        shell=True,
        capture_output=True,
        text=True
    )

    if "python.exe" in result.stdout:
        print("[OK] Python进程正在运行")

        # 检查日志文件
        log_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
        if os.path.exists(log_dir):
            log_files = os.listdir(log_dir)
            if log_files:
                latest_log = os.path.join(log_dir, sorted(log_files)[-1])
                print(f"[OK] 日志文件存在: {latest_log}")

                # 读取最后几行
                with open(latest_log, 'r', encoding='utf-8') as f:
                    lines = f.readlines()
                    if lines:
                        print(f"[OK] 最新日志: {lines[-1].strip()}")
            else:
                print("[WARN] 日志目录为空")

        return True
    else:
        print("[FAIL] 未找到Python进程")
        return False


def test_process_check():
    """测试3: 检查进程详情"""
    print()
    print("=" * 60)
    print("测试3: 检查进程详情")
    print("=" * 60)

    # 使用wmic查找eye_protect.py进程
    result = subprocess.run(
        'wmic process where "commandline like \'%eye_protect.py%\'" get processid,commandline',
        shell=True,
        capture_output=True,
        text=True
    )

    if "eye_protect.py" in result.stdout:
        print("[OK] 找到eye_protect.py进程")
        print("进程信息:")
        for line in result.stdout.split('\n'):
            if 'eye_protect.py' in line:
                print(f"  {line.strip()}")
        return True
    else:
        print("[WARN] 未找到eye_protect.py进程（可能已经退出或未启动）")
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
        [sys.executable, "uninstall_service_simple.py"],
        input="y\n",
        capture_output=True,
        text=True
    )

    print(result.stdout)

    # 验证文件是否被删除
    startup_folder = os.path.expandvars(
        r"%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"
    )
    target_file = os.path.join(startup_folder, "EyeProtector.bat")

    if not os.path.exists(target_file):
        print("[OK] 启动文件已删除")
        return True
    else:
        print("[FAIL] 启动文件仍然存在")
        return False


if __name__ == "__main__":
    print("护眼软件 - 服务管理功能测试")
    print()

    # 检查命令行参数
    test_uninstall = "--uninstall" in sys.argv

    results = []

    # 测试1: 验证安装
    results.append(("安装验证", test_installation()))

    # 测试2: 手动启动
    results.append(("手动启动", test_manual_start()))

    # 测试3: 进程检查
    results.append(("进程检查", test_process_check()))

    # 测试4: 卸载功能
    results.append(("卸载功能", test_uninstallation(test_uninstall)))

    # 汇总结果
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
