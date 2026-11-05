# 面试、评估和持久 Worker

面试服务负责场次、面试官、轮次和回答。评估服务从事务内登记的消息读取冻结证据，独立写入评分和报告。两套进程不装载旧学生 Web 应用。

## 正常运行

- 面试 API 和投递进程使用 `SERVICE_ID=interview` 与 `INTERVIEW_DB_ENGINE`，二者指向同一面试专库。SQLite 使用绝对路径 `INTERVIEW_SQLITE_PATH`，MySQL 使用 `INTERVIEW_MYSQL_*` 专有连接配置。
- 评估 API 和评分进程使用 `SERVICE_ID=assessment` 与 `ASSESSMENT_DB_ENGINE`，独占评估库。两域均绑定 `LEGACY_SCHOOL_ID`。名称沿用历史部署配置，校验依据是各专库的归属标记。
- 使用 `python -m deploy.run_service interview`、`assessment`、`interview-events` 和 `assessment-jobs` 四个入口分别启动。面试进程只消费 project、train_complete 和 media_close，评估进程只消费 score、report 和 analytics。
- 学生身份通过 identity 校验，面试库不创建登录账号。档案服务通过签名授权提供冻结快照；历史面试保留创建时的上下文。评分需要独立的用量服务授权。
- 停写后在只读源副本上执行 `python -m services.interview.migration --school 学校标识 --source-sqlite /绝对路径/旧库.sqlite`；MySQL 源使用仅 SELECT 的 `INTERVIEW_SOURCE_DB_ENGINE=mysql` 与 `INTERVIEW_SOURCE_MYSQL_*`。新库连接仍由 `INTERVIEW_*` 提供。导入会校验同校绑定、历史编号和快照摘要；首次导入仅允许空业务库，重复导入同一快照不产生新记录。新写入开启前核对两域收件水位与审批版本。

## 网关路由

浏览器继续使用既有 URL。网关验证真实 session 并针对每个动作签发短期令牌。下表以 `/api/interviews` 为前缀，空后缀表示该路径本身，`{id}` 表示面试 ID。所有学生操作同时核对签名学校和库中归属。

| 路由 | scope |
| --- | --- |
| GET 空后缀、/{id}、/{id}/agents、/{id}/messages | interview.read |
| POST 空后缀 | interview.create |
| PATCH /{id} | interview.update |
| POST /training-attempts/{attempt_id} | interview.training.start |
| POST /{id}/start、/{id}/finish | interview.start、interview.finish |
| POST /{id}/opening-question、/{id}/current-question、/{id}/follow-up | interview.question.open、interview.question.current、interview.question.followup |
| POST /{id}/turns、/{id}/turns/{submission_id}/spoken-question | interview.turn.submit、interview.turn.spoken |
| POST /{id}/agents、PATCH /{id}/agents/{agent_id}、POST /{id}/messages | interview.agent.create、interview.agent.update、interview.message.create |

教学尝试分配成功后，学生入口用 `attempt_id` 调 `POST /api/interviews/training-attempts/{attempt_id}`，成功后进入返回的 `interview_id`。该端点回查 `TRAINING_SERVICE_URL`，委派学生执行 `training.verify`。题目、顺序与原题 ID 都来自这次查证。服务将可跨班次复用的原题 ID 与本次面试消息 ID 分开存储。客户端用 `question.id` 提交，重复提交复用同一 `submission_id`。训练使用冻结的问题，答完才能结束。普通练习沿用已有面试官决策。

## 写入和恢复

- 接收回合、更新当前题、保存答案、插入评分任务在同一事务提交。兼容的消息 API 也在答案写入时登记任务。单题评分始终截取该答案提交前的对话。浏览器无需额外 POST 评分。
- 结束状态、queued 报告、报告任务和有绑定的教学完成事件一起提交。Web 进程可在响应后尝试领取报告任务。独立 Worker 会回收过期租约，并在启动时补登记升级前留下的 queued 占位。按答案/证据版本去重，执行外部请求时不持数据库锁，写结果和确认任务时重新校验租约与证据。真实外部调用可能因超时或进程退出而重复。
- 当任一单题补评成功，报告按新证据重算。一个版本的临时本地降级报告可在模型恢复后升级，已产生复核或教师调整的版本受保护。生成失败采用退避。用数据库时间检查到期任务，`interview_jobs.state`、`attempts`、`ready_at` 和 `last_error` 可用于排查积压。GET 面试报告的 `assessment_pending` 表示还有未完成的评分或报告任务。
- 对教学面试，结束事件通过 `TRAINING_SERVICE_URL` 发送，授予 interview 的 system 身份 `training.complete`。报告及教师改分版本通过 `ANALYTICS_SERVICE_URL` 发送，授予 assessment 的 system 身份 `analytics.completion.write`。须收到该教学尝试的完成回执后才发送分析事件。每次重试复用相同事件 ID 和原始负载。
- 历史生成版本、教师权限、版本化复核及证书查证契约见 [评估服务](../assessment/INTEGRATION.md)。旧管理端的报告复核写入必须通过 assessment。部署时将网关的 `INTERVIEW_SERVICE_URL` 和 `ASSESSMENT_SERVICE_URL` 指向对应服务。

## 离线回归

```sh
python -m pytest -q services/interview services/assessment
```

这些测试使用临时 SQLite，签名用测试密钥，模型和教学 HTTP 调用使用本地替身。包括一次提交后立即退出的进程和另一个恢复旧报告的进程。实际模型、RTC、生产 MySQL 和跨主机部署需另外验证。

原生管理网关的 `GET/PUT /api/admin/interviewer-policy` 由面试服务处理。身份域要求当前账号为具有全校管理范围并获授 `interview.policy.manage` 的管理员；面试服务只接受管理网关在本校委派的该动作。GET 返回当前配置、选项和 revision，PUT 提交 policy 及 expected_revision。并发修改返回 409，成功修改在同一事务中保留操作者与修改前后的摘要。面试建立时冻结当时策略，已有面试继续使用原快照。

原生管理页“面试官模板”向管理网关 `GET /api/admin/agent-templates` 查询。为获准职员授予 `interview.templates.read`，调用链为 admin-gateway → interview（teacher/admin 同名 scope）以及 interview → identity（teacher/admin 的 `identity.records.scope`）。返回的使用次数来自实际面试实例。读取具体使用明细时还必须拥有 `interview.records.read`。统计按实时授权名册分批聚合，使用学生标识的精确匹配；切换学校或移除班级后原会话不能查看已失去权限的数据。
