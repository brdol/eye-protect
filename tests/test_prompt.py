"""测试软提示（休息提醒弹窗）的状态逻辑与布局度量

状态逻辑不创建真实窗口：把 lock_screen 打桩为空函数，各状态方法在
prompt_hwnd 为 None 时不会触碰 UI，因此可纯逻辑验证。
布局度量只依赖 GDI 字体，不需要窗口，可直接验证"控件不越界/字号越大窗口越大"。
"""
import sys
import time

from _bootstrap import *
from eye_protect import (EyeProtector, WM_APP_PROMPT, WM_APP_HARD_LOCK,
                         STATE_WORKING, STATE_PROMPTING, STATE_RESTING,
                         BLOCKER_LOCK, BLOCKER_OVERLAY)


def new_protector():
    """新建实例并打桩 lock_screen，避免真实锁屏。显式设定可配置项，保证测试与 config.json 当前值无关。"""
    p = EyeProtector()
    p.lock_screen = lambda: None
    # 默认不打桩 show_overlay 会导致测试真的弹出全屏遮罩并安装键盘钩子
    p.show_overlay = lambda: None
    p.grace_seconds = 60
    p.postpone_minutes = 5
    p.max_postpones = 3
    p.min_rest_duration = 20
    p.work_duration = 20
    p.dnd_mode = False
    return p


def cleanup(p):
    if p.grace_timer:
        p.grace_timer.cancel()
    if p.work_timer:
        p.work_timer.cancel()


def test_postpone_under_cap():
    print("测试1: 推迟未达上限（非免打扰）")
    p = new_protector()
    p.state = STATE_PROMPTING
    try:
        p.on_prompt_postpone()
        assert p.postpone_count == 1, f"postpone_count 应为1，实际{p.postpone_count}"
        assert not p.is_resting, "不应进入休息"
        assert p.work_timer is not None, "应启动推迟计时器"
        assert p.work_timer.interval == p.postpone_minutes * 60, "推迟计时器时长错误"
        assert p.state != STATE_PROMPTING, "提示应已关闭"
        print("  [OK] 推迟成功，启动推迟计时器")
        print("  [OK] 测试1通过\n")
    finally:
        cleanup(p)


def test_postpone_at_cap():
    print("测试2: 推迟已达上限（非免打扰）→ 强制锁屏")
    p = new_protector()
    p.state = STATE_PROMPTING
    p.postpone_count = p.max_postpones
    try:
        p.on_prompt_postpone()
        assert p.is_resting, "应进入休息（强制锁屏）"
        assert p.state != STATE_PROMPTING, "提示应已关闭"
        print("  [OK] 达上限后强制锁屏")
        print("  [OK] 测试2通过\n")
    finally:
        cleanup(p)


def test_postpone_at_cap_when_dnd():
    print("测试3: 免打扰 + 达上限 → 不锁屏，继续延后")
    p = new_protector()
    p.state = STATE_PROMPTING
    p.dnd_mode = True
    p.postpone_count = p.max_postpones
    try:
        p.on_prompt_postpone()
        assert not p.is_resting, "免打扰时不应锁屏"
        assert p.work_timer is not None, "应启动推迟计时器"
        assert p.work_timer.interval == p.postpone_minutes * 60, "计时器时长错误"
        assert p.postpone_count == p.max_postpones, "免打扰时不应增加推迟计数"
        print("  [OK] 免打扰豁免上限，继续延后")
        print("  [OK] 测试3通过\n")
    finally:
        cleanup(p)


def test_grace_timeout_locks_when_not_dnd():
    print("测试4: 宽限期满（非免打扰）→ 强制锁屏")
    p = new_protector()
    p.state = STATE_PROMPTING
    try:
        p.on_grace_timeout()
        assert p.is_resting, "非免打扰时宽限超时应锁屏"
        assert p.state != STATE_PROMPTING, "提示应已关闭"
        print("  [OK] 宽限超时触发锁屏")
        print("  [OK] 测试4通过\n")
    finally:
        cleanup(p)


def test_grace_timeout_skips_when_dnd():
    print("测试5: 宽限期满（免打扰）→ 跳过，不锁屏")
    p = new_protector()
    p.state = STATE_PROMPTING
    p.dnd_mode = True
    try:
        p.on_grace_timeout()
        assert not p.is_resting, "免打扰时不应锁屏"
        assert p.state != STATE_PROMPTING, "提示应已关闭"
        assert p.work_timer is not None, "应启动推迟计时器"
        assert p.postpone_count == 0, "免打扰时不应增加推迟计数"
        print("  [OK] 免打扰跳过本轮")
        print("  [OK] 测试5通过\n")
    finally:
        cleanup(p)


