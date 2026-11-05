# 身份、租户与学校组织

## 启动与网关会话

从项目根目录运行 `uvicorn services.identity.app:app`。数据库使用 `IDENTITY_DB_ENGINE` 加 `IDENTITY_SQLITE_PATH`（绝对路径）或 `IDENTITY_MYSQL_*`。identity 的服务凭证、调用方公钥、可委派学校、角色和动作由 `SERVICE_ID`、`SERVICE_KEY_ID`、`SERVICE_SIGNING_KEY` 和 `SERVICE_TRUST_POLICY` 配置。浏览器只持有不透明会话 cookie，数据库只保存 token 摘要。

日常服务进程默认使用原生身份会话。网关按配置的学校绑定向 identity 签名内省，身份库按学校、班级和人员分别校验范围。正常服务显式设置 `IDENTITY_SESSION_MODE=legacy` 会拒绝启动或返回 503。人员登录、授予和写入都不能切到旧库。旧账号库仅为离线切换材料，写入兼容测试只允许显式启用的隔离夹具进程。

在候选人或管理网关的固定路由中调用同步函数 `services.identity.gateway.candidate_gateway_context(request, scope)` 或 `admin_gateway_context(request, scope)`。响应为 `{actor_id, school_id, actor_type, scopes:[scope]}`，可传给 `service_headers(audience, **context)`。路由固定 HTTP 方法及 scope，阻塞的会话查询和签名 HTTP 内省应在线程池执行。

学生、管理网关分别挂载 `services.identity.candidate_adapter.mount_candidate_auth(app)`、`services.identity.staff_adapter.mount_staff_auth(app)`。当前仓库的 `services.gateway.student` 和 `services.gateway.admin` 已调用它们。native 模式保留前端的登录、me、退出与学生首次改密 URL，使用 `identity_student_session`、`identity_staff_session` 两种 HttpOnly cookie。管理端 snapshot 返回当前账号和已接通模块的能力标志，学校统计使用获准业务域提供的数据。原生管理网关将请求审计写入结构化日志，身份与授权操作由 identity 持久化审计；网关无需业务 SQL 凭据或旧主管理员口令。

- 会话代理使用 `system/gateway` 与 `identity.session.proxy`，代理固定的 `/sessions/student/{login,me,logout,change-initial-password}`、`/sessions/staff/{login,me,logout}` 路由。me 为 GET，其余为 POST。学生使用学号和密码，职员使用邮箱和密码，学校由网关填入。验证成功后代理重建指定的 cookie。
- 内省使用 `system/gateway` 与 `identity.session.resolve`，调用 `POST /internal/sessions/{student|staff}/resolve`，提交 `{"token":"…","action":"路由动作"}`。此路由不对浏览器开放。
- `APP_ENV=production` 强制 Secure cookie 和 HTTPS 的 `IDENTITY_SERVICE_URL`。网关配置前端来源 `FRONTEND_ORIGIN` 或 `ADMIN_FRONTEND_ORIGIN`；直接使用 identity 浏览器路由时，可通过 `IDENTITY_BROWSER_ORIGINS` 指定额外来源。

## 独立动作与对象检查

`report.read`、`report.review`、`report.export`、`score.adjust`、`credential.approve`、`credential.revoke` 分别授权。旧 `viewReports` 只映射到读取。assessment 的 `assessment.history/review/score` 分别需要 `report.read/report.review/score.adjust`。改分和批准证书必须为有该动作的教师，域服务还要向 training 核验此次尝试的负责教师。旧管理报告导出使用 `GET /api/admin/reports/{report_id}/export` 和 `report.export`，返回带附件头的 JSON，并留存导出审计。

旧 `manageModelConfig` 只映射到 `model.config.read`。学校职员的显式 `model.config.write` 与平台供应商写入独立。平台配置读取、修改和探测分别使用 `providers.read`、`providers.configure`、`providers.diagnose`，由平台管理入口授权，不能把学校会话的 school_id 改为 platform 来取得权限。

| 调用方 | identity 下游路由 | 动作与返回 |
|---|---|---|
| training、analytics | `GET /classes` | identity.classes.read，返回 `{items:[{class_id,name,…}]}`。 |
| 教学、职业等获准的内部服务 | `POST /classes/roster`，提交 `{class_ids:[…]}` | identity.roster.read，返回 `{classes:[{class_id,student_ids:[…]}]}`。身份库核对当前职员授权、班级分配和在册学生，部分越权请求整批拒绝。 |
| 学生业务服务 | `GET /internal/students/me` | identity.student.read，仅使用本人委派，返回 `actor_id,school_id,name,status,must_change_password`。停用、须改密或不在该校时返回 403。业务服务可据此维护本地学生引用。 |
| 评估、证书 | `POST /internal/staff/authorize-student`，提交 `{student_id,action}` | identity.student.authorize。动作支持 report.read/review/export、score.adjust 和 credential.read/approve/issue/revoke/reissue。成功返回 `{school_id,actor_id,actor_type,student_id,action}`。 |
| 档案 | 同一路径，动作 `profile.student.read` 只接受 profile 签发的委派 | 教师和管理员需显式获得此项人员权限。每次查询复核同校有效账号和当前任课班级，全校管理员可查本校有效学生。 |

