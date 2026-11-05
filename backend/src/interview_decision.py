"""旧导入名映射到原生实现，避免测试补丁或历史调用方使用第二份实现。"""
import sys
from services.interview import decision

sys.modules[__name__] = decision