def test_grace_timeout_noop_when_idle():
    print("测试6: 非提示时宽限期满为空操作")
    p = new_protector()
    p.state = STATE_WORKING
    try:
        p.on_grace_timeout()
        assert not p.is_resting, "不应进入休息"
        assert p.state != STATE_PROMPTING, "提示状态不变"
        print("  [OK] 非提示时为空操作")
        print("  [OK] 测试6通过\n")
    finally:
        cleanup(p)


def test_sufficient_rest_resets_state():
    print("测试7: 休息达标重置推迟计数与免打扰")
    p = new_protector()
    p.state = STATE_RESTING
    p.rest_blocker = BLOCKER_LOCK
    p.rest_enforced = True
    p.rest_started_at = time.time() - (p.min_rest_duration + 10)
    p.postpone_count = 2
    p.dnd_mode = True
    try:
        p.on_unlock()
        assert p.postpone_count == 0, f"应重置为0，实际{p.postpone_count}"
        assert p.dnd_mode is False, "休息达标后应取消免打扰"
        assert not p.is_resting, "应退出休息"
        assert p.work_timer is not None, "应启动工作计时"
        assert p.work_timer.interval == p.work_duration * 60, "应使用完整工作时长"
        print("  [OK] 休息达标，推迟计数与免打扰均重置")
        print("  [OK] 测试7通过\n")
    finally:
        cleanup(p)


def test_insufficient_rest_keeps_state():
    print("测试8: 休息不足保持推迟计数")
    p = new_protector()
    p.state = STATE_RESTING
    p.rest_blocker = BLOCKER_LOCK
    p.rest_enforced = True
    p.rest_started_at = time.time()
    p.postpone_count = 2
    try:
        p.on_unlock()
        assert p.is_resting, "应仍处于休息"
        assert p.postpone_count == 2, f"推迟计数应不变，实际{p.postpone_count}"
        print("  [OK] 休息不足，推迟计数保持，重新锁屏")
        print("  [OK] 测试8通过\n")
    finally:
        cleanup(p)
    time.sleep(1.2)  # 等待 1 秒重锁定时器（已打桩，无害）


def test_route_work_timeout():
    print("测试9: 锁屏模式路由")
    p = new_protector()
    p.lock_mode = "hard"
    assert p._route_work_timeout() == WM_APP_HARD_LOCK, "hard 模式应路由到硬锁"
    p.lock_mode = "prompt"
    assert p._route_work_timeout() == WM_APP_PROMPT, "prompt 模式应路由到提示"
    p.lock_mode = "unknown"
    assert p._route_work_timeout() == WM_APP_PROMPT, "未知模式默认按提示"
    print("  [OK] hard→硬锁，prompt/未知→提示")
    print("  [OK] 测试9通过\n")


def test_manual_lock_during_prompt():
    print("测试10: 提示期间手动锁屏 → 进入休息")
    p = new_protector()
    p.state = STATE_PROMPTING
    try:
        p.on_lock()
        assert p.state == STATE_RESTING, "应进入休息"
        assert p.rest_blocker == BLOCKER_LOCK, "blocker 应为锁屏"
        assert p.rest_started_at is not None, "应记录休息开始时间"
        print("  [OK] 提示期间锁屏，关闭提示并进入休息")
        print("  [OK] 测试10通过\n")
    finally:
        cleanup(p)


def test_layout_controls_within_client():
    print("测试11: 自动布局——控件不越界")
    p = new_protector()
    p._setup_gdi()
    old = p._set_prompt_font(96)
    try:
        m = p._measure_prompt_layout(96)
    finally:
        p._release_font(old)
    for key in ("msg", "dnd", "count", "btn_sleep", "btn_postpone"):
        x, y, w, h = m[key]
        assert x >= 0 and y >= 0, f"{key} 起点越界: {(x, y)}"
        assert x + w <= m["client_w"], f"{key} 右边越界: {x + w} > {m['client_w']}"
        assert y + h <= m["client_h"], f"{key} 下边越界: {y + h} > {m['client_h']}"
    assert m["win_w"] > 0 and m["win_h"] > 0, "窗口尺寸应大于0"
    print(f"  [OK] 客户区 {m['client_w']}x{m['client_h']}，窗口 {m['win_w']}x{m['win_h']}，控件均在界内")
    print("  [OK] 测试11通过\n")


