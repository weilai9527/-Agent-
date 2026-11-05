# 旧框架应急边界与操作步骤

日常业务只从学生网关和管理网关进入。线上服务、Worker 和浏览器均无切回旧后台的路由。下游服务故障时，保留可重放的任务或返回不可用；成绩、审批、签发和账号变更继续由各自的原生服务持有。同一笔业务没有第二个写库。

旧框架的写入实现保存在 `backend/offline/` 和 `admin_backend/offline/`，用于构造合成历史数据、验证迁移。两个旧 `src/main.py` 直接启动时会在打开数据库前拒绝。写入夹具须由隔离的测试解释器显式启用，只接受临时合成 SQLite 文件或本机验证专库。不要给对外进程分发离线夹具、审批私钥或旧库凭据。

## 准备冻结快照

备份管理员从已验证学校归属的**恢复副本**制备状态文件。优先选独立 assessment 库。快照仅包括学校、真实备份水位、报告数量，以及按报告编号查询的生成与复核状态。姓名、答案、评分、证书或临时密码不进入快照。输出文件须是新路径。

```sh
python -m deploy.emergency_prepare snapshot \
  --school school-a --as-of 2026-11-01T08:00:00+08:00 \
  --sqlite /isolated-restore/assessment.sqlite --output /secure-export/report-status.sqlite
```

使用 MySQL 恢复副本时，把 `--sqlite ...` 替换为 `--mysql`。在导出进程单独设置 `EMERGENCY_SOURCE_DB_ENGINE=mysql` 及相应的 `EMERGENCY_SOURCE_MYSQL_*`、TLS 信任和 SELECT 账号。整个分页读取处于同一个只读事务。若读取尚无学校标记的旧 SQLite 文件，先由校方核实单校来源、冻结并合并事务日志，再附加 `--legacy-sha256` 及独立留存的文件摘要；应急部署不连接无学校标记的旧 MySQL 实例。

## 工单审批和使用

审批人在隔离管理机核对学校、备份水位、操作者和工单号。Ed25519 审批公钥由部署方预置，私钥只在审批机。以下签发示例生成有效 20 分钟的工单，最长 60 分钟。重复使用已有输出目录会失败。审批包中的 `permit.jwt` 投递给应急服务，`bearer` 通过受控渠道交给本次值班人员。

```sh
umask 077
python -m deploy.emergency_prepare issue \
  --school school-a --incident INC-1001 --operator oncall-01 --minutes 20 \
  --snapshot /secure-export/report-status.sqlite \
  --key /approval/ed25519-private.pem --output /approval/INC-1001
```

运维在本机通过独立环境启动，只监听 `127.0.0.1:3010`。不要将此端口加入普通站点、负载均衡或反向代理。

```sh
EMERGENCY_SCHOOL_ID=school-a \
EMERGENCY_APPROVER_PUBLIC_KEY_FILE=/etc/interview-emergency/approver.pub \
EMERGENCY_TICKET_FILE=/run/interview-emergency/INC-1001.jwt \
EMERGENCY_SNAPSHOT=/secure-export/report-status.sqlite \
python -m deploy.emergency
```

运维客户端从权限为 0600 的文件读取本次口令，放入 Authorization Bearer 请求头。可调用 `GET /emergency/summary` 或 `GET /emergency/reports/{报告编号}/status`。返回含快照水位。使用历史查询结果不能重新判定证书有效性，最新撤销状态始终由正式验真服务提供。

## 结束与复核

删除工单文件即可阻止后续查询；工单到期自动拒绝。结束后停止进程、撤掉凭据文件，按学校规定归档事件日志。日志仅包含工单、操作者、固定路由和结果，不记录口令、具体报告号或响应正文。签名或学校不匹配、快照被替换、视图替代表、状态字段含未知文本，以及写请求或旧 Cookie 请求，都应被拒绝。用 `python -m pytest -q tests/security/test_emergency_boundary.py tests/security/test_emergency_boundary_startup.py` 复验。


制备时在同一个只读事务内核验学校标记。若提供旧文件的 SHA-256，恢复副本中已有的专库标记和各表的学校列仍须与工单一致；遇到混校、空归属、异常主键或无法完整分页的报告时不发布快照。审批端复制一份私有只读文件，用同一份字节核验结构并签名。服务启动后校验文件摘要、主键、状态白名单和标识格式；额外的表、视图、触发器及生成列均被拒绝。

运行中的进程一旦观察到工单撤回或过期，即使旧文件被还原，该进程也不会重新开放。运维应按流程停止该进程，重新审批时使用新的工单编号和口令。
