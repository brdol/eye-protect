"""测试软提示（休息提醒弹窗）的状态逻辑与布局度量

状态逻辑不创建真实窗口：把 lock_screen 打桩为空函数，各状态方法在
prompt_hwnd 为 None 时不会触碰 UI，因此可纯逻辑验证。
布局度量只依赖 GDI 字体，不需要窗口，可直接验证"控件不越界/字号越大窗口越大"。
"""
import sys
import time

from _bootstrap import *
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
    print("测试2: 推迟已达上限（非免打扰）→ 强制锁屏")
    p = new_protector()
    p.prompt_active = True
    p.postpone_count = p.max_postpones
    try:
        p.on_prompt_postpone()
        assert p.is_resting, "应进入休息（强制锁屏）"
        assert not p.prompt_active, "提示应已关闭"
        print("  [OK] 达上限后强制锁屏")
        print("  [OK] 测试2通过\n")
    finally:
        cleanup(p)


def test_postpone_at_cap_when_dnd():
    print("测试3: 免打扰 + 达上限 → 不锁屏，继续延后")
    p = new_protector()
    p.prompt_active = True
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
    p.prompt_active = True
    try:
        p.on_grace_timeout()
        assert p.is_resting, "非免打扰时宽限超时应锁屏"
        assert not p.prompt_active, "提示应已关闭"
        print("  [OK] 宽限超时触发锁屏")
        print("  [OK] 测试4通过\n")
    finally:
        cleanup(p)


def test_grace_timeout_skips_when_dnd():
    print("测试5: 宽限期满（免打扰）→ 跳过，不锁屏")
    p = new_protector()
    p.prompt_active = True
    p.dnd_mode = True
    try:
        p.on_grace_timeout()
        assert not p.is_resting, "免打扰时不应锁屏"
        assert not p.prompt_active, "提示应已关闭"
        assert p.work_timer is not None, "应启动推迟计时器"
        assert p.postpone_count == 0, "免打扰时不应增加推迟计数"
        print("  [OK] 免打扰跳过本轮")
        print("  [OK] 测试5通过\n")
    finally:
        cleanup(p)


def test_grace_timeout_noop_when_idle():
    print("测试6: 非提示时宽限期满为空操作")
    p = new_protector()
    p.prompt_active = False
    try:
        p.on_grace_timeout()
        assert not p.is_resting, "不应进入休息"
        assert not p.prompt_active, "提示状态不变"
        print("  [OK] 非提示时为空操作")
        print("  [OK] 测试6通过\n")
    finally:
        cleanup(p)


def test_sufficient_rest_resets_state():
    print("测试7: 休息达标重置推迟计数与免打扰")
    p = new_protector()
    p.is_resting = True
    p.lock_time = time.time() - (p.min_rest_duration + 10)
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
    p.is_resting = True
    p.lock_time = time.time()
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
    p.prompt_active = True
    p.lock_time = None
    try:
        p.on_lock()
        assert not p.prompt_active, "提示应已关闭"
        assert p.is_resting, "应进入休息"
        assert p.lock_time is not None, "应记录锁屏时间"
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
