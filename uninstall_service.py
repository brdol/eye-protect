"""卸载护眼软件自动启动任务"""
import subprocess
import sys


def uninstall_task_scheduler():
    """从Windows任务计划程序中删除自动启动任务"""

    task_name = "EyeProtector"

    print(f"正在卸载护眼软件自动启动任务...")
    print()

    # 删除任务
    cmd = f'schtasks /Delete /TN "{task_name}" /F'
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)

    if result.returncode == 0:
        print("[OK] 卸载成功！")
        print(f"\n任务 '{task_name}' 已从任务计划程序中删除。")
        print("护眼软件将不再自动启动。")
    else:
        if "找不到" in result.stderr or "cannot find" in result.stderr.lower():
            print("任务不存在，无需卸载。")
        else:
            print("[FAIL] 卸载失败！")
            print(f"错误信息: {result.stderr}")
            return False

    return True


if __name__ == "__main__":
    print("=" * 60)
    print("护眼软件 - 自动启动卸载程序")
    print("=" * 60)
    print()

    response = input("确定要卸载自动启动任务吗? (y/n): ")
    if response.lower() != 'y':
        print("卸载已取消")
        sys.exit(0)

    print()
    if uninstall_task_scheduler():
        print()
        print("卸载完成！")
    else:
        sys.exit(1)