动作核验的 student_id 来自业务服务持久化的报告、尝试或证书。消费方比对身份服务返回值，另向 training 核验独家负责关系。该接口不能直接面向浏览器。独立的身份、对象核验失败时应终止对应动作。

## 管理 API

下列均为 identity 服务内路径。已挂载的管理网关前缀是 `/api/admin/identity`。

| 方法与路径 | scope | 约束 |
|---|---|---|
| GET /v1/organization | organization.read | 只返回职员可见组织。 |
| POST /v1/organization/import | organization.manage | 全校管理员。显式提供班级的 staff_ids 会替换其分配。 |
| POST /v1/classes/{class_id}/roster/import | roster.import | 同时核对来源班和目标班，整批变更、审计同事务提交。 |
| POST /students/import | student.import | 全校管理员。请求为 `{students:[{student_no,name,temporary_password}]}`，至多 100 个新账号，初次登录强制改密。 |
| POST /v1/students/{student_id}/reset-password | student.reset | 全校管理员，提交 temporary_password，强制首次改密并撤销所有本人会话。 |
| PATCH /v1/students/{student_id}/status | student.status | 全校管理员，提交 normal 或 disabled 的 status，变更时撤销会话。 |
| POST /v1/staff、PUT /v1/staff/{staff_id}/grants | permissions.manage | 全校管理员。替换授权会撤销目标现存会话。 |
| GET /v1/legacy-permission-requests | permissions.manage | 全校管理员查看迁入的历史申请。挂起申请须核对并重新授予。 |
| GET /v1/audit | audit.read | 全校管理员只读本校审计。 |

原生模式关闭旧的自助注册和邮件重置入口。密码或状态变更由独立的管理动作处理。为启用这两项操作，管理网关需挂载表中的两个固定 URL，并给 admin 委派 student.reset、student.status。

## 从旧数据库迁入

1. 冻结旧账号、权限和名册写入，制作一份经运维确认的单校只读快照。使用 `IDENTITY_SOURCE_DB_ENGINE` 和 `IDENTITY_SOURCE_SQLITE_PATH` 或 `IDENTITY_SOURCE_MYSQL_*` 指定源，identity 服务变量指定独立目标库。
2. 运行 `python -m services.identity.migrate --school SCHOOL --master-email EMAIL`。`LEGACY_SCHOOL_ID` 必须与 SCHOOL 相同。EMAIL 指定该校已有且启用的主管理员账号，其余职员仅继承可识别的授权。旧 role 展示文本不能建立教师身份。
3. 工具在一个目标事务中复制学生及职员账号（保留 ID 与既有密码摘要）、组织和名册、历史权限申请、管理员业务审计，并记录完成标志。按学院或专业配置的范围展开为当时已有的具体班级。原导入记录、软删除信息和历史组织字段按校归档。重复执行不会覆盖原生密码或恢复已撤销的权限。共享 `security_audit_events` 保留在旧历史审计库。
4. 验证账号、班级、在册学生和业务审计后切换网关。保持旧认证与名册写入口离线。回切前须处理切换后已经发生的密码、权限及组织变更。

### 原生职员权限申请

已启用的 admin/teacher 可在「学校管理 → 权限申请与审批」提交自己的申请。管理网关必须为这两类身份分别配置 identity audience 的 `identity.permissions.self` 调用权限。GET/POST `/api/admin/identity/v1/me/permission-requests` 只接受本人学校会话；提交包含 request_key、actions、classes、reason。身份服务生成可选动作，班级只接受本校现有且启用的编号。申请不改变业务身份或全校数据范围。

全校 `permissions.manage` 管理员可经 GET `/api/admin/identity/v1/permission-requests?status=pending` 查看队列，通过 POST `/api/admin/identity/v1/permission-requests/{id}/decision` 提交 approved/rejected 和非空 note。通过班级范围申请还需 `organization.manage`。系统在同一事务复查负责人权限、申请人身份与授权版本，保存审批意见、变更授予及审计；通过后申请人需重新登录。直接授权或班级分配变更会使该职员未决申请失效，即使旧权限集合后来恢复也须重新申请。迁入的旧记录保持只读。

