# 模型供应商控制服务

在仓库根目录运行 `uvicorn services.providers.app:app --host 127.0.0.1 --port 8112`。部署使用服务身份 `providers` 和独立的 `PROVIDERS_DB_ENGINE`、`PROVIDERS_SQLITE_PATH` 或 `PROVIDERS_MYSQL_*`。启动先校验正常模式，明确拒绝旧身份模式及共享评估库模式，随后才打开专库并安装配置表。数据库配置缺失会使启动失败。正式环境将签名身份、可信策略、SQL 账号和供应商凭据分别注入对应的服务进程。

## 权限与契约

| 方法与路径 | scope | 行为 |
|---|---|---|
| GET /settings | providers.read | 返回公开模型参数、控制面可用标识和密钥是否配置的布尔值 |
| PATCH /settings | providers.configure | 修改明确列出的公开字段；凭据、任意跳转地址及未授权的工作空间均不能写入 |
| POST /diagnostics | providers.diagnose | 使用固定合成问题，对每个已配置且获准的报告供应商至多进行一次实际 HTTPS 调用 |
| GET /internal/runtime-settings | providers.runtime.read | 推理工作负载读取获准的字段；按调用方及平台身份绑定，响应禁止代理缓存 |

前三项权限仅授予控制面信任策略中的管理网关。其委派身份还须同时满足学校声明为 `platform`、角色为 `admin`、操作人 ID 在部署变量 `PROVIDER_PLATFORM_ADMIN_IDS` 中。普通学校管理员和推理机器身份不能修改全局出站配置。管理端只看到密钥是否存在。诊断不会发送学生资料，不记入学校训练配额；供应商可能按诊断请求计费。未配置可测试的供应商时返回 503。已配置但外部请求失败时，逐供应商返回 error，不重试，不跟随重定向。

只读机器接口验证签名、audience、动作和 `school_id=platform`，要求 `actor_type=system` 且 `actor_id=caller`。profile、career、interview、assessment、media 各自只获得许可范围内已持久化的公开配置。其他服务不持有模型配置库账号。消费者配置 `PROVIDERS_SERVICE_URL` 后，使用本地部署授予的 HTTPS 地址名单重新校验投影；供应商凭据始终由工作负载单独注入。

## 故障与兼容

消费者缺少控制面地址、签名授权失败、收到其他工作负载的参数、出站地址未获授权或读取失败时，停止相应的模型操作。成功投影最多缓存三秒。缓存到期后控制服务不可用会返回 503。短时负缓存限制在故障期间的重复请求。已验证的投影仅覆盖相应部署默认值，失败时不会读取旧 SQL 或改用本地静态配置发起新的请求。

旧 `backend.src.provider_diagnostics` 仅供在解释器内显式启用的合成数据夹具兼容。旧 CLI 只接受 `--config-only`；付费诊断由新服务验权。仅设置 `APP_ENV=test` 不能启用离线模式。只读应急入口不开放模型设置写入或付费诊断。

## 验证

`python -m pytest -q services/providers tests/security/test_provider_runtime.py admin_backend/tests/test_model_settings.py`

测试使用临时 SQLite、公私钥、独立进程启动验证和可控的 HTTP 传输。覆盖正常入口不导入旧应用、跨校/跨角色拒绝、缺少专库、失联及缓存到期、诊断权限和重定向。测试不访问真实模型账户。
