"""重启护眼软件（后台、无窗口、无需管理员）。

如果 eye_protect 未运行则直接启动；如果已运行则先结束旧进程，再启动新进程。
适合修改 config.json 后立即让配置生效，也可以作为手动启动脚本使用。
"""
import sys
import time

import procutil


def restart():
    pids = procutil.find_eye_protect_pids()
    if pids:
        procutil.stop_pids(pids)
        time.sleep(0.5)
    else:
        print("未发现运行中的 eye_protect，直接启动。")
    if procutil.start_background():
        print("[OK] 已重启 eye_protect（后台运行，无窗口）。")
        return True
    return False


if __name__ == "__main__":
    sys.exit(0 if restart() else 1)
