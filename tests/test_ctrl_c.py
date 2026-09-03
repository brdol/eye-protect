"""测试 Ctrl+C 是否能正常工作"""
import time
import win32gui
from _bootstrap import *

print("程序启动，按 Ctrl+C 退出...")
print("等待5秒后自动退出（或按 Ctrl+C 提前退出）")

running = True
start_time = time.time()

try:
    while running:
        # 处理消息
        win32gui.PumpWaitingMessages()

        # 检查是否超时
        if time.time() - start_time > 5:
            print("5秒已到，自动退出")
            running = False

        time.sleep(0.1)
except KeyboardInterrupt:
    print("\n收到 Ctrl+C，正常退出")

print("程序已退出")
