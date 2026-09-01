# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Windows-only eye-protection utility (护眼软件). It runs in the background, counts down a configurable work duration, then (by default) shows a **soft pre-lock prompt** — a topmost, non-focus-stealing popup with **立即休息** (rest now) and **推迟N分钟** (postpone) buttons plus a grace countdown. Inaction for the grace period or clicking 立即休息 locks the workstation; postpone (or closing the window) delays and re-prompts, up to a configurable cap after which it force-locks. After locking, it enforces a minimum rest duration — unlocking too early triggers a re-lock one second later. A `lock_mode: "hard"` config reverts to instant lock-at-timeout (home use). Lock/unlock events and timing decisions are logged to daily files for usage auditing.

Windows-only by necessity: it depends on the Win32 session-notification API (`win32ts`) and `LockWorkStation` (`ctypes.windll.user32`). The only third-party dependency is `pywin32` (>=306).

## Common Commands

### Setup & run
On the dev machine `python` is a Microsoft Store stub, not a real interpreter — use the full path `D:\dev\miniconda\python.exe` (pywin32 is in its user site-packages; reinstall with `… -m pip install pywin32` if the env is rebuilt).
```powershell
D:\dev\miniconda\python.exe -m pip install -r requirements.txt   # pywin32>=306 (only dependency)
D:\dev\miniconda\python.exe eye_protect.py                       # run the protector (Ctrl+C to exit)
```
Run elevated for reliable forced locking (per README).

### Tests
Tests are **plain scripts run directly**, not pytest/unittest. Each prints `[OK]/[FAIL]` and exits non-zero (`sys.exit(1)`) on failure — the exit code is reliable. Run from the project dir (`eye_protect` reads the relative `config.json`). Substitute the full interpreter path on the dev machine.

```bash
python test_logic.py          # core: timer, rest check, state transitions, cancellation
python test_edge_cases.py     # config validation (incl. soft-prompt keys + clamps), log-dir, concurrent timers
python test_integration.py    # full cycle sim, stress, invalid config, timer cleanup
python test_prompt.py         # soft-prompt state logic: postpone (under/at cap), grace, routing, manual-lock
python test_ctrl_c.py         # standalone message-loop + Ctrl+C probe
python test_exit.py           # launches eye_protect.py as subprocess, sends SIGINT
python test_service.py        # install/start/process/uninstall verification
```

`test_logic.py` is config-agnostic: it verifies loading by comparing the instance against `config.json`'s actual values, so it passes with any valid config. `test_prompt.py` stubs `lock_screen` and exercises the state machine with `prompt_hwnd=None` (no real window). `test_edge_cases.py` and `test_integration.py` back up `config.json` to `config.json.backup` and restore it in a `finally` block — they mutate config during the run, so don't run them concurrently. `test_service.py`, `test_exit.py`, and `test_ctrl_c.py` actually launch `eye_protect.py` (and `test_service.py` touches the Startup folder) — heavier, and can leave a background process that will lock the screen after `work_duration` minutes; run them deliberately and kill the process afterward.

### Auto-start install / uninstall (no admin, background)
- **Install:** `python install_service.py` — creates a `.lnk` shortcut to `pythonw.exe` in the user Startup folder. Fires on login, runs `pythonw.exe` (no console window, background). **No admin needed.**
- **Uninstall:** `python uninstall_service.py` — deletes the shortcut (and cleans up legacy `EyeProtector.bat` / Task Scheduler task).

### Package as exe (optional)
```bash
pip install pyinstaller
pyinstaller --onefile --noconsole --name=EyeProtect eye_protect.py
```

## Architecture

The entire runtime lives in `eye_protect.py` as a single class, `EyeProtector`. No framework — it's a Win32 message-loop application.

### States (WORKING / PROMPTING / RESTING) — all shared-state mutations on the main thread
- **WORKING**: a daemon `threading.Timer` (`work_timer`) counts down to the next prompt.
- **PROMPTING**: a modeless topmost prompt window is up; a *separate* daemon `threading.Timer` (`grace_timer`) is the authoritative timeout; a cosmetic `SetTimer` only refreshes the countdown text.
- **RESTING**: `is_resting=True`, screen locked; `on_lock`/`on_unlock` enforce the minimum rest.

