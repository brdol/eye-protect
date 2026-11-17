"""测试在线升级的版本比较逻辑（不联网）。"""
import sys

from _bootstrap import *
from updater import parse_version, is_newer


def test_parse_version():
    print("测试1: 版本号解析")
    assert parse_version("v1.2.3") == [1, 2, 3]
    assert parse_version("1.0") == [1, 0]
    assert parse_version("2") == [2]
    assert parse_version("") == [0]
    assert parse_version("1.2.3-rc1") == [1, 2, 3, 0]
    print("  [OK] 版本号解析正确")
    print("  [OK] 测试1通过\n")


def test_is_newer():
    print("测试2: 版本比较")
    assert is_newer("v1.2.0", "1.1.9")
    assert is_newer("2.0.0", "1.9.9")
    assert is_newer("1.0.1", "1.0.0")
    assert not is_newer("v1.0.0", "1.0.0")
    assert not is_newer("v0.9", "1.0")
    print("  [OK] 版本比较正确")
    print("  [OK] 测试2通过\n")


if __name__ == "__main__":
    print("=" * 50)
    print("在线升级版本逻辑测试")
    print("=" * 50 + "\n")

    failed = False
    try:
        test_parse_version()
        test_is_newer()
        print("=" * 50)
        print("所有升级测试通过！")
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
