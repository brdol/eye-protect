# 护眼软件（eye-protect）

Windows 下的后台护眼工具：工作时倒计时，到点弹出**软提示**（置顶、不抢焦点），可选择**休息**或**推迟**；默认情况下宽限期内无操作会**强制进入休息**，勾选**免打扰**后则只跳过、不打扰。进入休息后默认显示**全屏遮罩**（不锁屏、不需要重新输密码），也可配置为锁屏。所有锁/解与休息事件写入日志，便于审计用机时间。

> 设计要点：默认**允许被打断**（宽限到点未操作即强制休息），需要时在弹窗里勾选**免打扰**临时豁免；免打扰状态在进程内保持，完成一次达标休息后自动复位。休息的落地方式与"到点是否先弹提示"是两个独立配置（`rest_style` / `lock_mode`）。弹窗与遮罩的尺寸、字号、间距全部由实测字体度量派生，跨 DPI / 多显示器自动适配。

## 功能特性

- 工作到点 → 置顶、不抢键盘焦点的休息提示弹窗（`休息` / `推迟N分钟` + 倒计时 + `免打扰`）
- 默认：宽限期（默认 60 秒）内无操作 → **强制进入休息**
- **休息方式可选**：`rest_style: "overlay"`（默认，全屏深色遮罩，**不锁屏**）/ `"lock"`（锁屏）
- 遮罩期间屏蔽键鼠（低级键盘钩子），只保留 `Ctrl+Alt+Del` 这条系统逃生通道
- 遮罩文案可从 `rest_messages` 列表随机抽取，保持简洁平静的风格
- 遮罩刚出现时只显示文案；达到 `min_rest_duration_seconds` 后才出现「结束休息」，点击即返回工作
- 勾选 `免打扰` → 宽限超时只跳过、不打扰，且豁免 `max_postpones` 上限
- 点 `推迟` 或关闭窗口 → 延迟 `postpone_minutes` 后再次提示；未开免打扰时连续推迟达上限会强制进入休息
- `lock_mode: hard` 可切回"到点不弹提示，直接进入休息"（家庭场景）
- 完成一次达标休息后，推迟计数与免打扰自动复位
- 弹窗与遮罩尺寸随内容/字号自动计算；字号按显示器**真实 PPI** 换算，同一字号在不同缩放下物理大小一致
- 支持多显示器，运行时切换缩放/分辨率会自动重排（`WM_DPICHANGED` / `WM_DISPLAYCHANGE`）
- 详细的按日日志，可审计

## 环境要求

- **Windows**（依赖 Win32 会话通知 `win32ts` 与 `LockWorkStation`）
- **Python 3.8+** 与 **pywin32 ≥ 306**（唯一第三方依赖）

## 快速开始（新机器）

```bash
git clone https://github.com/brdol/eye-protect.git
cd eye-protect
python -m pip install -r requirements.txt   # 安装 pywin32
python install_service.py                     # 安装自启动并立即后台启动
```

安装即生效：`install_service.py` 创建开机自启快捷方式，并检测/启动后台进程。
首次启动会自动从 `config.example.json` 复制生成 `config.json`（若不存在）。

> 若 `python` 不在 PATH（如 Microsoft Store 占位符），用解释器全路径，例如 `D:\dev\miniconda\python.exe`。

### 自定义配置（无需先启动一次）
```bash
copy config.example.json config.json   # 或 cp（bash）
# 编辑 config.json 改成自己的值
```
`config.json` 是本地文件（gitignored，不入库），`config.example.json` 是带说明的模板（入库）。

## 配置说明（`config.json`）

首次运行自动生成。所有键均可省略，缺省走代码默认值。

