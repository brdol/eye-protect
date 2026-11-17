"""在线升级：查询 GitHub Release、下载、解压，并生成替换脚本完成自更新。

Windows 不允许覆盖正在运行的 exe 及其 _internal 目录，因此下载完成后会生成一个
临时 .bat：它等待当前进程退出，再用 robocopy 覆盖程序文件（保留 config.json 与 logs），
最后启动新版本。
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.request

REPO = "brdol/eye-protect"
API_LATEST = f"https://api.github.com/repos/{REPO}/releases/latest"
ASSET_SUFFIX = "windows_amd64.zip"
USER_AGENT = "EyeProtect-Updater"
HTTP_TIMEOUT = 30


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


def _http_json(url):
    req = urllib.request.Request(url, headers={
        "Accept": "application/vnd.github+json",
        "User-Agent": USER_AGENT,
    })
    with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as r:
        return json.load(r)


def _download(url, dest):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as r, open(dest, "wb") as f:
        shutil.copyfileobj(r, f)


def _find_new_root(extract_dir):
    """返回解压目录中包含 EyeProtect.exe 的那一层。"""
    for root, _dirs, files in os.walk(extract_dir):
        if "EyeProtect.exe" in files:
            return root
    return None


def _write_apply_script(tmp_dir, new_root, install_dir):
    """生成替换脚本：等待本进程退出 → 覆盖程序文件 → 启动新版本。"""
    sys32 = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32")
    tasklist = os.path.join(sys32, "tasklist.exe")
    findstr = os.path.join(sys32, "findstr.exe")
    timeout = os.path.join(sys32, "timeout.exe")
    robocopy = os.path.join(sys32, "robocopy.exe")
    exe = os.path.join(install_dir, "EyeProtect.exe")
    logs = os.path.join(install_dir, "logs")
    cfg = os.path.join(install_dir, "config.json")

    lines = [
        "@echo off",
        "setlocal",
        ":wait",
        f'"{tasklist}" /FI "PID eq {os.getpid()}" 2>nul | "{findstr}" /i "EyeProtect.exe" >nul',
        "if not errorlevel 1 (",
        f'  "{timeout}" /t 1 /nobreak >nul',
        "  goto wait",
        ")",
        f'"{robocopy}" "{new_root}" "{install_dir}" /MIR /XD "{logs}" /XF "{cfg}" >nul',
        f'start "" "{exe}"',
        'del "%~f0"',
    ]
    bat = os.path.join(tmp_dir, "apply_update.bat")
    with open(bat, "w", encoding="ascii", errors="replace") as f:
        f.write("\r\n".join(lines) + "\r\n")
    return bat


def run_upgrade(current_version):
    """执行在线升级。返回进程退出码。"""
    if not getattr(sys, "frozen", False):
        print("[FAIL] 在线升级仅适用于打包后的 EyeProtect.exe")
        return 1

    install_dir = os.path.dirname(os.path.abspath(sys.executable))
    print(f"当前版本: {current_version}")
    print("正在检查最新版本...")
    try:
        info = _http_json(API_LATEST)
    except Exception as e:
        print(f"[FAIL] 无法访问 GitHub: {e}")
        print("       可手动打开 https://github.com/brdol/eye-protect/releases 下载")
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
        print("[FAIL] 更新包中未找到 EyeProtect.exe")
        return 1

    # 停止除自己以外的实例
    try:
        import procutil
        others = [p for p in procutil.find_eye_protect_pids() if p != os.getpid()]
        if others:
            procutil.stop_pids(others)
    except Exception as e:
        print(f"[WARN] 停止旧实例失败，替换时可能失败: {e}")

    bat = _write_apply_script(tmp_dir, new_root, install_dir)
    print("即将替换文件并重启...")
    subprocess.Popen(
        ["cmd.exe", "/c", bat],
        creationflags=(getattr(subprocess, "CREATE_NO_WINDOW", 0)
                       | getattr(subprocess, "DETACHED_PROCESS", 0)),
        close_fds=True,
    )
    return 0
