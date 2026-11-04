# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Windows-only eye-protection utility (护眼软件). It runs in the background, counts down a configurable work duration, then (by default) shows a **soft pre-lock prompt** — a topmost, non-focus-stealing popup with **休息** (rest now), **推迟N分钟** (postpone), a **免打扰** (do-not-disturb) checkbox and a grace countdown. By default inaction for the grace period force-locks; ticking 免打扰 makes timeout/delays skip without locking (and exempts the `max_postpones` cap) — a manual escape hatch for meetings, since automatic meeting detection proved unreliable. Postpone/closing the window delays and re-prompts, up to a configurable cap after which it force-locks. After locking it enforces a minimum rest duration — unlocking too early triggers a re-lock one second later. A completed rest resets both `postpone_count` and 免打扰. A `lock_mode: "hard"` config reverts to instant lock-at-timeout (home use). Lock/unlock events and timing decisions are logged to daily files for usage auditing.

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
cd tests
python test_logic.py          # core: timer, rest check, state transitions, cancellation
python test_edge_cases.py     # config validation (incl. soft-prompt keys + clamps), log-dir, concurrent timers
python test_integration.py    # full cycle sim, stress, invalid config, timer cleanup
python test_prompt.py         # soft-prompt: postpone/免打扰/grace/routing + layout metrics (no window)
python test_ctrl_c.py         # standalone message-loop + Ctrl+C probe
python test_exit.py           # launches eye_protect.py as subprocess, sends SIGINT
python test_service.py        # install/start/process/uninstall verification
```

Tests live in `tests/` and share `tests/_bootstrap.py` — it computes the project root, adds it to `sys.path`, and `os.chdir`s there, so `from eye_protect import …` works and relative `config.json` paths land at the project root (run them from the `tests/` directory). `test_logic.py` is config-agnostic (compares instance vs `config.json`'s actual values). `test_prompt.py` stubs `lock_screen` and exercises the state machine with `prompt_hwnd=None` (no real window). `test_edge_cases.py` and `test_integration.py` back up `config.json` to `config.json.backup` and restore it in a `finally` block — they mutate config during the run, so don't run them concurrently. `test_service.py`, `test_exit.py`, and `test_ctrl_c.py` actually launch `eye_protect.py` (and `test_service.py` touches the Startup folder) — heavier, and can leave a background process that will lock the screen after `work_duration` minutes; run them deliberately and kill the process afterward. Process discovery uses PowerShell/CIM because Windows 11 may not include `wmic`.

### Auto-start install / uninstall (no admin, background)
- **Install:** `python install_service.py` — creates a `.lnk` shortcut to `pythonw.exe` in the user Startup folder. Fires on login, runs `pythonw.exe` (no console window, background). **No admin needed.** After creating the shortcut it **detects whether eye_protect is already running and launches it in the background if not** (install-takes-effect-immediately).
- **Uninstall:** `python uninstall_service.py` — deletes the shortcut (and cleans up legacy `EyeProtector.bat` / Task Scheduler task).
- **Restart / apply config:** `python restart_service.py` — kills matching `eye_protect.py` instances and starts `pythonw.exe` in the background; if none is running, it acts as a start command.
- **Double-clickable launchers** (for non-CLI users): `install.bat` / `uninstall.bat` / `restart.bat` at the repo root — pure-ASCII thin wrappers that call the matching `*_service.py`. They print `[DONE]` / `[FAILED] exit code N` and **pause only when launched by Explorer** (detected via `%cmdcmdline%` containing the script name), so terminal/automation runs don't block; `EYE_PROTECT_NO_PAUSE=1` forces no pause. **Keep these files pure ASCII** — Chinese comments break cmd parsing, and use the full path to `findstr.exe` so a GNU `find` on PATH can't shadow it.
- **Python resolution lives in `_find_python.bat`** (shared by the three launchers; it sets `PY` in the caller's scope, so it must not `setlocal`). Order: `EYE_PROTECT_PYTHON` env var → `py -3` → **registry `PythonCore` InstallPath** (HKLM/HKCU/WOW6432Node, 3.x only; standard and conda installs register here, and it works **without PATH** — this is what fixes "works in terminal, not on double-click") → `where python` skipping `\WindowsApps\` → bare `python`. No hardcoded paths.
- **`procutil.py` calls PowerShell by absolute path** (`%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe`) — an Explorer-launched process may have a PATH without that directory, and a bare `powershell.exe` would silently fail the "already running" check and spawn a duplicate instance.
- **Process plumbing lives in `procutil.py`** (`find_eye_protect_pids` / `is_running` / `start_background` / `stop_pids`), shared by `install_service.py` and `restart_service.py`. It queries via PowerShell/CIM because Windows 11 may not ship `wmic`; a diverged duplicate of this logic previously made `install_service.py` spawn a second instance every run.

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
- **RESTING**: `is_resting=True`, screen locked; `on_lock`/`on_unlock` enforce the minimum rest. Reached from PROMPTING by an explicit 休息 click, by grace timeout when 免打扰 is unchecked, or by hitting the `max_postpones` cap.

### Event-driven message pump
- `run()` (main thread) registers a hidden window (`win32gui.CreateWindow`), calls `win32ts.WTSRegisterSessionNotification`, then loops `win32gui.PumpWaitingMessages()` + `time.sleep(0.1)`. This single pump drives **both** the hidden window and the prompt window.
- **The work timer's worker thread never mutates shared state** — `on_work_timeout` only `win32api.PostMessage`s a private `WM_APP` message (`WM_APP_PROMPT` in prompt mode, `WM_APP_HARD_LOCK` in hard mode) to the hidden window. `wnd_proc` handles it on the main thread → `show_prompt`/`enter_rest`. (This fixes a pre-existing race where `is_resting` was written from the worker and read from the main thread.)
- **Grace timeout depends on 免打扰.** `on_grace_expired` (worker) only posts `WM_APP_GRACE_EXPIRED`; `on_grace_timeout` (main) tears the prompt down, then: 免打扰 checked → `_postpone_without_prompt()` (skip, no lock, cap exempt); unchecked → `enter_rest()` (force-lock, the default safety net). The `grace_timer` remains a daemon thread so the decision doesn't depend on the UI event loop.
- **Watchdog:** a daemon thread watches `self._heartbeat` (updated each pump iteration); if the main thread stops pumping for >180s (wedged), it logs the error, spawns a fresh `pythonw eye_protect.py`, and `os._exit`s — self-healing so a wedged main never leaves the user without reminders.
- `wnd_proc` dispatches `WM_WTSSESSION_CHANGE` (`WTS_SESSION_LOCK`→`on_lock`, `WTS_SESSION_UNLOCK`→`on_unlock`) and the `WM_APP_*` messages. `stop()` sets `running=False` (also stops the watchdog loop), cancels both timers + `_teardown_prompt`, and posts `WM_QUIT`.

### Prompt window (pywin32 specifics)
- The process is declared **Per-Monitor V2** DPI-aware in `__init__` (`_set_dpi_aware` → `SetProcessDpiAwarenessContext(-4)`, falling back to `SetProcessDpiAwareness(2)` / `SetProcessDPIAware`).
- A second `WNDCLASS` `"EyeProtectorPromptClass"` with `prompt_wnd_proc`, registered lazily once. **`self._prompt_wc` and `self._prompt_proc_ref` are pinned on the instance** — pywin32's C ref to the proc doesn't keep the Python object alive; without this the window works once and crashes on the second prompt.
- Created modeless via `win32gui.CreateWindowEx` with `WS_EX_TOPMOST | WS_EX_NOACTIVATE | WS_EX_DLGMODALFRAME` (topmost, no focus steal, silent). **Child `Static`/`Button` controls are created directly in `show_prompt` after `CreateWindowEx`** — pywin32 does **not** synchronously dispatch `WM_CREATE`, so `WM_CREATE` is a no-op. `WM_COMMAND` (LOWORD) → `IDB_SLEEP`/`IDB_POSTPONE`/`IDC_DND`; `WM_CLOSE` (X) → `on_prompt_postpone` (close == postpone); `WM_TIMER` → countdown text only; `WM_CTLCOLORSTATIC`/`WM_CTLCOLORBTN` → gray bg (`COLOR_BTNFACE`) + black text (no white boxes).
- **Layout is content-driven and purely proportional.** `_measure_prompt_layout(dpi)` measures the real text with `GetTextExtentPoint32W`, derives every margin/gap/row height/button size as a fraction of the measured font height `fh` (no absolute pixel constants; only `max(1, …)` guards), then converts the client size to a window size with `AdjustWindowRectExForDpi`. The two buttons are **equal width** (based on the longer label). Window size is never configured by the user.
- The control font is `ctypes.windll.gdi32.CreateFontW` (typeface `Microsoft YaHei`). Point→pixel conversion uses the monitor's **raw PPI** (`GetDpiForMonitor(MDT_RAW_DPI)`, clamped to 60–400, falling back to effective DPI when EDID is implausible), so the same `prompt_font_size` renders the same **physical** size regardless of Windows scaling. **The returned HFONT must be masked `& 0xFFFFFFFF`** — `restype=c_void_p` reads the full 64-bit RAX whose high 32 bits are non-deterministic garbage; GDI handles are 32-bit, so masking yields the real handle (an unmasked handle intermittently fails `WM_SETFONT` → invisible text).
- **Live display changes are handled:** `WM_DPICHANGED` (scaling / moving to another monitor) rebuilds the font, recomputes the layout and recreates the child controls; `WM_DISPLAYCHANGE` (resolution-only change, same DPI) repositions the window into the new work area. The window is placed on the monitor under the cursor (`MonitorFromPoint`) at creation, and on the window's own monitor (`MonitorFromWindow`) afterwards.
- `SetTimer`/`KillTimer` are **not** in `win32gui` — use `ctypes.windll.user32`. **`_teardown_prompt()` is the single idempotent exit path** (`prompt_active=False` first, cancel `grace_timer`, `KillTimer` + `DestroyWindow`); `KillTimer` before destroy is mandatory. Both window procs are wrapped in `try/except` so a stray exception can't kill the pump.
- **One shared skip path:** `_postpone_without_prompt()` is used by both the 推迟 button/X-close (`on_prompt_postpone`) and the grace timeout when 免打扰 is checked (`on_grace_timeout`). With 免打扰 checked it skips without touching `postpone_count` and never force-locks; otherwise under the cap → `start_work_timer(postpone_minutes)` (re-prompts after the short delay), at/over the cap → force-lock. A completed rest (`on_unlock` with sufficient rest) resets `postpone_count` and `dnd_mode`.

### Rest enforcement (core, preserved)
- `on_unlock`: if `is_resting` and `lock_time`, compare `time.time() - lock_time` to `min_rest_duration`. Below → re-lock in 1 s (a daemon `Timer`); at/above → clear resting, reset `postpone_count` **and `dnd_mode`**, `start_work_timer()`.
- `on_lock`: record `lock_time`; if a manual lock arrives while prompting, tear the prompt down and treat it as starting rest; if a manual lock during WORKING, cancel the work timer (pause).
- `start_work_timer(duration_minutes=None)` always cancels any existing timer first; `None` = full `work_duration`, else used for postpone.

### Config & logging
- Config: `config.json` is **local-only** (gitignored). `config.example.json` is the tracked template. On first run, if `config.json` is missing it's copied from `config.example.json` (falling back to code defaults if the example is also absent). To customize without running first: `copy config.example.json config.json` then edit. `config.json` keys (with per-key code defaults): `work_duration_minutes` (20), `min_rest_duration_seconds` (20), `log_dir` ("logs"), `lock_mode` ("prompt" | "hard"), `grace_seconds` (60), `postpone_minutes` (5), `max_postpones` (3), `prompt_font_size` (9, points), `prompt_position` ("top-right" | "center" | "top-left" | "bottom-left" | "bottom-right" | "top-center"). `prompt_window_width/height` are **obsolete and ignored** (window size is content-driven) — old configs still load. A missing config file writes the defaults; missing keys fall back per-key. `lock_mode`/`prompt_position` are case-insensitive (unknown→default); `grace_seconds`/`postpone_minutes` clamp to ≥1, `max_postpones` to ≥0, font ≥4. The reader uses `utf-8-sig`, so a UTF-8 BOM is tolerated.
- Logs to `logs/eye_protect_YYYYMMDD.log` plus **stderr** (`StreamHandler` default), via `logging.basicConfig` at INFO. WARNING-level transitions (timeout, postpone, grace expiry, lock/unlock) are the primary audit trail.

### Auto-start installer
- `install_service.py` — creates a `.lnk` shortcut (via pywin32 `win32com.client` → `WScript.Shell.CreateShortcut`) in `%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\EyeProtect.lnk`, pointing to `pythonw.exe` + `eye_protect.py`. Runs on login, background, **no admin**. Also cleans up legacy install methods (`EyeProtector.bat`, the old Task Scheduler task).
- `uninstall_service.py` — deletes the `.lnk` (+ legacy cleanup).

## Gotchas

- **Git repo on GitHub (private):** tracked in git and pushed to GitHub. `origin` is HTTPS (the office network blocks SSH port 22; git credentials via `gh auth setup-git`). `config.json`, `logs/`, `__pycache__/`, `.idea/`, `.claude/settings.local.json` are gitignored (machine-specific / generated). The auto-start `.lnk` lives in the Startup folder (outside the repo).
- **Interpreter not on PATH:** the dev machine's `python` is a Microsoft Store stub. Use `D:\dev\miniconda\python.exe`; `pywin32` lives in its user site-packages.
- **Auto-start is a `.lnk`, not a bat.** `install_service.py` writes `EyeProtect.lnk` into the user Startup folder with absolute interpreter + script paths, so there is no generated bat to keep in sync. The `.lnk` lives outside the repo and must be re-created on a new machine by re-running `install_service.py`.
- **The prompt window can't be unit-tested directly** — it needs the live `PumpWaitingMessages` loop + a real window. `test_prompt.py` covers the state logic (stubbing `lock_screen`, `prompt_hwnd=None`) **and** the layout math (`_measure_prompt_layout` against a real GDI font, no window needed). The window mechanics (class registration, GC pinning, `SetTimer`/`KillTimer`, live `WM_DPICHANGED`/`WM_DISPLAYCHANGE`) are only exercised by a manual end-to-end run.
- **Config/log paths are script-relative, not CWD-relative.** `eye_protect.py` locates `config.json` and `logs/` via `SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))`, NOT the process working directory — launchers (shortcut, scheduled task, bat) may start it with an arbitrary CWD. Keep these paths script-relative.
- Stopping the running protector: the auto-start runs `pythonw.exe` (no console) — end it via Task Manager (`pythonw.exe`, command line contains `eye_protect.py`); for a manual foreground run, Ctrl+C in its console.
- Logs accumulate under `logs/` (gitignored, machine-specific).
