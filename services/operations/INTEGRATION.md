# 原生 RTC 诊断与平台安全审计

网关、面试服务和诊断服务使用各自的进程身份、签名密钥和访问范围。学校的日常日志检索通过 `operations` 的独立数据库完成。旧库仅在显式执行离线迁移命令时打开。

## 启动

`python -m deploy.run_service operations` 以 `SERVICE_ID=operations` 在本机 8114 端口提供内部 HTTP 服务。SQLite 配置 `OPERATIONS_DB_ENGINE=sqlite` 和绝对路径 `OPERATIONS_SQLITE_PATH`；MySQL 使用 `OPERATIONS_DB_ENGINE=mysql` 及单独的 `OPERATIONS_MYSQL_{HOST,PORT,DATABASE,USER,PASSWORD,SSL_CA}`。目标库须独立，MySQL 启动时逐列检查学校、主体、事件和资源编号的二进制排序规则。

学生、管理网关均设置 `OPERATIONS_SERVICE_URL` 和绝对路径 `OPERATIONS_JOURNAL_DIR`，将后者挂载到持久卷，重启时继续使用原卷。生产模式下任一配置缺失即拒绝启动。每个网关先将脱敏审计写入仅进程所有者可读的临时文件，落盘后原子重命名再异步转签投递。服务断线时退避重试，只有收到匹配的确认编号才移除本地文件。队列记录按学校及入口隔离。监控持久卷容量、最老待发文件年龄、`operations.journal.*` 与 `security.audit_persist_failed` 错误。诊断事件在业务响应结束后的审计阶段记录，需配合各业务域事务内的成绩、签发等变更记录使用。

面试服务配置 `OPERATIONS_SERVICE_URL`，诊断服务配置 `IDENTITY_SERVICE_URL`。每个调用方还需配置服务签名参数；接收方 `SERVICE_TRUST_POLICY` 只授予部署范围内的学校、角色与下列动作。

| 调用方 | 接收方 | 角色与允许动作 |
|---|---|---|
| student-gateway、admin-gateway | operations | system，主体等于网关名称，operations.audit.append |
| student-gateway | interview | student，interview.diagnostics.read / interview.diagnostics.write |
| interview | operations | student，operations.rtc.self / operations.rtc.append |
| admin-gateway | operations | teacher/admin，operations.rtc.read；admin，operations.audit.read |
| operations | identity | teacher/admin，identity.operations.scope |

## 人员权限与可见范围

- 学生的 `GET/POST /api/interviews/{id}/webrtc-events` 保持旧地址，面试服务负责校验学校、面试和学生三者归属，然后转给诊断服务。每个受信调用的载荷只含受控事件类型、级别、供应商别名、状态和匿名会话摘要。原始会话号、SDP、供应商报文、答题文本、自由文本消息和任意元数据不入诊断库。
- 学校管理端“连接日志”读取 `/api/admin/connection-logs`。教职员需要 `operations.rtc.read`，原有 `viewConnectionLogs` 只映射这一项。服务每次请求从身份域重查当前任课班级及学生，不接受前端提交的名单。可按姓名/学号/学生编号、面试编号和级别查询。跨多页名册时先翻完当前学生页事件，再用“下一页学生”继续；调班和撤权后旧游标也要重新授权。
- 学校管理端“安全审计”读取 `/api/admin/security-logs`。学校全域管理员还需单独获得 `operations.audit.read`；历史身份域的 `audit.read` 不自动升级。具备相同动作的真实 `platform` 学校管理员，其账号还必须列入诊断服务 `OPERATIONS_PLATFORM_ADMIN_IDS` 才可选择其他学校或查平台全局记录。管理网关配置相同名单，用于显示跨校过滤栏；最终授权由服务端执行。网关不得把普通学校账号改写成平台身份。
- 安全事件允许按时间、请求 ID、操作者与动作筛选，仅存审计所需的技术字段。导入历史也使用同一白名单，舍弃 IP、尝试登录的账号、令牌、请求/响应内容和异常原文。现有签名身份、证书审核、发证许可等业务审计依旧由所属服务权威保存。
- `OPERATIONS_RTC_RETENTION_DAYS` 默认 0，运维与校方确认期限后可配 1 至 36500 天。启用时查询立即按窗口限定，下次该校写入 RTC 事件时清理已过期行。安全审计不套用 RTC 的清理规则。

## 历史档案导入

1. 从停写的原单校库生成一致性快照。SQLite 应使用 backup API 或正确的 WAL 备份，MySQL 提供一致快照与只读账号。运维先核对学校、RTC 面试及学生归属，以及审计表所属系统。无法证实学校的档案不导入。
2. 为独立迁移进程设置 `OPERATIONS_ARCHIVE_SCHOOL` 及 `OPERATIONS_SOURCE_DB_ENGINE`。SQLite 使用 `OPERATIONS_SOURCE_SQLITE_PATH`，工具以 URI 只读模式打开。MySQL 使用 `OPERATIONS_SOURCE_MYSQL_*` 和 SELECT 账号，源查询在 READ ONLY 事务内进行。目标继续使用 `OPERATIONS_*` 专库。原生业务进程不带 SOURCE 环境变量。
3. 执行 `python -m services.operations.migrate --school 学校编号 --category both`。若 RTC 和安全审计来自不同快照，可分别选择 `rtc` 和 `audit`。工具不加载工作区的 .env。旧单校记录没有学校列，按运维显式核对的绑定导入。已有学校字段不匹配、学生与面试归属冲突、主键重放载荷不一致，都会回滚本次导入。重跑原快照只确认同一事件。
4. 核对命令返回的扫描条数、职员看到的本班记录及平台审计行；确认旧库只读快照保持原样。学校未设置 RTC 清理窗口时，可从原生连接日志页查看已导入的历史日期。

复验命令为 `python -m pytest -q services/operations`。项目的 `scripts/smoke_microservices.py` 还通过真实学生与管理员 Cookie、分离进程、回环 HTTP 和独立数据库验证 RTC 写入查询及审计送达。
