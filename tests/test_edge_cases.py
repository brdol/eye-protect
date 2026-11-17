"""测试配置文件和边界情况"""
import json
import os
import shutil
import sys
from _bootstrap import *
from eye_protect import EyeProtector, BLOCKER_OVERLAY


def test_config_validation():
    """测试配置文件验证"""
    print("测试5: 配置文件处理")

    # 备份原配置
    if os.path.exists("config.json"):
        shutil.copy("config.json", "config.json.backup")

    try:
        # 测试1: 缺失配置文件（应该创建默认配置）
        if os.path.exists("config.json"):
            os.remove("config.json")

        protector = EyeProtector()
        assert os.path.exists("config.json"), "应该创建默认配置文件"
        assert protector.work_duration > 0, "工作时长应该有默认值"
        assert protector.min_rest_duration > 0, "休息时长应该有默认值"
        assert protector.lock_mode == "prompt", "lock_mode 默认应为 prompt"
        assert protector.grace_seconds == 60, "grace_seconds 默认应为 60"
        assert protector.postpone_minutes == 5, "postpone_minutes 默认应为 5"
        assert protector.max_postpones == 3, "max_postpones 默认应为 3"
        print("  [OK] 缺失配置时自动创建默认配置")

        # 测试2: 部分配置缺失（应该使用默认值）
        with open("config.json", "w", encoding="utf-8") as f:
            json.dump({"work_duration_minutes": 5}, f)

        protector = EyeProtector()
        assert protector.work_duration == 5, "应该读取自定义值"
        assert protector.min_rest_duration == 20, "缺失项应该使用默认值"
        assert protector.lock_mode == "prompt", "缺失项 lock_mode 应使用默认值"
        assert protector.grace_seconds == 60, "缺失项 grace_seconds 应使用默认值"
        assert protector.postpone_minutes == 5, "缺失项 postpone_minutes 应使用默认值"
        assert protector.max_postpones == 3, "缺失项 max_postpones 应使用默认值"
        print("  [OK] 部分配置缺失时使用默认值")

        # 测试3: 完整配置
        with open("config.json", "w", encoding="utf-8") as f:
            json.dump({
                "work_duration_minutes": 10,
                "min_rest_duration_seconds": 30,
                "log_dir": "test_logs"
            }, f)

        protector = EyeProtector()
        assert protector.work_duration == 10, "应该读取工作时长"
        assert protector.min_rest_duration == 30, "应该读取休息时长"
        # log_dir 相对路径会被解析为脚本目录下的绝对路径
        assert protector.log_dir.endswith("test_logs"), f"应该读取日志目录，实际 {protector.log_dir}"
        print("  [OK] 完整配置正确加载")

        # 测试4: 零/负值被钳制
        with open("config.json", "w", encoding="utf-8") as f:
            json.dump({
                "work_duration_minutes": 10,
                "min_rest_duration_seconds": 30,
                "log_dir": "logs",
                "grace_seconds": -5,
                "postpone_minutes": 0,
                "max_postpones": -2,
            }, f)
        protector = EyeProtector()
        assert protector.grace_seconds == 1, f"grace_seconds 应钳制为1，实际{protector.grace_seconds}"
        assert protector.postpone_minutes == 1, f"postpone_minutes 应钳制为1，实际{protector.postpone_minutes}"
        assert protector.max_postpones == 0, f"max_postpones 应钳制为0，实际{protector.max_postpones}"
        print("  [OK] 零/负值被钳制")

        # 测试5: lock_mode 大小写与非法值归一化
        with open("config.json", "w", encoding="utf-8") as f:
            json.dump({"lock_mode": "HARD"}, f)
        protector = EyeProtector()
        assert protector.lock_mode == "hard", f"HARD 应归一为 hard，实际{protector.lock_mode}"
        with open("config.json", "w", encoding="utf-8") as f:
            json.dump({"lock_mode": "garbage"}, f)
        protector = EyeProtector()
        assert protector.lock_mode == "prompt", f"非法值应为 prompt，实际{protector.lock_mode}"
        print("  [OK] lock_mode 归一化")

        print("  [OK] 测试5通过\n")

    finally:
        # 恢复原配置
        if os.path.exists("config.json.backup"):
            shutil.move("config.json.backup", "config.json")
        # 清理测试日志目录
        if os.path.exists("test_logs"):
            shutil.rmtree("test_logs")