| 键 | 默认 | 含义 |
|---|---|---|
| `work_duration_minutes` | `20` | 工作时长（分钟），到点弹提示 |
| `min_rest_duration_seconds` | `20` | 最短休息时长（秒），不足会重新锁屏 |
| `log_dir` | `"logs"` | 日志目录（相对脚本目录） |
| `lock_mode` | `"prompt"` | `"prompt"` 软提示（办公）/ `"hard"` 到点直接锁屏（家庭） |
| `grace_seconds` | `60` | 弹窗宽限期（秒）。未开免打扰时到点强制锁屏；开了则只跳过 |
| `postpone_minutes` | `5` | 推迟时长（分钟后再次提示） |
| `max_postpones` | `3` | 连续推迟上限（免打扰时豁免），超过后强制进入休息 |
| `rest_style` | `"overlay"` | 休息方式：`"overlay"` 全屏遮罩（不锁屏）/ `"lock"` 锁屏 |
| `rest_messages` | 内置 8 条 | 遮罩文案列表，每次休息随机取一条；非法或为空时回退到默认列表 |
| `prompt_font_size` | `9` | 弹窗字号（磅）。按显示器真实 PPI 换算，同一字号在不同缩放下物理大小一致 |
| `prompt_position` | `"top-right"` | 弹窗位置：`center`/`top-left`/`top-right`/`bottom-left`/`bottom-right`/`top-center` |

> 弹窗**宽高由内容自动计算**，不再提供宽高配置。位置默认右上角，避免遮挡屏幕正中。`lock_mode`/`prompt_position` 大小写不敏感；数值类有下限钳制。
>
> 若某台机器上觉得字号偏大/偏小，直接调 `prompt_font_size`：它按显示器真实 PPI 换算，所以同一数值在不同屏幕上物理大小一致。

## 运行方式

### 双击运行（推荐给普通用户）
项目根目录有三个双击即用的批处理，不需要打开命令行：

| 脚本 | 作用 |
|---|---|
| `install.bat` | 安装开机自启动，并立即在后台启动（无需管理员） |
| `uninstall.bat` | 移除开机自启动 |
| `restart.bat` | 重启（让 `config.json` 改动立即生效）；未运行时就等于启动 |

它们只是薄封装，内部仍调用对应的 `*_service.py`。解释器由 `_find_python.bat` 统一解析，优先级为：

1. `EYE_PROTECT_PYTHON` 环境变量（指定完整 `python.exe` 路径）
2. `py -3` 启动器
3. **Windows 注册表 `PythonCore`**（`HKLM`/`HKCU`，标准安装与 conda 都会注册，**不依赖 PATH**）
4. PATH 中的 `python`（自动跳过 Microsoft Store 占位符）
5. 回退到 `python`

> 这解决了"终端里能用、双击却提示找不到 Python"的问题：双击继承的是 Explorer 的 PATH，可能没有 conda 的路径或先命中 Store 占位符；而注册表查询不受 PATH 影响。

> **双击时窗口不会一闪而过**：脚本会打印 `[DONE]` 或 `[FAILED] exit code N`，然后等待按键再关闭（`9009` 表示找不到 Python，并会附带提示）。从已有终端运行不会停顿；自动化场景可设置 `EYE_PROTECT_NO_PAUSE=1` 强制跳过等待。

> 若双击后提示 `Python was not found ... Microsoft Store`，说明 `python` 被 Microsoft Store 的占位符拦截了：在「设置 → 应用 → 高级应用设置 → 应用执行别名」里关闭 `python.exe` / `python3.exe` 即可（一次性，之后全系统受益）。

### 命令行方式（与双击等价）
```bash
python install_service.py     # 安装自启动（并立即后台启动）
python uninstall_service.py   # 卸载自启动
python restart_service.py     # 重启 / 应用配置
```

安装即在用户启动文件夹创建指向 `pythonw.exe` 的快捷方式（`.lnk`），登录时后台启动，**无终端窗口，全程零管理员**。安装脚本会顺带清理旧方式残留，并在未运行时**立即后台启动**（安装即生效，无需等下次登录）。

### 前台调试运行
```bash
python eye_protect.py
```
可见控制台输出；与自启动互不影响。

### 停止运行中的程序
- 任务管理器结束 `pythonw.exe`（命令行含 `eye_protect.py`）。