def test_larger_font_grows_window():
    print("测试12: 字号增大 → 窗口随之增大")
    p = new_protector()
    p._setup_gdi()
    p.prompt_font_size = 8
    old = p._set_prompt_font(96)
    m8 = p._measure_prompt_layout(96)
    p._release_font(old)
    p.prompt_font_size = 14
    old = p._set_prompt_font(96)
    m14 = p._measure_prompt_layout(96)
    p._release_font(old)
    assert m14["win_h"] > m8["win_h"], f"高度应增大: {m8['win_h']} -> {m14['win_h']}"
    assert m14["win_w"] >= m8["win_w"], f"宽度不应缩小: {m8['win_w']} -> {m14['win_w']}"
    print(f"  [OK] 8pt={m8['win_w']}x{m8['win_h']}，14pt={m14['win_w']}x{m14['win_h']}")
    print("  [OK] 测试12通过\n")


def test_font_uses_raw_ppi():
    print("测试13: 字号按真实 PPI 换算（不随 Windows 缩放漂移）")
    p = new_protector()
    p.prompt_font_size = 8
    assert p._font_dpi(144, 108) == 108, "应优先使用真实 PPI"
    assert p._font_dpi(96, 0) == 96, "raw 无效时回退有效 DPI"
    assert p._font_dpi(96, 5000) == 96, "raw 超范围时回退有效 DPI"
    assert p._font_dpi(120, 30) == 120, "raw 过小时回退有效 DPI"
    px_100 = p._font_px(p._font_dpi(96, 108))
    px_150 = p._font_px(p._font_dpi(144, 108))
    assert px_100 == px_150 == 12, f"同屏不同缩放下字号应一致，实际 {px_100}/{px_150}"
    print(f"  [OK] raw=108：100%→{px_100}px，150%→{px_150}px（一致）；异常 raw 自动回退")
    print("  [OK] 测试13通过\n")


def test_rest_style_defaults_to_overlay():
    print("测试14: rest_style 默认值")
    p = new_protector()
    assert p.rest_style in ("overlay", "lock"), f"rest_style 非法: {p.rest_style}"
    assert p.rest_style == "overlay", f"默认应为 overlay，实际 {p.rest_style}"
    print("  [OK] 默认 overlay")
    print("  [OK] 测试14通过\n")


def test_enter_rest_overlay_does_not_lock():
    print("测试15: overlay 模式休息不锁屏")
    p = new_protector()
    called = {"lock": 0, "overlay": 0}
    p.lock_screen = lambda: called.__setitem__("lock", called["lock"] + 1)
    p.show_overlay = lambda: called.__setitem__("overlay", called["overlay"] + 1)
    p.rest_style = "overlay"
    try:
        p.enter_rest()
        assert p.is_resting, "应进入休息"
        assert called["overlay"] == 1, "应显示遮罩"
        assert called["lock"] == 0, "不应锁屏"
        print("  [OK] 进入休息时只显示遮罩，未调用 LockWorkStation")
        print("  [OK] 测试15通过\n")
    finally:
        cleanup(p)


def test_enter_rest_lock_style_locks():
    print("测试16: lock 模式休息仍锁屏")
    p = new_protector()
    called = {"lock": 0, "overlay": 0}
    p.lock_screen = lambda: called.__setitem__("lock", called["lock"] + 1)
    p.show_overlay = lambda: called.__setitem__("overlay", called["overlay"] + 1)
    p.rest_style = "lock"
    try:
        p.enter_rest()
        assert p.is_resting
        assert called["lock"] == 1 and called["overlay"] == 0
        print("  [OK] lock 模式仍调用锁屏，未显示遮罩")
        print("  [OK] 测试16通过\n")
    finally:
        cleanup(p)


def test_overlay_release_resets_state():
    print("测试17: 结束休息后状态复位")
    p = new_protector()
    p.rest_style = "overlay"
    p.state = STATE_RESTING
    p.rest_blocker = BLOCKER_OVERLAY
    p.rest_enforced = True
    p.rest_started_at = time.time() - (p.min_rest_duration + 5)
    p._rest_ready = True
    p.postpone_count = 2
    p.dnd_mode = True
    try:
        p.on_overlay_release()
        assert not p.is_resting, "应退出休息"
        assert not p.overlay_active, "遮罩应关闭"
        assert p.postpone_count == 0, "推迟计数应重置"
        assert p.dnd_mode is False, "免打扰应重置"
        assert p.work_timer is not None, "应重新开始工作计时"
        print("  [OK] 遮罩释放后状态复位并重启工作计时")
        print("  [OK] 测试17通过\n")
    finally:
        cleanup(p)


def test_rest_messages_default_and_pick():
    print("测试18: 遮罩文案列表与随机选择")
    p = new_protector()
    assert isinstance(p.rest_messages, list) and p.rest_messages, "默认文案列表不应为空"
    assert all(isinstance(m, str) and m.strip() for m in p.rest_messages), "文案应为非空字符串"
    for _ in range(30):
        assert p._pick_rest_message() in p.rest_messages, "随机结果必须来自列表"
    print(f"  [OK] {len(p.rest_messages)} 条文案，随机选择均来自列表")
    print("  [OK] 测试18通过\n")