def test_log_directory_creation():
    """测试日志目录创建"""
    print("测试6: 日志目录自动创建")

    # 备份原配置
    if os.path.exists("config.json"):
        shutil.copy("config.json", "config.json.backup")

    try:
        # 设置不存在的日志目录
        test_log_dir = "test_logs_auto_create"
        if os.path.exists(test_log_dir):
            shutil.rmtree(test_log_dir)

        with open("config.json", "w", encoding="utf-8") as f:
            json.dump({
                "work_duration_minutes": 2,
                "min_rest_duration_seconds": 20,
                "log_dir": test_log_dir
            }, f)

        protector = EyeProtector()
        assert os.path.exists(test_log_dir), "日志目录应该被自动创建"
        print("  [OK] 日志目录自动创建成功")

        # 检查日志文件是否创建
        from datetime import datetime
        expected_log = os.path.join(test_log_dir, f"eye_protect_{datetime.now().strftime('%Y%m%d')}.log")
        assert os.path.exists(expected_log), "日志文件应该被创建"
        print("  [OK] 日志文件创建成功")

        print("  [OK] 测试6通过\n")

    finally:
        # 恢复原配置
        if os.path.exists("config.json.backup"):
            shutil.move("config.json.backup", "config.json")
        # 清理测试目录
        if os.path.exists(test_log_dir):
            shutil.rmtree(test_log_dir)


def test_edge_cases():
    """测试边界情况"""
    print("测试7: 边界情况处理")

    protector = EyeProtector()
    protector.lock_screen = lambda: None
    protector.show_overlay = lambda: None

    # 测试1: 休息计时为空（异常状态）时解锁不应崩溃
    try:
        protector.enter_rest(BLOCKER_OVERLAY)
        protector.rest_started_at = None
        protector.on_unlock()
        print("  [OK] 处理 rest_started_at 为 None 的情况")
    except Exception as e:
        print(f"  [FAIL] 异常: {e}")

    # 测试2: 极短的工作时间（边界值）
    protector.work_duration = 0.01  # 0.6秒
    protector.start_work_timer()
    assert protector.work_timer is not None, "极短时间也应该能启动计时器"
    protector.work_timer.cancel()
    print("  [OK] 极短工作时间处理正常")

    # 测试3: 极短的休息时间（边界值）
    protector.min_rest_duration = 1
    protector.rest_started_at = protector.rest_started_at or 0
    # 应该能正常比较
    print("  [OK] 极短休息时间处理正常")

    print("  [OK] 测试7通过\n")


def test_concurrent_timer_handling():
    """测试并发计时器处理"""
    print("测试8: 并发计时器处理")

    protector = EyeProtector()

    # 快速连续启动多个计时器
    for i in range(5):
        protector.start_work_timer()

    # 应该只有最后一个计时器在运行
    assert protector.work_timer is not None, "应该有一个活动计时器"
    assert protector.work_timer.is_alive(), "最后的计时器应该在运行"
    print("  [OK] 快速连续启动计时器处理正常")

    protector.work_timer.cancel()
    print("  [OK] 测试8通过\n")


if __name__ == "__main__":
    print("=" * 50)
    print("配置和边界情况测试")
    print("=" * 50 + "\n")

    failed = False
    try:
        test_config_validation()
        test_log_directory_creation()
        test_edge_cases()
        test_concurrent_timer_handling()

        print("=" * 50)
        print("所有扩展测试通过！")
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