### Event-driven message pump
- `run()` (main thread) registers a hidden window (`win32gui.CreateWindow`), calls `win32ts.WTSRegisterSessionNotification`, then loops `win32gui.PumpWaitingMessages()` + `time.sleep(0.1)`. This single pump drives **both** the hidden window and the prompt window.
- **The work timer's worker thread never mutates shared state** — `on_work_timeout` only `win32api.PostMessage`s a private `WM_APP` message (`WM_APP_PROMPT` in prompt mode, `WM_APP_HARD_LOCK` in hard mode) to the hidden window. `wnd_proc` handles it on the main thread → `show_prompt`/`enter_rest`. (This fixes a pre-existing race where `is_resting` was written from the worker and read from the main thread.)
- **The grace timeout is owned by the daemon `grace_timer`, not the UI.** `on_grace_expired` (worker) calls `LockWorkStation()` (thread-safe) directly and posts `WM_APP_GRACE_EXPIRED`; `on_grace_timeout` (main) tears the prompt down and enters rest. The lock fires even if the popup is hung/unfocused — this is the resilience anchor that replaces a fragile UI-internal timeout.
- `wnd_proc` dispatches `WM_WTSSESSION_CHANGE` (`WTS_SESSION_LOCK`→`on_lock`, `WTS_SESSION_UNLOCK`→`on_unlock`) and the `WM_APP_*` messages. `stop()` cancels both timers + `_teardown_prompt` and posts `WM_QUIT`.

### Prompt window (pywin32 specifics)
- The process is declared DPI-aware in `__init__` (`_set_dpi_aware` → `SetProcessDpiAwareness(2)`), so the popup is **not** system-scaled — window/font sizes are real pixels/points (earlier "too big" was 125% system scaling on a 120-DPI display).
- A second `WNDCLASS` `"EyeProtectorPromptClass"` with `prompt_wnd_proc`, registered lazily once. **`self._prompt_wc` and `self._prompt_proc_ref` are pinned on the instance** — pywin32's C ref to the proc doesn't keep the Python object alive; without this the window works once and crashes on the second prompt.
- Created modeless via `win32gui.CreateWindowEx` with `WS_EX_TOPMOST | WS_EX_NOACTIVATE | WS_EX_DLGMODALFRAME` (topmost, no focus steal, silent). **Child `Static`/`Button` controls are created directly in `show_prompt` after `CreateWindowEx`** — pywin32 does **not** synchronously dispatch `WM_CREATE`, so `WM_CREATE` is a no-op. `WM_COMMAND` (LOWORD) → `on_prompt_sleep`/`on_prompt_postpone`; `WM_CLOSE` (X) → `on_prompt_postpone` (close == postpone); `WM_TIMER` → countdown text only; `WM_CTLCOLORSTATIC` → gray bg (`COLOR_BTNFACE`) + black text (no white boxes).
- The control font is `ctypes.windll.gdi32.CreateFontW` with the configured point size converted via `GetDpiForSystem` (typeface `Microsoft YaHei`). **The returned HFONT must be masked `& 0xFFFFFFFF`** — `restype=c_void_p` reads the full 64-bit RAX whose high 32 bits are non-deterministic garbage; GDI handles are 32-bit, so masking yields the real handle (an unmasked handle intermittently fails `WM_SETFONT` → invisible text).
- `SetTimer`/`KillTimer` are **not** in `win32gui` — use `ctypes.windll.user32`. **`_teardown_prompt()` is the single idempotent exit path** (`prompt_active=False` first, cancel `grace_timer`, `KillTimer` + `DestroyWindow`); `KillTimer` before destroy is mandatory. Both window procs are wrapped in `try/except` so a stray exception can't kill the pump.
- Postpone under the cap → `start_work_timer(postpone_minutes)` (re-prompts after the short delay); at/over the cap → force-lock. A completed rest (`on_unlock` with sufficient rest) resets `postpone_count` to 0.

