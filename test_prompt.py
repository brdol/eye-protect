"""测试软提示（休息提醒弹窗）的状态逻辑

只测状态机逻辑，不创建真实窗口：把 lock_screen 打桩为空函数，
各状态方法在 prompt_hwnd 为 None 时不会触碰 UI，因此可纯逻辑验证。
"""
import sys
import time

from eye_protect import EyeProtector, WM_APP_PROMPT, WM_APP_HARD_LOCK


def new_protector():
    """新建实例并打桩 lock_screen，避免真实锁屏。显式设定可配置项，保证测试与 config.json 当前值无关。"""
    p = EyeProtector()
    p.lock_screen = lambda: None
    p.grace_seconds = 60
    p.postpone_minutes = 5
    p.max_postpones = 3
    p.min_rest_duration = 20
    p.work_duration = 20
    return p


def cleanup(p):
    if p.grace_timer:
        p.grace_timer.cancel()
    if p.work_timer:
        p.work_timer.cancel()


def test_postpone_under_cap():
    print("测试1: 推迟未达上限")
    p = new_protector()
    p.prompt_active = True
    try:
        p.on_prompt_postpone()
        assert p.postpone_count == 1, f"postpone_count 应为1，实际{p.postpone_count}"
        assert not p.is_resting, "不应进入休息"
        assert p.work_timer is not None, "应启动推迟计时器"
        assert p.work_timer.interval == p.postpone_minutes * 60, "推迟计时器时长错误"
        assert not p.prompt_active, "提示应已关闭"
        print("  [OK] 推迟成功，启动推迟计时器")
        print("  [OK] 测试1通过\n")
    finally:
        cleanup(p)


def test_postpone_at_cap():
    print("测试2: 推迟已达上限，强制锁屏")
    p = new_protector()
    p.prompt_active = True
    p.postpone_count = p.max_postpones  # 已达上限
    try:
        p.on_prompt_postpone()
        assert p.is_resting, "应进入休息（强制锁屏）"
        assert not p.prompt_active, "提示应已关闭"
        print("  [OK] 达上限后强制锁屏")
        print("  [OK] 测试2通过\n")
    finally:
        cleanup(p)


def test_grace_timeout_while_prompting():
    print("测试3: 宽限期满（提示中）→ 锁屏")
    p = new_protector()
    p.prompt_active = True
    try:
        p.on_grace_timeout()
        assert p.is_resting, "应进入休息"
        assert not p.prompt_active, "提示应已关闭"
        print("  [OK] 宽限期满触发锁屏")
        print("  [OK] 测试3通过\n")
    finally:
        cleanup(p)


def test_grace_timeout_noop_when_idle():
    print("测试4: 非提示时宽限期满为空操作")
    p = new_protector()
    p.prompt_active = False
    try:
        p.on_grace_timeout()
        assert not p.is_resting, "不应进入休息"
        assert not p.prompt_active, "提示状态不变"
        print("  [OK] 非提示时为空操作")
        print("  [OK] 测试4通过\n")
    finally:
        cleanup(p)


def test_sufficient_rest_resets_count():
    print("测试5: 休息达标重置推迟计数")
    p = new_protector()
    p.is_resting = True
    p.lock_time = time.time() - (p.min_rest_duration + 10)
    p.postpone_count = 2
    try:
        p.on_unlock()
        assert p.postpone_count == 0, f"应重置为0，实际{p.postpone_count}"
        assert not p.is_resting, "应退出休息"
        assert p.work_timer is not None, "应启动工作计时"
        assert p.work_timer.interval == p.work_duration * 60, "应使用完整工作时长"
        print("  [OK] 休息达标，推迟计数归零，重启完整工作计时")
        print("  [OK] 测试5通过\n")
    finally:
        cleanup(p)


def test_insufficient_rest_keeps_count():
    print("测试6: 休息不足保持推迟计数")
    p = new_protector()
    p.is_resting = True
    p.lock_time = time.time()  # 刚锁屏，休息≈0
    p.postpone_count = 2
    try:
        p.on_unlock()
        assert p.is_resting, "应仍处于休息"
        assert p.postpone_count == 2, f"推迟计数应不变，实际{p.postpone_count}"
        print("  [OK] 休息不足，推迟计数保持，重新锁屏")
        print("  [OK] 测试6通过\n")
    finally:
        cleanup(p)
    # 等待可能产生的 1 秒重锁定时器（已打桩 lock_screen，无害）
    time.sleep(1.2)


def test_route_work_timeout():
    print("测试7: 锁屏模式路由")
    p = new_protector()
    p.lock_mode = "hard"
    assert p._route_work_timeout() == WM_APP_HARD_LOCK, "hard 模式应路由到硬锁"
    p.lock_mode = "prompt"
    assert p._route_work_timeout() == WM_APP_PROMPT, "prompt 模式应路由到提示"
    p.lock_mode = "unknown"
    assert p._route_work_timeout() == WM_APP_PROMPT, "未知模式默认按提示"
    print("  [OK] hard→硬锁，prompt/未知→提示")
    print("  [OK] 测试7通过\n")


def test_manual_lock_during_prompt():
    print("测试8: 提示期间手动锁屏 → 进入休息")
    p = new_protector()
    p.prompt_active = True
    p.lock_time = None
    try:
        p.on_lock()
        assert not p.prompt_active, "提示应已关闭"
        assert p.is_resting, "应进入休息"
        assert p.lock_time is not None, "应记录锁屏时间"
        print("  [OK] 提示期间锁屏，关闭提示并进入休息")
        print("  [OK] 测试8通过\n")
    finally:
        cleanup(p)


if __name__ == "__main__":
    print("=" * 50)
    print("软提示状态逻辑测试")
    print("=" * 50 + "\n")

    failed = False
    try:
        test_postpone_under_cap()
        test_postpone_at_cap()
        test_grace_timeout_while_prompting()
        test_grace_timeout_noop_when_idle()
        test_sufficient_rest_resets_count()
        test_insufficient_rest_keeps_count()
        test_route_work_timeout()
        test_manual_lock_during_prompt()

        print("=" * 50)
        print("所有软提示测试通过！")
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
