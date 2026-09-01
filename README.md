# 护眼软件（eye-protect）

Windows 下的后台护眼工具：工作时倒计时，到点弹出**软提示**（置顶、不抢焦点），可选择**立即休息**或**推迟**；宽限期内无操作自动锁屏；锁屏后强制最短休息，过短解锁会重新锁屏。所有锁/解事件写入日志，便于审计用机时间。

> 设计要点：宽限超时由**守护线程定时器**强制执行，**不依赖弹窗 UI 事件循环**——即使弹窗被忽略/失焦，到点也会锁屏。

## 功能特性

- 工作到点 → 置顶、不抢键盘焦点的休息提示弹窗（`立即休息` / `推迟N分钟` + 倒计时）
- 宽限期（默认 60 秒）内无操作 → 自动锁屏；点 `立即休息` → 立即锁屏
- 点 `推迟` 或关闭窗口 → 延迟 `postpone_minutes` 后再次提示；连续推迟达上限后强制锁屏
- 锁屏后强制最短休息（默认 20 秒），过短解锁会 1 秒后重新锁屏
- `lock_mode: hard` 可切回"到点直接锁屏"（家庭场景）
- 休息达标后自动重置推迟计数、重新开始工作计时
- 详细的按日日志，可审计

## 环境要求

- **Windows**（依赖 Win32 会话通知 `win32ts` 与 `LockWorkStation`）
- **Python 3.8+** 与 **pywin32 ≥ 306**（唯一第三方依赖）

## 快速开始（新机器）

```bash
git clone https://github.com/brdol/eye-protect.git
cd eye-protect
python -m pip install -r requirements.txt   # 安装 pywin32
python eye_protect.py                         # 首次运行会自动生成默认 config.json；Ctrl+C 退出
```

> 若 `python` 不在 PATH（如 Microsoft Store 占位符），用解释器全路径，例如 `D:\dev\miniconda\python.exe`。

按需编辑 `config.json`（见下表），再次运行即生效。

## 配置说明（`config.json`）

首次运行自动生成。所有键均可省略，缺省走代码默认值。

| 键 | 默认 | 含义 |
|---|---|---|
| `work_duration_minutes` | `20` | 工作时长（分钟），到点弹提示 |
| `min_rest_duration_seconds` | `20` | 最短休息时长（秒），不足会重新锁屏 |
| `log_dir` | `"logs"` | 日志目录（相对脚本目录） |
| `lock_mode` | `"prompt"` | `"prompt"` 软提示（办公）/ `"hard"` 到点直接锁屏（家庭） |
| `grace_seconds` | `60` | 弹窗宽限期（秒），无操作自动锁屏 |
| `postpone_minutes` | `5` | 推迟时长（分钟后再次提示） |
| `max_postpones` | `3` | 连续推迟上限，超过后强制锁屏 |
| `prompt_window_width` | `360` | 弹窗宽（像素，下限 300） |
| `prompt_window_height` | `160` | 弹窗高（像素，下限 160） |
| `prompt_font_size` | `9` | 弹窗字号（磅，DPI 感知） |
| `prompt_position` | `"top-right"` | 弹窗位置：`center`/`top-left`/`top-right`/`bottom-left`/`bottom-right`/`top-center` |

> 弹窗位置默认右上角，避免遮挡屏幕正中。`lock_mode`/`prompt_position` 大小写不敏感；数值类有下限钳制。

## 运行方式

### 直接运行（前台，可见控制台）
```bash
python eye_protect.py
```

### 开机自启动（二选一）

| 方式 | 命令 | 权限 | 运行形态 |
|---|---|---|---|
| **后台（服务）** | `python install_service.py` 或 `install_service.bat` | 需管理员 | `pythonw.exe`，无控制台窗口，登录时自动启动 |
| **前台（可见）** | `python install_service_simple.py` | 无需管理员 | `python.exe`，可见控制台窗口 |

- 后台方式用任务计划程序（`schtasks /SC ONLOGON /RL LIMITED`，**最低权限**），登录时拉起 `pythonw.exe`。
- 前台方式把启动脚本放进启动文件夹，登录时拉起 `python.exe`。
- 两种方式都会用**当前解释器 + 脚本绝对路径**重新生成启动配置，换机器重装即可。

### 卸载自启动
```bash
python uninstall_service.py          # 后台方式
python uninstall_service_simple.py  # 前台方式
```

### 停止运行中的程序
- 前台方式：在控制台按 `Ctrl+C`。
- 后台方式：任务管理器结束 `pythonw.exe`（命令行含 `eye_protect.py`）。

## 日志

- 路径：`logs/eye_protect_YYYYMMDD.log`（按日，相对脚本目录）
- 记录：工作计时、到点提示、推迟、宽限超时、锁屏/解锁、休息是否达标、强制锁屏等
- `WARNING` 级别的状态转换是主要审计线索

## 测试

测试为**普通脚本**（非 pytest），各打印 `[OK]/[FAIL]`，失败退出码非 0：

```bash
python test_logic.py          # 核心：计时、休息判定、状态转换、取消
python test_prompt.py         # 软提示状态逻辑：推迟（不足/达上限）、宽限、路由、提示期间锁屏
python test_edge_cases.py     # 配置校验（含软提示键与钳制）、日志目录、并发计时
python test_integration.py    # 完整周期模拟、压力、非法配置、计时器清理
```

> `test_edge_cases.py` 与 `test_integration.py` 会备份并改写 `config.json`，请勿与其他测试并发运行。

## 打包为 exe（可选）

```bash
pip install pyinstaller
pyinstaller --onefile --noconsole --name=EyeProtect eye_protect.py
```

## 注意事项

- 仅支持 Windows（依赖 Win32 API）。
- `python` 不在 PATH 时，用解释器全路径运行。
- 建议在系统区域设置开启 **"Beta: 使用 Unicode UTF-8 提供全球语言支持"**（设置 → 区域 → 管理 → 更改系统区域设置），可避免中文乱码；不开也能用，代码已用 `utf-8-sig` 读配置。
- 后台任务以**最低权限**运行；`LockWorkStation` 无需管理员权限。
- 锁屏/解锁事件依赖 Windows 会话通知，需在用户交互会话中运行（任务计划程序的 `ONLOGON` 已满足）。