### Rest enforcement (core, preserved)
- `on_unlock`: if `is_resting` and `lock_time`, compare `time.time() - lock_time` to `min_rest_duration`. Below → re-lock in 1 s (now a daemon `Timer`); at/above → clear resting, reset `postpone_count`, `start_work_timer()`.
- `on_lock`: record `lock_time`; if a manual lock arrives while prompting, tear the prompt down and treat it as starting rest; if a manual lock during WORKING, cancel the work timer (pause).
- `start_work_timer(duration_minutes=None)` always cancels any existing timer first; `None` = full `work_duration`, else used for postpone.

### Config & logging
- `config.json` keys (with per-key code defaults): `work_duration_minutes` (20), `min_rest_duration_seconds` (20), `log_dir` ("logs"), `lock_mode` ("prompt" | "hard"), `grace_seconds` (60), `postpone_minutes` (5), `max_postpones` (3), `prompt_window_width` (360, px), `prompt_window_height` (160, px), `prompt_font_size` (9, points), `prompt_position` ("top-right" | "center" | "top-left" | "bottom-left" | "bottom-right" | "top-center"). A missing config file writes the defaults; missing keys fall back per-key. `lock_mode`/`prompt_position` are case-insensitive (unknown→default); `grace_seconds`/`postpone_minutes` clamp to ≥1, `max_postpones` to ≥0, font ≥4, window width ≥300/height ≥160. The reader uses `utf-8-sig`, so a UTF-8 BOM is tolerated.
- Logs to `logs/eye_protect_YYYYMMDD.log` plus **stderr** (`StreamHandler` default), via `logging.basicConfig` at INFO. WARNING-level transitions (timeout, postpone, grace expiry, lock/unlock) are the primary audit trail.

### Auto-start installer
- `install_service.py` — creates a `.lnk` shortcut (via pywin32 `win32com.client` → `WScript.Shell.CreateShortcut`) in `%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\EyeProtect.lnk`, pointing to `pythonw.exe` + `eye_protect.py`. Runs on login, background, **no admin**. Also cleans up legacy install methods (`EyeProtector.bat`, the old Task Scheduler task).
- `uninstall_service.py` — deletes the `.lnk` (+ legacy cleanup).

## Gotchas

- **Git repo on GitHub (private):** tracked in git and pushed to GitHub. `origin` is HTTPS (the office network blocks SSH port 22; git credentials via `gh auth setup-git`). `config.json`, `logs/`, `__pycache__/`, `.idea/`, `.claude/settings.local.json` are gitignored (machine-specific / generated). The auto-start `.lnk` lives in the Startup folder (outside the repo).
- **Interpreter not on PATH:** the dev machine's `python` is a Microsoft Store stub. Use `D:\dev\miniconda\python.exe`; `pywin32` lives in its user site-packages.
- **The startup bat is machine-specific.** `eye_protect_startup.bat` bakes absolute interpreter + project paths (currently `D:\dev\miniconda\python.exe` and `D:\proj\eye-protect`) — a bat copied to the Windows Startup folder must point back to the project by absolute path. `install_service_simple.py` regenerates it from `sys.executable`/`__file__`, so re-run that on a new machine rather than copying the bat. `test_service.py` resolves paths dynamically via `__file__`.
- **The prompt window can't be unit-tested directly** — it needs the live `PumpWaitingMessages` loop + a real window. `test_prompt.py` covers the state logic by stubbing `lock_screen` and driving the state methods with `prompt_hwnd=None`; the window mechanics (class registration, GC pinning, `SetTimer`/`KillTimer`) are only exercised by a manual end-to-end run (short config: `work_duration 1 / grace 15 / postpone 1 / max_postpones 2`).
- **Config/log paths are script-relative, not CWD-relative.** `eye_protect.py` locates `config.json` and `logs/` via `SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))`, NOT the process working directory. This matters because the Task Scheduler method runs with CWD = `C:\Windows\System32` (no "Start In" set) — a relative path would look in System32, fail to write (LIMITED), and crash silently before logging. Keep these paths script-relative.
- Stopping the running protector: the auto-start runs `pythonw.exe` (no console) — end it via Task Manager (`pythonw.exe`, command line contains `eye_protect.py`); for a manual foreground run, Ctrl+C in its console.
- Logs accumulate under `logs/` (gitignored, machine-specific).
