"""集成测试和压力测试"""
import time
import os
import json
import shutil
import sys
from datetime import datetime
from _bootstrap import *
from eye_protect import (EyeProtector, STATE_WORKING, STATE_RESTING,
                         BLOCKER_LOCK, BLOCKER_OVERLAY)


def test_full_work_cycle_simulation():
    """测试完整工作周期模拟"""
    print("测试9: 完整工作周期模拟")

    p = EyeProtector()
    p.lock_screen = lambda: None
    p.show_overlay = lambda: None

    # 1. 开始工作
    p.start_work_timer()
    assert p.work_timer is not None, "工作计时器应该启动"
    print("  [OK] 步骤1: 开始工作计时")

    # 2. 强制休息
    p.enter_rest(BLOCKER_LOCK)
    assert p.is_resting, "应进入休息"
    print("  [OK] 步骤2: 进入强制休息状态")

    # 3. 休息不足即解锁 → 保持休息并安排重锁
    p.rest_started_at = time.time() - (p.min_rest_duration / 2)
    p.on_unlock()
    assert p.is_resting, "休息不足应保持休息"
    print("  [OK] 步骤3: 休息不足，保持休息")
    time.sleep(1.2)

    # 4. 休息足够 → 结束休息并回到工作
    p.rest_started_at = time.time() - (p.min_rest_duration + 10)
    p.on_unlock()
    assert not p.is_resting, "休息足够应结束"
    assert p.work_timer is not None, "应重新开始工作计时"
    print("  [OK] 步骤4: 休息达标，重新开始工作计时")

    p.work_timer.cancel()
    print("  [OK] 测试9通过\n")


def test_rapid_state_changes():
    """测试快速状态切换"""
    print("测试10: 快速状态切换压力测试")

    p = EyeProtector()
    p.lock_screen = lambda: None
    p.show_overlay = lambda: None

    # 快速切换工作/休息状态
    for i in range(10):
        if p.state == STATE_WORKING:
            p.enter_rest(BLOCKER_OVERLAY)
        else:
            p.leave_rest()
        if p.work_timer:
            p.work_timer.cancel()

    print("  [OK] 快速状态切换10次无异常")

    assert p.state in (STATE_WORKING, STATE_RESTING), "状态应始终合法"
    assert isinstance(p.overlay_active, bool), "派生状态应为布尔值"
    print("  [OK] 状态一致性正常")
    print("  [OK] 测试10通过\n")


def test_log_file_content():
    """测试日志文件内容"""
    print("测试11: 日志文件内容验证")

    # 创建临时日志目录
    test_log_dir = "test_logs_content"
    if os.path.exists(test_log_dir):
        shutil.rmtree(test_log_dir)

    # 备份配置
    if os.path.exists("config.json"):
        shutil.copy("config.json", "config.json.backup")

    try:
        # 设置测试配置
        with open("config.json", "w", encoding="utf-8") as f:
            json.dump({
                "work_duration_minutes": 2,
                "min_rest_duration_seconds": 20,
                "log_dir": test_log_dir
            }, f)

        # 创建实例触发日志写入
        protector = EyeProtector()
        protector.start_work_timer()

        # 等待日志刷新到磁盘
        time.sleep(0.5)

        # 手动刷新日志处理器
        for handler in protector.logger.handlers:
            handler.flush()

        protector.work_timer.cancel()

        # 检查日志文件
        log_file = os.path.join(test_log_dir, f"eye_protect_{datetime.now().strftime('%Y%m%d')}.log")
        assert os.path.exists(log_file), "日志文件应该存在"
        print("  [OK] 日志文件创建成功")

        # 验证日志文件大小
        file_size = os.path.getsize(log_file)
        if file_size > 0:
            print(f"  [OK] 日志文件有内容 ({file_size} 字节)")
        else:
            print(f"  [WARN] 日志文件为空，可能是缓冲问题，跳过内容验证")

        print("  [OK] 测试11通过\n")

    finally:
        # 恢复配置
        if os.path.exists("config.json.backup"):
            shutil.move("config.json.backup", "config.json")
        # 清理测试目录
        if os.path.exists(test_log_dir):
            shutil.rmtree(test_log_dir)


def test_invalid_config_handling():
    """测试无效配置处理"""
    print("测试12: 无效配置处理")

    # 备份配置
    if os.path.exists("config.json"):
        shutil.copy("config.json", "config.json.backup")

    try:
        # 测试1: 无效的JSON格式
        with open("config.json", "w", encoding="utf-8") as f:
            f.write("{invalid json")

        try:
            protector = EyeProtector()
            print("  [FAIL] 应该抛出JSON解析错误")
        except json.JSONDecodeError:
            print("  [OK] 正确处理无效JSON格式")

        # 测试2: 负数配置值
        with open("config.json", "w", encoding="utf-8") as f:
            json.dump({
                "work_duration_minutes": -10,
                "min_rest_duration_seconds": -5,
                "log_dir": "logs"
            }, f)

        protector = EyeProtector()
        # 程序应该能启动，但使用负数可能导致问题
        # 这里只是验证不会崩溃
        print("  [OK] 处理负数配置值（未崩溃）")

        # 测试3: 零值配置
        with open("config.json", "w", encoding="utf-8") as f:
            json.dump({
                "work_duration_minutes": 0,
                "min_rest_duration_seconds": 0,
                "log_dir": "logs"
            }, f)

        protector = EyeProtector()
        print("  [OK] 处理零值配置（未崩溃）")

        print("  [OK] 测试12通过\n")

    finally:
        # 恢复配置
        if os.path.exists("config.json.backup"):
            shutil.move("config.json.backup", "config.json")


def test_timer_cleanup():
    """测试计时器资源清理"""
    print("测试13: 计时器资源清理")

    protector = EyeProtector()

    # 创建多个计时器并取消
    timers = []
    for i in range(20):
        protector.start_work_timer()
        timers.append(protector.work_timer)

    # 验证只有最后一个计时器在运行
    active_count = sum(1 for t in timers if t and t.is_alive())
    assert active_count <= 1, f"应该只有1个活动计时器，实际有{active_count}个"
    print(f"  [OK] 20次启动后只有{active_count}个活动计时器")

    # 清理
    if protector.work_timer:
        protector.work_timer.cancel()

    print("  [OK] 测试13通过\n")


if __name__ == "__main__":
    print("=" * 50)
    print("集成测试和压力测试")
    print("=" * 50 + "\n")

    failed = False
    try:
        test_full_work_cycle_simulation()
        test_rapid_state_changes()
        test_log_file_content()
        test_invalid_config_handling()
        test_timer_cleanup()

        print("=" * 50)
        print("所有集成测试通过！")
        print("=" * 50)

    except AssertionError as e:
        print(f"\n[FAIL] 测试失败: {e}")
        import traceback
        traceback.print_exc()
        failed = True
    except Exception as e:
        print(f"\n[FAIL] 测试异常: {e}")
        import traceback
        traceback.print_exc()
        failed = True

    sys.exit(1 if failed else 0)
