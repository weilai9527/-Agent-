"""管理网关只装配原生服务；错误配置必须在加载业务模块前被拒绝。"""
from shared.runtime_mode import require_native_runtime

require_native_runtime()

from .native_admin import create_app

app = create_app()