## 工作台账号摘要

- `GET /v1/student-accounts/summary` 使用 `student.read`。账号总数仅统计本校当前可见的已建账号。正常账号数和停用账号数之和等于总数。停用统计覆盖所有非 `normal` 状态，包括撤销开户后保留的 `registration_revoked` 账号。`must_change_password` 只统计正常账号中的待改密人数。`unassigned_accounts` 包括全部状态且没有有效归班的账号，`unassigned_normal_accounts` 专用于展示可登录但仍未归班的人数。可传 `college_id` 和 `class_id`，无权访问或不匹配的组合返回 403。
- `GET /v1/student-accounts/pending-summary` 使用 `registration.read`，限管理网关委派的本校全校管理员。返回 `school_id`、`pending_accounts` 及按学号排序的前五条 `items`，每项只含 `name`、`student_no`。待办以登记表的 `archived=0 AND opened=0` 为准，包含撤销开户后待处理的登记。实际发放账号时还要核验学籍状态。该接口只读全校队列，不接受筛选和请求正文。

## 注册名单、开通待办与密码发放

正式管理端在「学校管理 → 注册名单与开通待办」办理。所有接口均由管理网关签名中继到 identity 的 `/v1/registrations`，并在身份库实时核对全校管理员、学校及下列独立权限。部署需为管理网关的 admin 角色配置相应动作，现有学校经授权管理流程逐项授予。

| 动作 | 接口与用途 |
| --- | --- |
| `registration.read` | GET 名单，按状态、学号、姓名、学院、班级和辅导员分页筛选。 |
| `registration.export` | GET `/export` 导出当前筛选的 XLSX，不含密码，逐次审计。 |
| `registration.import` | POST `/import` 或 `/import-xlsx`（接受 XLSX 或 CSV），按校内学号增量登记，重复文件不重复开户。学籍字段仅在显式办理账号操作后生效。 |
| `registration.issue` | POST `/issue`，对勾选的待开通学生生成随机初始密码。涉及真实分班另需 `roster.import`。 |
| `registration.status` | POST `/apply` 同步姓名、停用状态及归班（归班另需 `roster.import`）；`/revoke` 撤销登录，但训练记录和学生 ID 保留。`/archive`、`/restore` 仅改变登记行可见状态。 |
| `registration.reissue` | POST `/reissue` 要求选择补发原因；事务内轮换密码、使旧会话失效并记录审计。 |

批量操作携带 `items: [{student_no, revision}]`（每批 1 至 100 人），补发另传 `reason`（“凭据遗失”或“发放失败”）。任一行权限、状态、版本或班级不匹配，整批回滚。电子表格导入限 720 KiB、4,999 人，拒绝公式、异常 XML 和重复学号；班级存在重名时填写班级编号。开户或补发返回的一次性发放单仅留在页面内存，五分钟后或关闭页面后清除；数据库保留密码摘要，读取名单、导出和审计均不返回密码。HTTP 响应丢失后重新加载名单核对版本，确需重新发放时显式补发。

已迁入学校应重新运行原迁移命令并核对数量，新步骤使用目标库中已封存的旧登记和组织存档，保留软删除标识与稳定账号 ID，不从旧系统恢复明文密码或已撤销授权。组织管理的 `POST /v1/organization/import-workbook` 支持校方 XLSX 多工作表和 CSV。可同时写整条学院、专业、班级路径，或使用可唯一确定上级的分表。只补充新节点，重名或上级不明时整批回滚。组织说明保留学院编码、标准专业代码、培养方向、专业负责人、班级辅导员、毕业年份和邀请码。停用组织前先移交在用子节点和师生关系，历史记录按原编号保留。

## 职员改名和强制密码重置

学校管理页的「职员资料与密码」使用 `staff.profile.write` 维护姓名，使用独立的 `staff.password.reset` 轮换凭据。操作者须为本校全校管理员，在登录状态下核对受管职员编号、姓名、邮箱与版本。职员目录可查看编号。禁止代管本人、外校账号、全校主管、权限管理员以及操作权限高于本人的账号。例如普通校管不能重置拥有负责教师改分权限的账号。高权限或唯一主管账号按学校独立核验的恢复制度处理。

经管理网关使用 GET/PATCH `/api/admin/identity/v1/staff/{id}/profile`，GET/POST `/api/admin/identity/v1/staff/{id}/password-reset`。写请求须带读取时的 `expected_revision`。补发会撤销旧会话，登录只能在正确临时密码和合规的新密码均通过后获得新会话。单独提交临时密码返回 428，页面提示补充新密码。资料、密码状态和审计同事务生效；日志不含密码。
