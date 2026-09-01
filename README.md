# 护眼软件

强制休息提醒工具，帮助开发者保护视力。

## 功能特性

- 工作时长达到设定时间（默认20分钟）后自动强制锁屏
- 休息时长必须达到最短时间（默认20秒），否则重新计时并再次锁屏
- 详细的日志记录，可审计电脑使用时间
- 配置文件可自定义时间参数

## 安装依赖

```bash
pip install -r requirements.txt
```

## 配置说明

编辑 `config.json` 文件：

```json
{
    "work_duration_minutes": 20,        // 工作时长（分钟）
    "min_rest_duration_seconds": 20,    // 最短休息时长（秒）
    "log_dir": "logs"                   // 日志目录
}
```

## 运行

```bash
python eye_protect.py
```

## 打包成exe（可选）

```bash
pip install pyinstaller
pyinstaller --onefile --noconsole --name=EyeProtect eye_protect.py
```

生成的exe文件在 `dist` 目录下。

## 日志说明

日志文件按日期存储在 `logs` 目录下，格式为 `eye_protect_YYYYMMDD.log`

记录内容包括：
- 程序启动/退出
- 锁屏/解锁事件
- 工作计时开始/结束
- 休息时长检查
- 强制锁屏操作

## 开机自启动（推荐）

### 方式1: 自动安装（推荐）

运行安装脚本，自动配置为开机启动：

```bash
# 右键点击，选择"以管理员身份运行"
install_service.bat

# 或者在命令行中运行
python install_service.py
```

安装后，每次开机登录时会自动启动护眼软件。

### 方式2: 手动配置

1. 按 `Win + R` 打开运行
2. 输入 `shell:startup` 打开启动文件夹
3. 创建 `run.bat` 的快捷方式放入该文件夹

### 卸载自动启动

```bash
python uninstall_service.py
```

## 注意事项

- 需要管理员权限运行以确保能够强制锁屏
- 程序会在后台持续运行，可通过任务管理器结束进程
- 建议根据个人习惯调整配置参数
