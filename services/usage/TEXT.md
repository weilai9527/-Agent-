# 评分和报告 Worker 的文字额度

`prepare_score_job`、`prepare_report_job` 已接入。调用点覆盖 CLI Worker 和争取同一任务租约的兼容 HTTP 接口。提交答案的事务独立入队，学校没额度或 usage 暂时离线，学生已提交的回答仍会保留。预算恢复后，Worker 按原队列的退避策略接手。

## 启用

- 为计量的 Web 与 Worker 副本设置 `USAGE_SERVICE_URL`、`LEGACY_SCHOOL_ID`、`SERVICE_ID` 和服务签名配置。在切换流量前启动已配置的 Worker。
- 独立评估库使用 `SERVICE_ID=assessment`。usage 的信任策略为该 caller、本校和 student 类型授予 `usage.reserve`、`usage.dispatch`、`usage.settle`。学校初始额度为 0，由具备 `usage.configure` 的管理方设置。
- 日常评估进程只使用独立评估库。即使该库首次启动时尚无 `USAGE_SERVICE_URL`，也会绑定学校和计量身份；新模型调用暂缓，已保存的学生回答和已有评分仍可查询。恢复地址及授权后，工作进程重试原任务。
- 未计量的旧逻辑只供迁移回归夹具使用。测试须在独立解释器内调用 `shared.offline_fixture.enable_offline_fixture()`，并在操作时通过临时库和进程身份复核。仅设置 `APP_ENV=test`、`legacy` 或 `shared` 不授予该许可。线上只读应急命令不运行评分任务。

## 一次 HTTP 尝试的状态

1. Worker 持当前任务租约，按任务、执行代次、HTTP 序号和请求摘要记录 `prepared`。预留 1 个文字请求单位。重试同一操作使用相同业务键。
2. Worker 持久化预留号和 `authorizing`，调用 `POST /internal/usage/reservations/{id}/begin`。usage 在学校锁内把有效预留转为 `in_flight`。此时额度仍只计入 reserved。未经 begin 的预留到期自动释放。
3. Worker 再次验证租约并提交 `dispatching` 后才发送 POST。每个供应商重试及切换都是独立尝试。HTTP 请求的 `X-Client-Request-Id` 等于日志行 ID，供查证供应商记录使用。系统不依赖供应商按此头去重。
4. 取得确定响应，先记录 `received` 再幂等结算。供应商已接受的 2xx 请求计 1，包括业务返回内容不可用的请求。确认未发送或收到明确的前置拒绝计 0。此单位用于统计文字请求，无法推导 token、货币金额或供应商实际账单。
5. Worker 用已结算的输出生成业务结果。写入评分或报告、清除日志中的临时模型输出、推进执行代次和确认任务同事务提交。发布回滚时保留输出。成功发布后，显式强制重评会开始新的计量代次。

## 故障与核对

- 额度耗尽或服务不可达时任务保持 pending。查看 `worker_text_runs.wait_reason`；`quota_exhausted` 表示学校额度用尽。报告仍在排队时附有 `generation_error` 提示。强制重评被暂缓时，兼容评分接口返回 202、job_id 和 assessment_pending，已有评价仍是此前发布的结果。
- Worker 在 begin 前后退出，接管者根据本地 `authorizing` 和相同预留号确认发送动作尚未发生，以 0 结算或确认准备期已过期，再安全地使用新预留。
- 发生读超时、部分写入、响应不确定的 5xx 或 Worker 在提交发送意图后崩溃，日志保留 `unknown` 和关联号，不继续重发或切换供应商。旧 Worker 的迟到响应只能凭原发送凭据补记一次。若供应商未提供可验证的执行回执，任务保持待核对，原账期保留该单位，used 不增加。普通排队重试不能替代供应商查证。旧共享库若要物理删除学生，请先查清并处理未结算的调用，再执行原有级联删除。
- `received` 记录可在供应商配置、题目版本发生变化后补结算。即使超过原预留 TTL 或跨月，已进入 in_flight 的记录仍按创建预留的账期结算一次。响应已保存或结算确认丢失时，接管 Worker 不再调用模型。
- 可从 `worker_text_runs` 获取任务号、执行代次、等待原因，再用 `worker_model_attempts` 的 job_id、id、reservation_id、state、outcome 和 status_code 核对 usage 账本。临时响应可能包含学生信息，只应由评估库授权人员处理。

从仓库根用 `python -m pytest -q services/usage` 复跑隔离测试。端到端脚本为 `python -m services.usage.smoke_worker_usage`，需本机 loopback 监听权限。脚本使用临时数据库、网关 cookie、本地 HTTPS 模型夹具和随机密钥。

## 本轮验收结果

本机回环验收使用独立的面试、评估、用量和 providers 配置库；旧库路径 legacy.sqlite 应始终不存在。以学校管理员网关设置实际学校额度，学生通过登录 cookie 提交训练回答并重放同一 submission_id。临时 SQLite 中仅保存一份回答。

| 步骤 | 模型夹具累计收到的 HTTPS 请求 | 账本结果 |
| --- | ---: | --- |
| 文字额度为 0，独立 Worker 尝试评分 | 0 | used 0，评分排队 |
| 提额至 1，评分成功；报告因无余量等待 | 1 | used 1 |
| 提额至 2，报告成功；重启 Worker | 2 | used 2，reserved 0 |
| 额度已用尽，经学生网关强制重评 | 2 | HTTP 202 携带任务号，前次分数保留，used 2 |

该验收通过真实网关、usage、独立评估进程与 HTTPS 测试模型通信。没有调用付费供应商，没有验证供应商金额。
