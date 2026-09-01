import subprocess
import time
import signal

print("启动护眼程序...")
proc = subprocess.Popen(
    ["python", "eye_protect.py"],
    stdout=subprocess.PIPE,
    stderr=subprocess.STDOUT,
    text=True,
    bufsize=1
)

# 等待程序启动
time.sleep(2)

print("发送 Ctrl+C 信号...")
proc.send_signal(signal.SIGINT)

# 等待程序退出
try:
    output, _ = proc.communicate(timeout=3)
    print(f"程序退出码: {proc.returncode}")
    print(f"输出:\n{output}")

    if proc.returncode == 0 or proc.returncode == -2:  # -2 是 SIGINT
        print("\n✓ 测试通过：程序能够正常响应 Ctrl+C")
    else:
        print(f"\n✗ 测试失败：退出码异常 {proc.returncode}")
except subprocess.TimeoutExpired:
    print("\n✗ 测试失败：程序未能在3秒内退出")
    proc.kill()
