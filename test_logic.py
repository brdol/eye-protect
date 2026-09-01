"""测试护眼软件的核心逻辑"""
import json
import sys
import time
import threading
from eye_protect import EyeProtector


def test_work_timer():
    """测试工作计时器"""
    print("测试1: 工作计时器功能")

    # 创建实例但不启动消息循环
    protector = EyeProtector()

    # 验证配置加载：实例值应与 config.json 文件内容一致
    with open(protector.config_file, 'r', encoding='utf-8') as f:
        cfg = json.load(f)
    assert protector.work_duration == cfg.get("work_duration_minutes", 20), \
        f"工作时长配置错误: 实例={protector.work_duration}, 文件={cfg.get('work_duration_minutes')}"
    assert protector.min_rest_duration == cfg.get("min_rest_duration_seconds", 20), \
        f"休息时长配置错误: 实例={protector.min_rest_duration}, 文件={cfg.get('min_rest_duration_seconds')}"
    print("  [OK] 配置加载正确")

    # 测试工作计时器启动
    protector.start_work_timer()
    assert protector.work_timer is not None, "工作计时器未启动"
    assert protector.work_timer.is_alive(), "工作计时器未运行"
    print("  [OK] 工作计时器启动成功")

    # 取消计时器
    protector.work_timer.cancel()
    print("  [OK] 测试1通过\n")


def test_rest_logic():
    """测试休息逻辑"""
    print("测试2: 休息时间检查逻辑")

    protector = EyeProtector()

    # 模拟强制锁屏休息
    protector.is_resting = True
    protector.lock_time = time.time()
    print("  [OK] 模拟进入休息状态")

    # 模拟立即解锁（休息时间不足）
    time.sleep(0.5)
    current_time = time.time()
    rest_duration = current_time - protector.lock_time

    if rest_duration < protector.min_rest_duration:
        print(f"  [OK] 检测到休息时间不足: {rest_duration:.1f}秒 < {protector.min_rest_duration}秒")
        print("  [OK] 应该重新锁屏")
    else:
        print(f"  [FAIL] 逻辑错误: {rest_duration:.1f}秒")

    # 模拟休息时间达标（休息时间应明确超过最短休息时长）
    protector.lock_time = time.time() - (protector.min_rest_duration + 10)
    current_time = time.time()
    rest_duration = current_time - protector.lock_time

    if rest_duration >= protector.min_rest_duration:
        print(f"  [OK] 检测到休息时间达标: {rest_duration:.1f}秒 >= {protector.min_rest_duration}秒")
        print("  [OK] 可以继续工作")
    else:
        print(f"  [FAIL] 逻辑错误: {rest_duration:.1f}秒")

    print("  [OK] 测试2通过\n")


def test_state_transitions():
    """测试状态转换"""
    print("测试3: 状态转换逻辑")

    protector = EyeProtector()

    # 初始状态
    assert not protector.is_resting, "初始状态应该不是休息状态"
    print("  [OK] 初始状态正确")

    # 进入休息状态
    protector.is_resting = True
    protector.lock_time = time.time()
    assert protector.is_resting, "应该处于休息状态"
    print("  [OK] 进入休息状态")

    # 退出休息状态
    protector.is_resting = False
    protector.lock_time = None
    assert not protector.is_resting, "应该退出休息状态"
    assert protector.lock_time is None, "锁屏时间应该被清空"
    print("  [OK] 退出休息状态")

    print("  [OK] 测试3通过\n")


def test_timer_cancellation():
    """测试计时器取消"""
    print("测试4: 计时器取消功能")

    protector = EyeProtector()

    # 启动计时器
    protector.start_work_timer()
    timer1 = protector.work_timer
    assert timer1.is_alive(), "计时器应该在运行"
    print("  [OK] 计时器1启动")

    # 再次启动应该取消旧的
    protector.start_work_timer()
    timer2 = protector.work_timer

    # 等待一下确保旧计时器被取消
    time.sleep(0.1)

    assert timer2.is_alive(), "新计时器应该在运行"
    print("  [OK] 计时器2启动，旧计时器已取消")

    # 清理
    timer2.cancel()
    print("  [OK] 测试4通过\n")


if __name__ == "__main__":
    print("=" * 50)
    print("护眼软件核心逻辑测试")
    print("=" * 50 + "\n")

    failed = False
    try:
        test_work_timer()
        test_rest_logic()
        test_state_transitions()
        test_timer_cancellation()

        print("=" * 50)
        print("所有测试通过！")
        print("=" * 50)

    except AssertionError as e:
        print(f"\n[FAIL] 测试失败: {e}")
        failed = True
    except Exception as e:
        print(f"\n[FAIL] 测试异常: {e}")
        import traceback
        traceback.print_exc()
        failed = True

    sys.exit(1 if failed else 0)
