"""测试在线升级的版本比较与文件替换逻辑（不联网）。"""
import os
import shutil
import sys
import tempfile

from _bootstrap import *
from updater import parse_version, is_newer, _find_new_root, _copy_app_files


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


def test_find_new_root():
    print("测试3: 定位更新包根目录")
    tmp = tempfile.mkdtemp()
    try:
        root = os.path.join(tmp, "outer", "EyeProtect")
        os.makedirs(root)
        open(os.path.join(root, "eye_protect.py"), "w").close()
        assert _find_new_root(tmp) == root, "应找到包含 eye_protect.py 的目录"
        print("  [OK] 能定位到更新包根目录")
        print("  [OK] 测试3通过\n")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_copy_app_files_preserves_user_data():
    print("测试4: 替换应用文件时保留用户数据")
    src = tempfile.mkdtemp()
    dst = tempfile.mkdtemp()
    try:
        # 新版本包：应用文件 + 一个 python\（不应被复制）
        for name in ("eye_protect.py", "install_service.py", "updater.py",
                     "install.bat", "config.example.json", "README.md"):
            with open(os.path.join(src, name), "w", encoding="utf-8") as f:
                f.write("new")
        os.makedirs(os.path.join(src, "python"))
        with open(os.path.join(src, "python", "python.exe"), "w") as f:
            f.write("bundled")

        # 已有安装：用户配置、日志、运行时
        with open(os.path.join(dst, "eye_protect.py"), "w") as f:
            f.write("old")
        with open(os.path.join(dst, "config.json"), "w") as f:
            f.write("user-config")
        os.makedirs(os.path.join(dst, "logs"))
        with open(os.path.join(dst, "logs", "a.log"), "w") as f:
            f.write("log")
        os.makedirs(os.path.join(dst, "python"))
        with open(os.path.join(dst, "python", "python.exe"), "w") as f:
            f.write("existing")

        copied = _copy_app_files(src, dst)

        assert "eye_protect.py" in copied and "install.bat" in copied, "应用文件应被复制"
        with open(os.path.join(dst, "eye_protect.py")) as f:
            assert f.read() == "new", "应用文件应被更新"
        with open(os.path.join(dst, "config.json")) as f:
            assert f.read() == "user-config", "config.json 不能被覆盖"
        assert os.path.exists(os.path.join(dst, "logs", "a.log")), "logs 不能被删除"
        with open(os.path.join(dst, "python", "python.exe")) as f:
            assert f.read() == "existing", "python\\ 不能被替换"
        print("  [OK] 只更新应用文件，config/logs/python 保持不变")
        print("  [OK] 测试4通过\n")
    finally:
        shutil.rmtree(src, ignore_errors=True)
        shutil.rmtree(dst, ignore_errors=True)


if __name__ == "__main__":
    print("=" * 50)
    print("在线升级版本逻辑测试")
    print("=" * 50 + "\n")

    failed = False
    try:
        test_parse_version()
        test_is_newer()
        test_find_new_root()
        test_copy_app_files_preserves_user_data()
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
