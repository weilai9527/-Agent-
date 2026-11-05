# 教学证书接口

学校业务签名和链确认分别记录。证书类型固定为“模拟面试训练完成证明”。学生和管理网关使用原生会话，签发服务从独立评估库的所属服务取得报告。省略模式开关即走该链路，显式配置 legacy 或 shared 会在签发服务打开数据库前报错。公开站点仅挂载 GET 验真路由。credentials 的授权动作如下。

| 所属入口 | 服务内路由 | scope | 对象检查 |
| --- | --- | --- | --- |
| 学生 | POST /applications | credential.apply | 已完成训练的本人，以当前报告生成申请 |
| 学生 | GET /me/applications | credential.read | 仅本校本人 |
| 管理 | GET /students/{student_id}/applications | credential.read | 指定学生且逐条核对负责关系 |
| 管理 | POST /applications/{id}/review | credential.approve | 有此动作的负责教师；审核时提交所见版本及摘要 |
| 管理 | POST /applications/{id}/issue | credential.issue | 已批准且当前证据仍一致 |
| 管理 | POST /certificates/{id}/revoke | credential.revoke | 核对对象授权；需要撤销原因 |
| 管理 | POST /certificates/{id}/reissue | credential.reissue | 从已撤销的证书补发，核对原审核及当前证据 |
| 无需登录 | GET /verify/{id} | 无 | 随机证书标识，实时读取撤销状态 |

验真结果以及学生/管理接口应禁止代理缓存。网关应保留证书 ID、申请 ID 及查看时的版本，不接受浏览器自行传入学校、颁发者、报告内容或审核人。服务独立启动命令为 `uvicorn services.credentials.app:app`。

## 评估与身份接入契约

assessment 须提供 `GET /internal/credential-evidence/{report_id}`，audience 为 assessment，scope 为 `assessment.credential-evidence`，仅 credentials 可调用。响应为 `{report_id,interview_id,student_id,school_id,version,digest}`，version 为正整数，digest 为 64 位小写 SHA-256。源服务需在同一报告事务内核对成功生成、当前证据 head 与版本一致，按不可变报告版本（含教师改分）计算摘要。学生只准读取本人，教师按真实任务负责人限制。无完整来源的历史或降级报告不纳入签发。

credentials 将向 training 调用 `GET /interviews/{interview_id}/attempt`（training.verify），校验已完成、报告归属、教师及学校。审核绑定整份来源快照，新版本需重新提交与批准。

### 申请代次与原子签发许可

证书服务先将经过审核的申请、代次、预定序号和学校签名存入私有 `credential_issuance_intents`。此时学生列表和公开验真均不能取得该证书。随后 credentials 以原教师或管理员身份调用 `POST /internal/credential-evidence/{report_id}/authorize`，scope 为 `assessment.credential-authorize`。请求携带 `application_id, generation, serial, version, digest, proof_digest`，其中 proof_digest 绑定完整签名产物。assessment 在与改分相同的会话/报告事务锁内比较版本和证据摘要，并写入 `assessment_issuance_permits`。

许可提交确定了本次签发与并发改分的先后。改分先提交时旧审核返回 409；许可先提交时，后续改分保留原证依据。即使许可回包丢失或凭据进程退出，重新发起同一请求会复用预定序号、签名和原许可，并在本地事务中发布证书及唯一 outbox 事件。重试仍校验操作人当前权限。补发使用下一代次和新许可，原证的撤销记录保留。校方密钥签名、身份查询和服务间调用均在写事务之外执行。

## 部署和调用

- 学生入口使用 `/api/credentials`，管理入口使用 `/api/admin/credentials`，拼接上表服务内路径。申请 body 为 `{"report_id":"…"}`，审核为 `{"version":1,"digest":"<64位小写十六进制>","decision":"approved","note":"…"}`。可选 decision 为 approved 或 rejected。签发、补发经浏览器网关传空 JSON 对象，撤销传 `{"reason":"…"}`。列表支持 `limit`（1–100）和 `after`，用响应中的 next 继续。
- 对应服务 ID 为 credentials，证书数据库配置 `CREDENTIALS_DB_ENGINE` 及 `CREDENTIALS_SQLITE_PATH` 或 `CREDENTIALS_MYSQL_*`。内部签发服务启动时幂等建表，内部 `GET /health` 探测数据库连接。出站配置 `IDENTITY_SERVICE_URL`、`ASSESSMENT_SERVICE_URL`、`TRAINING_SERVICE_URL`、`PROVENANCE_SERVICE_URL`。生产使用 HTTPS；环回开发地址可使用 HTTP。
- 在相关服务信任策略中按学校和 actor_type 放行上表的具体动作。credentials 委派原人类身份到 assessment（学生只授 assessment.credential-evidence；有权签发的教师/管理员还需 assessment.credential-authorize）和 training（training.verify），assessment 委派管理身份到 training，training 委派管理身份到 identity（identity.roster.read）。对职员的每次管理操作，credentials 还以 identity.student.authorize 调用 identity 的 POST /internal/staff/authorize-student，核验其对该学生的具体动作。训练名单与申请记录均不能替代当前授权。
- 通过部署密钥管理系统注入 `CREDENTIALS_SIGNING_KEYS_JSON={"<school>":{"kid":"<活动编号>","private_key":"<Ed25519 PKCS8 PEM>"}}`，`CREDENTIALS_PUBLIC_KEYS_JSON={"<school>":{"<编号>":"<Ed25519 SPKI 公钥 PEM>"}}`。轮换时先部署新公钥再切换活动私钥，保留须继续验真的历史公钥。服务身份签名、学校证书签名、链上的交易授权各自独立配置。
- 外网入口仅部署 `uvicorn services.credentials.app:public_app`。这个 ASGI 实例只注册 GET /verify/{serial}，不执行 DDL。连接同一证书库并授予只读权限，使用学校公钥与单独的 SERVICE_ID=credentials-verifier 及其密钥，provenance 仅为该 caller 的 system 身份授予 provenance.read，不给其他服务授信，浏览器返回中文页面，API 返回 JSON。内网签发进程若设置 `CREDENTIALS_PUBLIC_SERVICE_URL` 为验真源站，会返回可直接分享的绝对 verification_url；同源部署可使用默认相对路径。验证 URL 含 128 位随机序列号，请在入口访问日志中遮盖路径参数。
- 签发、撤销、补发以同一数据库事务更新业务记录并写 credential_outbox。运行 `python -m services.credentials.relay` 驱动投递；provenance 使用独立数据库和 worker。签发与补发用申请或被替换序列号做天然幂等键，同一版本及同一代证书只有一个持久结果。审核/撤销理由冲突返回 409。公开验真使用当前序列号的实时业务状态，已撤销的旧链接持续显示撤销；补发不会代替新版报告的审核。签发与撤销分别取自身对应事件的链状态。
- 投递以 caller=credentials、actor_type=system、actor_id=credentials-relay 按学校获授 provenance.submit/read。公网只读进程为 caller=credentials-verifier、actor_type=system、actor_id=credentials-verifier，仅可查本校锚点。公查返回的 anchor.status 区分 pending、submitted、confirmed、failed 与 unconfirmed（查询不可用）。已确认的 fixture 会明确标记，链路协议与 worker 配置见同级 provenance/INTEGRATION.md。

