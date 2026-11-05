"""离线兼容导入，保留原模块的公共函数和测试注入点。"""
import sys
from services.career import feed

sys.modules[__name__] = feed
