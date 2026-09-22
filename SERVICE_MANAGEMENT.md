# 护眼软件管理命令

## 安装开机自启动（无需管理员，后台运行）
```bash
python install_service.py
```
在用户启动文件夹创建指向 `pythonw.exe` 的快捷方式（.lnk），登录时后台启动，无终端窗口，全程零管理员。安装脚本会顺带清理旧方式（旧 `EyeProtector.bat`、旧任务计划程序任务）。

## 卸载开机自启动
```bash
python uninstall_service.py
```
删除快捷方式，并清理旧方式残留。

## 查看自启动项
- 任务管理器 → 启动应用 → 找 `EyeProtect`
- 或资源管理器地址栏输入 `shell:startup`，可见 `EyeProtect.lnk`（右键属性可看目标）

## 重启 / 应用配置
```bash
python restart_service.py
```
结束所有命令行匹配本项目 `eye_protect.py` 的旧实例，再用 `pythonw.exe` 后台启动新实例。没有运行中的实例时，它就是启动命令；修改 `config.json` 后运行即可立即生效。无需管理员、无终端窗口。

## 停止运行中的程序
- 任务管理器 → 结束 `pythonw.exe`（命令行含 `eye_protect.py`）

## 手动启动（后台）
双击 `EyeProtect.lnk`，或：
```bash
pythonw eye_protect.py
```

## 注意事项
- 全程无需管理员权限；`LockWorkStation` 锁屏也不需要管理员。
- 若 `python` 不在 PATH，用解释器全路径运行安装脚本，例如：
  `D:\dev\miniconda\python.exe install_service.py`
- 自启动项若在“任务管理器 → 启动”里被禁用则不生效，自行启用即可。
- 想要**前台可见控制台**（便于直接看输出）调试时，直接 `python eye_protect.py` 运行即可，与自启动互不影响。