学生或获授权的教师从列表中可取得 certificates[].proof。使用相应学校的可信公钥，对 UTF-8 编码、字段按键排序、无额外空格的 JSON 对象 `{format,kid,payload}` 验证 Ed25519 签名，signature 为无填充 base64url。私有 proof 与证据可一起归档；当前效力由 verification_url 的实时撤销状态决定。

持有人可运行 `python -m services.credentials.verify_file proof.json --issuer SCHOOL --serial SERIAL` 离线核验，公钥须独立取得并通过 `CREDENTIALS_PUBLIC_KEYS_JSON` 配置。部署指定可信 `CREDENTIALS_PUBLIC_SERVICE_URL` 后，加 `--status` 可查询实时撤销状态。文件签名涵盖 JSON 声明；查验页面上的二维码不能验证任意 PDF 的文字。

## 界面组件

学生端可在认证区域挂载 `<TeachingCredentials key={sessionKey} request={apiRequest} reportId={reportId} />`，默认导出来自 frontend/src/TeachingCredentials.jsx。sessionKey 随账号或学校变化，reportId 可省略。学生可复制公开验真链接、下载签名 JSON。管理端学生详情可挂载 `<TeachingCredentialsPanel key={sessionKey} request={adminRequest} studentId={student.id} actions={grantedCredentialScopes} />`，默认导出来自 admin/src/TeachingCredentialsPanel.jsx。actions 为会话实际获授的 credential.* 动作，所有操作仍由网关与服务重新授权。当前学生界面可从“我的证书”或报告打开申请，管理界面从“证书申请”选择学生。

## 故障排查和审查入口

| 现象 | 检查位置与预期行为 |
| --- | --- |
| 身份服务不可达，或老师已转班、失去某个动作 | 在 `sources.py` 查看原生对象授权和训练归属核对。服务不可达返回 503；已撤回的授权会被拒绝。公开页面仍可查询既有证书。 |
| 证书申请、签发报 409 | 在 `app.py` 核对申请、审核的版本和摘要；评估服务只有在报告锁内确认来源后才提交许可。新版本须重新审核。 |
| 签发响应丢失或进程退出 | 在 `app.py` 的 reserve_intent、publish 和评估许可记录中按申请及代次查证。仅预留的签名不对外发布。重试同一申请会取回原许可，证书、代次和待投递事件在本地一并提交。 |
| 验签通过但链状态为 pending、submitted 或 unconfirmed | 在 `relay.py` 检查持久投递记录，在 provenance 的 worker 检查租约和链回执。网络不可用时保留未确认状态；对应序号的撤销立即在证书库生效。 |
| 下载文件有效性存疑 | `verify_file.py` 离线验学校签名，用 `--status` 查当前效力。签名文件、二维码和链回执有不同的核验对象。 |

## 本地回归

从仓库根目录执行 `python -m pytest -q services/credentials services/provenance`。证据契约在不传身份或存储模式开关时，先由面试服务生成事件，再移走面试源库，由独立评估服务生成报告，使用真实服务凭据完成证书授权和签发。测试给投影中的学生配置 2 个合成文字调用单位，分别检查评分和报告的请求号、用量预留、派发及结算。仅模型 HTTP 回复为合成数据。若评估任务因 usage 不可用而暂缓，申请返回 409，须待证据发布后重试。存证契约通过真实 ASGI 路由、独立收发队列及本地模拟链检查断连重投和最终确认。外部学校、真实链账户和生产配置均不用于测试。

运行 `python scripts/smoke_microservices.py --assessment-mode isolated --crash-issuance` 可检查跨进程故障恢复：在许可提交后终止临时签发进程，真实调整成绩后重启，并核对恢复得到同一预定序号、同一依据和有效签名。