def test_stale_prompt_ignored_when_not_working():
    print("测试19: 非工作状态的迟到提示被忽略")
    p = new_protector()
    p.state = STATE_RESTING
    p.rest_blocker = BLOCKER_OVERLAY
    p.rest_started_at = time.time()
    try:
        p.show_prompt()
        assert p.state == STATE_RESTING, "状态不应被改变"
        assert p.prompt_hwnd is None, "不应创建提示窗口"
        print("  [OK] 休息中收到迟到的提示消息 → 忽略")
        print("  [OK] 测试19通过\n")
    finally:
        cleanup(p)


def test_lock_during_overlay_switches_blocker():
    print("测试20: 遮罩期间锁屏 → 切换 blocker，休息不重新计时")
    p = new_protector()
    p.enter_rest(BLOCKER_OVERLAY)
    started = p.rest_started_at
    try:
        p.on_lock()
        assert p.state == STATE_RESTING, "应仍在休息"
        assert p.rest_blocker == BLOCKER_LOCK, "blocker 应切换为锁屏"
        assert p.rest_started_at == started, "连续休息不应重新计时"
        print("  [OK] blocker 切换为锁屏，计时保持连续")
        print("  [OK] 测试20通过\n")
    finally:
        cleanup(p)


def test_unlock_after_rest_leaves_rest_cleanly():
    print("测试21: 锁屏休息足够后解锁 → 干净离开休息（含残留遮罩清理）")
    p = new_protector()
    p.enter_rest(BLOCKER_LOCK)
    p.rest_started_at = time.time() - (p.min_rest_duration + 10)
    p._rest_ready = True  # 模拟可能残留的遮罩 UI 状态
    try:
        p.on_unlock()
        assert p.state == STATE_WORKING, "应回到工作状态"
        assert not p.overlay_active, "遮罩应被清理"
        assert p.work_timer is not None, "应重新开始工作计时"
        print("  [OK] 解锁后状态干净，无残留 UI")
        print("  [OK] 测试21通过\n")
    finally:
        cleanup(p)


def test_voluntary_lock_does_not_enforce_min_rest():
    print("测试22: 工作中自愿锁屏 → 不强制最短休息")
    p = new_protector()
    p.start_work_timer()
    try:
        p.on_lock()
        assert p.state == STATE_RESTING, "应记录为休息"
        assert p.rest_enforced is False, "自愿锁屏不应强制执行最短休息"
        p.on_unlock()
        assert p.state == STATE_WORKING, "立即解锁应直接恢复工作"
        assert p.work_timer is not None
        print("  [OK] 自愿锁屏只暂停，不强制执行最短休息")
        print("  [OK] 测试22通过\n")
    finally:
        cleanup(p)


def test_early_unlock_restarts_rest_clock():
    print("测试23: 强制休息中提前解锁 → 重新计时")
    p = new_protector()
    p.enter_rest(BLOCKER_LOCK)
    p.rest_started_at = time.time()
    try:
        p.on_unlock()
        assert p.state == STATE_RESTING, "休息不足应保持休息"
        assert p.rest_started_at is None, "应由下一次锁屏重新开始计时"
        print("  [OK] 提前解锁不累计，重新计时")
        print("  [OK] 测试23通过\n")
    finally:
        cleanup(p)
    time.sleep(1.2)


if __name__ == "__main__":
    print("=" * 50)
    print("软提示状态逻辑与布局测试")
    print("=" * 50 + "\n")

    failed = False
    try:
        test_postpone_under_cap()
        test_postpone_at_cap()
        test_postpone_at_cap_when_dnd()
        test_grace_timeout_locks_when_not_dnd()
        test_grace_timeout_skips_when_dnd()
        test_grace_timeout_noop_when_idle()
        test_sufficient_rest_resets_state()
        test_insufficient_rest_keeps_state()
        test_route_work_timeout()
        test_manual_lock_during_prompt()
        test_layout_controls_within_client()
        test_larger_font_grows_window()
        test_font_uses_raw_ppi()
        test_rest_style_defaults_to_overlay()
        test_enter_rest_overlay_does_not_lock()
        test_enter_rest_lock_style_locks()
        test_overlay_release_resets_state()
        test_rest_messages_default_and_pick()
        test_stale_prompt_ignored_when_not_working()
        test_lock_during_overlay_switches_blocker()
        test_unlock_after_rest_leaves_rest_cleanly()
        test_voluntary_lock_does_not_enforce_min_rest()
        test_early_unlock_restarts_rest_clock()

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
