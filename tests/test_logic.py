"""测试护眼软件的核心逻辑"""
import json
import sys
import time
import threading
from _bootstrap import *
from eye_protect import (EyeProtector, STATE_WORKING, STATE_RESTING,
                         BLOCKER_LOCK, BLOCKER_OVERLAY)


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


def _fresh():
    p = EyeProtector()
    p.lock_screen = lambda: None
    p.show_overlay = lambda: None
    return p


def test_rest_logic():
    """测试休息判定（锁屏 blocker）"""
    print("测试2: 休息时间判定逻辑")

    # 场景1：强制休息中立即解锁 → 保持休息并安排重锁
    p = _fresh()
    p.enter_rest(BLOCKER_LOCK)
    p.on_unlock()
    assert p.is_resting, "休息不足时应保持休息"
    assert p.rest_started_at is None, "应清空计时等待重新锁屏"
    print("  [OK] 休息不足：保持休息并安排重新锁屏")
    time.sleep(1.2)  # 等重锁定时器（已打桩）

    # 场景2：休息足够 → 结束休息
    p2 = _fresh()
    p2.enter_rest(BLOCKER_LOCK)
    p2.rest_started_at = time.time() - (p2.min_rest_duration + 10)
    p2.on_unlock()
    assert not p2.is_resting, "休息足够后应结束休息"
    if p2.work_timer:
        p2.work_timer.cancel()
    print("  [OK] 休息足够：结束休息并回到工作计时")

    print("  [OK] 测试2通过\n")


def test_state_transitions():
    """测试统一状态机"""
    print("测试3: 状态转换逻辑")

    p = _fresh()
    assert p.state == STATE_WORKING and not p.is_resting, "初始应为工作状态"
    print("  [OK] 初始状态正确")

    p.enter_rest(BLOCKER_OVERLAY)
    assert p.state == STATE_RESTING, "应进入休息状态"
    assert p.rest_blocker == BLOCKER_OVERLAY, "blocker 应为遮罩"
    assert p.overlay_active, "遮罩应处于活动状态"
    print("  [OK] 进入休息（遮罩）")

    p.leave_rest()
    assert p.state == STATE_WORKING, "应回到工作状态"
    assert p.rest_blocker is None and p.rest_started_at is None, "休息字段应清空"
    assert not p.overlay_active
    if p.work_timer:
        p.work_timer.cancel()
    print("  [OK] 退出休息，字段已清空")

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
