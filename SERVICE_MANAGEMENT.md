# 护眼软件管理命令

## 安装自动启动
```bash
# 右键以管理员身份运行
install_service.bat

# 或命令行
python install_service.py
```

## 卸载自动启动
```bash
python uninstall_service.py
```

## 查看任务状态
```bash
schtasks /Query /TN "EyeProtector"
```

## 手动启动任务
```bash
schtasks /Run /TN "EyeProtector"
```

## 停止运行中的程序
- 打开任务管理器
- 找到 python.exe 进程（命令行包含 eye_protect.py）
- 结束进程

## 查看任务详情
1. 按 Win+R，输入 `taskschd.msc`
2. 打开"任务计划程序库"
3. 找到 "EyeProtector" 任务

## 注意事项
- 安装需要管理员权限
- 任务会在用户登录时自动启动
- 程序以最低权限（普通用户）运行；LockWorkStation 锁屏无需管理员
- 卸载后需要重启才能完全停止自动启动
