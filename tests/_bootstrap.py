"""测试公共引导：定位项目根、加入 sys.path、切换 CWD 到项目根。

各测试文件首行 `from _bootstrap import *` 即可：
- `from eye_protect import ...` 能找到根目录的 eye_protect.py；
- 测试里裸写的 "config.json" 相对路径会落在项目根（与 eye_protect.py 一致）。
"""
import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)
os.chdir(PROJECT_ROOT)
