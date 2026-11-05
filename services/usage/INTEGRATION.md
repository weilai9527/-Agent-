# 学校用量服务

从仓库根运行 `uvicorn services.usage.app:app`。对内使用 `SERVICE_ID=usage`、受信公钥和 `SERVICE_TRUST_POLICY`，以及 `USAGE_DB_ENGINE=sqlite`、绝对文件路径 `USAGE_SQLITE_PATH`，或独立 MySQL 库的 `USAGE_MYSQL_*`。启动时创建表，MySQL 使用 InnoDB。每个请求都需要受信服务针对 audience `usage` 签发的短时凭据。仅授予调用方所需的下列 scope。学校、主体、主体类型和服务身份均取自验签凭据，不接受客户端自报的学校。

| 方法与路径 | Scope | 请求和结果 |
| --- | --- | --- |
| PUT /internal/usage/quota | usage.configure | 仅 admin/system，设置当前学校的月度上限，如 `{"text":10000,"media":360000}`。返回本月两个资源的 limit、used、reserved、available。 |
| GET /internal/usage/quota | usage.read | 仅 admin/system，返回同样的本月统计。未配置的学校两项上限均为 0。 |
| POST /internal/usage/reservations | usage.reserve | 如 `{"request_id":"turn-15-llm","resource":"text","units":1,"ttl_seconds":90}`。TTL 整数 1–3600，默认 120 秒。配额充足返回 200，否则 429。 |
| POST /internal/usage/reservations/{reservation_id}/begin | usage.dispatch | 学生的单单位文字操作。Worker 在派发前将有效预留置为 in_flight。重放不会扣费，已结算或已过期且未获派发授权的预留返回 409。 |
| POST /internal/usage/reservations/{reservation_id}/settle | usage.settle | 如 `{"actual_units":1}`。实际用量可为 0，不能超过预留。成功返回 200。 |

预留和结算的成功响应含 `reservation_id,resource,units,actual_units,state,expires_at`。expires_at 是 Unix 秒，state 为 reserved、in_flight、settled 或 expired。预留重试必须使用完全相同的请求参数、学校、主体、主体类型、调用服务和 request_id。原样重试返回原预留的当前状态，参数变化返回 409。评分/报告 Worker 只有在有效租期内获准 begin 并确认派发租约后，才可开始外部调用；同一回合重发需由调用方工作流另行去重，禁止重复调用供应商。同一结算重复提交返回原结果，冲突金额或已过期的普通预留返回 409；in_flight 允许在取得确定回执后跨 TTL 结算。其他主体、类型、学校或服务读取/结算猜测的预留号返回 404。

text 单位为一次模型文字请求；media 单位为一次受控媒体操作准入，每次申请执行一项操作预留 1，确认发放后结算 1。它记录授权发放次数，计算 RTC 时长费用需要提供商的实际使用时长数据。学校预算自每个 UTC 自然月重置，跨月预留始终计入创建月。下调上限不撤销有效预留，超限期间不再批准新预留。未获派发授权的预留在数据库时间到达 expires_at 时自动退出计算；in_flight 保持占用，直到有确定结果可结算，无需定时任务。已过期的 request_id 不会自动建立新预留。

评分/报告 Worker 已在每次实际模型 HTTP 尝试处执行预留、派发确认和结算。云服务接收结果不明时保留原预留，暂停向供应商重发，等待核对。部署身份、事务和恢复细节见 [评分和报告文字配额](TEXT.md)。

超额响应形如 `{"detail":{"code":"quota_exhausted","resource":"media","fallback":"text"}}`。媒体不可用时释放确定未使用的媒体预留，界面展示文字输入，文字模型执行前仍需独立预留 text。text 超额时返回 `fallback:"deferred"`，调用方应保存已提交的文字，展示“学校文字额度已用尽，待恢复后处理”，不生成模型答复或完成标记。跨服务代理可能将错误详情收敛为字符串，调用方仍可根据 429 和自己请求的资源确定降级策略。提供商能力或角色权限仍由媒体服务控制。