## 日志

- 路径：`logs/eye_protect_YYYYMMDD.log`（按日，相对脚本目录）
- 记录：工作计时、到点提示、推迟、宽限超时、锁屏/解锁、休息是否达标、强制锁屏等
- `WARNING` 级别的状态转换是主要审计线索

## 测试

测试为**普通脚本**（非 pytest），各打印 `[OK]/[FAIL]`，失败退出码非 0：

```bash
cd tests
python test_logic.py          # 核心：计时、休息判定、状态转换、取消
python test_prompt.py         # 软提示状态逻辑：推迟（不足/达上限）、宽限、路由、提示期间锁屏
python test_edge_cases.py     # 配置校验（含软提示键与钳制）、日志目录、并发计时
python test_integration.py    # 完整周期模拟、压力、非法配置、计时器清理
```

> `test_edge_cases.py` 与 `test_integration.py` 会备份并改写 `config.json`，请勿与其他测试并发运行。

## 发布版（安装包）

发布版随包携带 **Python 官方的 embeddable 运行时**，使用者**不需要安装 Python**。

> 运行时可执行文件（`python.exe` / `pythonw.exe`）由 Python Software Foundation 官方签名。发布包**不生成自定义 exe**，因此不会触发 SmartScreen 的"未知发布者"提示，也不需要购买代码签名证书。

### 安装

1. 下载 `eye-protect_<version>_windows_amd64.zip`，**解压到一个固定目录**（例如 `D:\green\EyeProtect`）
2. 双击 `install.bat`：
   - 在当前位置生成 `config.json`（如缺失）
   - 创建开机自启动（快捷方式指向 `python\pythonw.exe`，无需管理员）
   - 立即在后台启动

> 程序在解压目录原地运行，不会复制到其它位置。**安装后请勿移动该目录**；如果移动了，重新双击一次 `install.bat` 即可修复自启动路径。

### 目录结构

```
<解压目录>\
    python\                 官方 embeddable Python（含 python.exe / pythonw.exe）
    eye_protect.py          主程序
    install_service.py / uninstall_service.py / restart_service.py
    procutil.py / updater.py
    config.json             首次运行/安装时生成
    logs\                   按日日志
    README.md / LICENSE / NOTICE
    install.bat / upgrade.bat / start.bat / stop.bat / restart.bat / uninstall.bat
```

### 常用操作（双击即可）

| 脚本 | 作用 |
|---|---|
| `start.bat` / `stop.bat` / `restart.bat` | 启动 / 停止 / 重启后台进程（改完 `config.json` 用 restart） |
| `upgrade.bat` | 检查并安装最新版本（自动下载、替换、重启，**保留 config 与 logs**） |
| `uninstall.bat` | 移除开机自启动（程序与配置保留，可手动删目录） |

### 构建发布包（维护者）

```powershell
powershell -ExecutionPolicy Bypass -File build_release.ps1
# 产物：dist\eye-protect_<version>_windows_amd64.zip
```

脚本会自动下载官方 embeddable Python 3.12、把 pywin32 安装进随包运行时，并用它执行导入自检。
推送 `v*` 标签时，GitHub Actions 会自动构建并把 zip 上传到 Release。

## 注意事项

- 仅支持 Windows（依赖 Win32 API）。
- `python` 不在 PATH 时，用解释器全路径运行。
- 建议在系统区域设置开启 **"Beta: 使用 Unicode UTF-8 提供全球语言支持"**（设置 → 区域 → 管理 → 更改系统区域设置），可避免中文乱码；不开也能用，代码已用 `utf-8-sig` 读配置。
- 后台任务以**最低权限**运行；`LockWorkStation` 无需管理员权限。
- 锁屏/解锁事件依赖 Windows 会话通知，需在用户交互会话中运行（登录自启动已满足）。

## 许可证

本项目采用 **Apache License 2.0**，详见 [LICENSE](LICENSE) 与 [NOTICE](NOTICE)。

```
Copyright 2026 brd

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
```
