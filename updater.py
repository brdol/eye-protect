r"""在线升级：下载最新发布包并替换应用文件。

发布包布局（官方 embeddable Python，不生成自定义 exe）：
    EyeProtect\
        python\          官方签名运行时（升级时不替换）
        *.py, *.bat, 文档

升级只替换应用文件（*.py / *.bat / 文档），保留 config.json、logs 和 python\。
运行时升级需要重新下载完整安装包。
"""
import json
import os
import shutil
import sys
import tempfile
import time
import urllib.request

REPO = "brdol/eye-protect"
API_LATEST = f"https://api.github.com/repos/{REPO}/releases/latest"
ASSET_SUFFIX = "windows_amd64.zip"
USER_AGENT = "EyeProtect-Updater"
HTTP_TIMEOUT = 30
RETRY_TRIES = 5
RETRY_DELAY = 3

APP_FILES = (
    "eye_protect.py",
    "install_service.py",
    "uninstall_service.py",
    "restart_service.py",
    "procutil.py",
    "updater.py",
    "config.example.json",
    "README.md",
    "LICENSE",
    "NOTICE",
)


def parse_version(v):
    """把 v1.2.3 / 1.2.3-rc1 之类的版本号转成可比较的整数列表。"""
    v = str(v or "").strip().lstrip("vV")
    parts = []
    for p in v.replace("-", ".").replace("_", ".").split("."):
        try:
            parts.append(int(p))
        except ValueError:
            parts.append(0)
    return parts


def is_newer(latest, current):
    a = parse_version(latest)
    b = parse_version(current)
    n = max(len(a), len(b))
    a += [0] * (n - len(a))
    b += [0] * (n - len(b))
    return a > b


def _retry(fn, tries=RETRY_TRIES, delay=RETRY_DELAY):
    """办公网络下 HTTPS 会间歇性握手失败，统一做有限次重试。"""
    last = None
    for i in range(tries):
        try:
            return fn()
        except Exception as e:
            last = e
            if i < tries - 1:
                time.sleep(delay)
    raise last


def _http_json(url):
    def _once():
        req = urllib.request.Request(url, headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": USER_AGENT,
        })
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as r:
            return json.load(r)

    return _retry(_once)


def _download(url, dest):
    def _once():
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as r, open(dest, "wb") as f:
            shutil.copyfileobj(r, f)

    _retry(_once)


def _find_new_root(extract_dir):
    for root, _dirs, files in os.walk(extract_dir):
        if "eye_protect.py" in files:
            return root
    return None


def _copy_app_files(new_root, install_dir):
    copied = []
    for name in APP_FILES:
        src = os.path.join(new_root, name)
        if os.path.exists(src):
            shutil.copy2(src, os.path.join(install_dir, name))
            copied.append(name)
    for name in os.listdir(new_root):
        if name.lower().endswith(".bat"):
            shutil.copy2(os.path.join(new_root, name), os.path.join(install_dir, name))
            copied.append(name)
    return copied


def run_upgrade(current_version):
    """执行在线升级。返回进程退出码。"""
    install_dir = os.path.dirname(os.path.abspath(__file__))
    print(f"当前版本: {current_version}")
    print("正在检查最新版本...")
    try:
        info = _http_json(API_LATEST)
    except Exception as e:
        print(f"[FAIL] 无法访问 GitHub: {e}")
        print(f"       可手动打开 https://github.com/{REPO}/releases 下载")
        return 1

    latest = info.get("tag_name", "")
    print(f"最新版本: {latest}")
    if not latest:
        print("[FAIL] 未能解析最新版本号")
        return 1
    if not is_newer(latest, current_version):
        print("[OK] 已是最新版本")
        return 0

    asset = next((a for a in info.get("assets", [])
                  if str(a.get("name", "")).endswith(ASSET_SUFFIX)), None)
    if not asset:
        print("[FAIL] 最新 Release 中未找到 Windows 安装包")
        return 1

    tmp_dir = tempfile.mkdtemp(prefix="eyeprotect-update-")
    zip_path = os.path.join(tmp_dir, "update.zip")
    print(f"下载: {asset['name']}")
    try:
        _download(asset["browser_download_url"], zip_path)
    except Exception as e:
        print(f"[FAIL] 下载失败: {e}")
        return 1

    extract_dir = os.path.join(tmp_dir, "new")
    try:
        shutil.unpack_archive(zip_path, extract_dir)
    except Exception as e:
        print(f"[FAIL] 解压失败: {e}")
        return 1

    new_root = _find_new_root(extract_dir)
    if not new_root:
        print("[FAIL] 更新包中未找到 eye_protect.py")
        return 1

    try:
        import procutil
        others = procutil.find_eye_protect_pids()
        if others:
            procutil.stop_pids(others)
    except Exception as e:
        print(f"[WARN] 停止旧实例失败: {e}")

    copied = _copy_app_files(new_root, install_dir)
    print(f"[OK] 已更新 {len(copied)} 个应用文件（config.json / logs / python\\ 未改动）")

    try:
        import procutil
        if procutil.start_background():
            print("[OK] 已用新版本重新启动")
    except Exception as e:
        print(f"[WARN] 自动启动失败，请手动运行 start.bat: {e}")

    print("[OK] 升级完成")
    return 0
