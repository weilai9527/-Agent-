# 教学任务与教学分析接入

## 面试、评估和证书

training 是尝试 ID 的分配者。学生网关以已认证学生身份调用 `POST /tasks/{task_id}/attempts`，scope 为 `training.start`，body 为 `{"request_id":"<客户端生成并在同一次重试中复用>"}`。返回固定的 `attempt_id`、`interview_id` 及冻结的题目。面试引擎按该 interview_id 幂等创建会话，将题目和 question_id 原样纳入会话。浏览器传入的题文、答题人、学校、老师不能替代训练记录。

- 按尝试查证使用 `GET /attempts/{attempt_id}`，按面试查证使用 `GET /interviews/{interview_id}/attempt`，scope 均为 `training.verify`。结果包含 `school_id, student_id, teacher_id, class_id, task_id, attempt_id, interview_id, status, questions, job_role`。负责老师来自任务发布时经过身份服务核准的教师。改分和审核操作应携带当前 teacher 身份查证，执行者 ID、当前学校与学生和资源均须匹配，且仍要由评估/证书服务检查操作本身的权限。
- 面试完成的持久事件由面试服务以 system 身份投递 `POST /attempts/{attempt_id}/complete`，scope 为 `training.complete`，body 为 `{"event_id":"<持久事件ID>","interview_id":"<预留的面试ID>"}`。重复投递复用同一 event_id。
- 评估服务以 system 身份投递 `POST /v1/completions` 到 analytics，scope 为 `analytics.completion.write`。body 含 `event_id, attempt_id, version, questions`，每个题目含 `question_id, original_answer, dimension, score`。score 取 0–100，version 从 1 开始，同一尝试连续改分以更高版本全量替换。请使用冻结题目 ID 将面试消息/评分关联回训练。analytics 向 training 检查尝试与完成状态。先完成训练尝试，再发送成绩。持久发送方在暂时失败后重投同一事件，不能据单次 HTTP 超时认定对端未写入。

## 身份与浏览器网关

网关先验证真实浏览器 session，按路由检查动作权限，再用 service_headers 为目标 audience 签发仅含本动作的凭据。浏览器不能指定 actor、school、role、caller 或 scopes。请仅挂载下列用户端路由，系统事件和查证端点只供内部调用。

| 网关前缀 | 服务 | 方法与路径 | scope |
|---|---|---|---|
| /api/admin/training | training | GET /classes、/tasks、/tasks/{task_id}/roster | training.read |
| /api/admin/training | training | POST /tasks | training.assign |
| /api/training | training | GET /tasks | training.read |
| /api/admin/training | training | GET /tasks?view=workbench | training.read |
| POST /tasks/{task_id}/attempts | training.start |
| /api/admin/analytics | analytics | GET /v1/teaching/summary、/v1/teaching/weaknesses | analytics.teaching.read |
| /api/admin/analytics | analytics | POST /v1/teaching/practice | analytics.practice.assign |
| /api/analytics | analytics | GET /v1/me/weaknesses | analytics.self.read |

身份服务要从本校的有效任课/授权及学籍关系求出班级、在册学生。服务调用委派原教师上下文，身份服务在服务端重算；返回的班级必须来自授权范围，返回的学生必须属于该班。布置任务不接受来自教师浏览器的 student_ids。原题复练只接受 analytics 对已评估尝试的分派，重新核对负责教师、当前范围、学生以及原题。

## 任务与成绩接口

| 接口 | 请求与返回 |
|---|---|
| POST /tasks | 传 title、job_role、class_ids、带时区的 deadline、max_attempts（1–100）与 questions。每道题含 question_id 和 prompt。可传岗位 job_id。发布方应传固定 request_id 供网络重试。返回 task_id、student_count 和冻结题目。 |
| GET /tasks/{task_id}/roster | 返回 items，每项含 student_id、class_id、used_attempts、completed_attempts。名单按发布时冻结，显示学生明细时再与教师当前班级学籍求交集。student_count 保留发布时应到人数。 |
| GET /tasks | 学生只见自己的任务、当前耗用次数和 latest_attempt。教师可见自己发布且至少一个目标班仍获授权的任务。class_ids 和发布时 student_count 只统计仍获授权的目标班。历史目录保留已转出学生的冻结人数。 |
| GET /tasks?view=workbench | 仅教师或管理员可查看。items 仅含当前仍有应参加学生的任务，每个任务的 class_ids 仅列有有效应到生的班级。student_count 与 completed_count 分别为当前应到和已完成人数。完成任意一次即计为该生完成该任务。classes 包含每个当前授权班级（含零任务），summary 给出跨班汇总。task_count 按任务去重，enrolled_students 为当前在册人数，assigned_students 和 completed_students 分别为有任务、至少完成一项任务的独立学生数。assigned_task_students 和 completed_task_students 以学生、任务组合去重，可作为任务完成率的分母和分子。统计以冻结名单与当前教师授权、班级学籍的交集为准。 |
| POST /tasks/{task_id}/attempts | 同一学生、任务和 request_id 返回同一条尝试，超额或已到截止时间返回 409。截止约束开始时间，已开始的面试可在截止后完成。 |
| GET /v1/teaching/summary | 可按 task_id、class_id、job_role、dimension 筛选。返回已投递评分的尝试数、已评估原题数、分组均分。均分先对每道题的维度分数取平均，再按题平均。 |
| GET /v1/teaching/weaknesses、GET /v1/me/weaknesses | 输入同上。返回低于 60 分的维度、分数、评分版本、原题 ID、原文及学生原答。教师读取同时受学校、任务责任人、当前班级及学生学籍限制。管理员受当前学校和班级范围限制。 |
| POST /v1/teaching/practice | 传 attempt_id、question_id、request_id、deadline、max_attempts。原学生和原题从服务端查证；返回新的单人训练任务。该任务按普通训练规则领取与完成。 |

训练和分析以原教师或管理员身份分别调用 identity 的 `GET /classes`（identity.classes.read，返回 `{items:[{class_id,name}]}`）与 `POST /classes/roster`（identity.roster.read，请求 `{class_ids:[...]}`，返回 `{classes:[{class_id,student_ids:[...]}]}`）。identity 从自己的教职员、授课班级、启用的组织节点、在册且可用的学生账号计算结果。多个服务间的权限映射如下。

| 调用链 | 委派角色 | 所需 scope |
|---|---|---|
| training / analytics → identity | teacher、admin | identity.classes.read、identity.roster.read |
| interview → training | student 核验开场、system 投递结束 | training.verify、training.complete 分别授给对应角色 |
| assessment / credentials → training | teacher 查证负责人、student 查本人、admin 按当前班级范围核验或授权的 system worker | 按实际角色仅授 training.verify |
| assessment → analytics | system | analytics.completion.write |
| analytics → training | system 核验评分归属、teacher 下发复练 | training.verify、training.assign 分别授给对应角色 |

## 页面装配位置

- 管理端 `admin/src/main.jsx` 的 `navItems` 与 `renderContent()` 挂载 `TrainingTasksPage`，请求函数为 `adminRequest`。从服务端当前账号权限派生两个独立的布尔属性：`canAssign` 对应 teacher 的 training.assign，`canAssignPractice` 对应 teacher 的 analytics.practice.assign。导航可见性由原生管理会话的 `/api/admin/snapshot` 提供；identity 的 `staff_adapter` 按当前授权设置 canViewTraining 等能力。首页的业务数字由各归属服务直接提供。读写动作分别授权。教师实际使用发布与分析界面应同时具备相应读取和写入权限。
- 学生端 `frontend/src/main.jsx` 的个人中心进入 training 视图，挂载 `StudentTrainingPage` 并注入 `apiRequest`。回调 `onOpenAttempt(receipt)` 以空 JSON 对象调用学生网关 `POST /api/interviews/training-attempts/{attempt_id}`（interview.training.start）。成功返回绑定的 interview_id 后进入该场面试。失败可复用同一条尝试重试。
- 学生和管理网关的教学路由注册在 `services/gateway/routes.py`；面试交接路由在 `services/gateway/compatibility.py`。两个浏览器入口分别使用 `services.gateway.student:app` 和 `services.gateway.admin:app`。

## 运行和验证

在仓库根目录运行。ASGI 服务使用 `services/requirements.txt` 的依赖。下面端口仅作本地部署示例。每个进程有自己的环境和签名密钥。

```sh
SERVICE_ID=training python -m uvicorn services.training.app:app --host 127.0.0.1 --port 8013
SERVICE_ID=analytics python -m uvicorn services.analytics.app:app --host 127.0.0.1 --port 8014
```

- 本地使用 TRAINING_DB_ENGINE=sqlite 和 ANALYTICS_DB_ENGINE=sqlite。TRAINING_SQLITE_PATH 和 ANALYTICS_SQLITE_PATH 为各自独立的绝对路径。生产各自设置 DB_ENGINE=mysql（带服务大写前缀），以及同前缀的 MYSQL_HOST、MYSQL_PORT、MYSQL_USER、MYSQL_PASSWORD、MYSQL_DATABASE。MYSQL_SSL_CA 可指定受信 CA。服务账号只需自己的库。
- training 配置 IDENTITY_SERVICE_URL。analytics 配置 IDENTITY_SERVICE_URL 和 TRAINING_SERVICE_URL。网关配置相应的 TRAINING_SERVICE_URL、ANALYTICS_SERVICE_URL、INTERVIEW_SERVICE_URL，以及身份服务配置。浏览器来源分别配置 FRONTEND_ORIGIN 与 ADMIN_FRONTEND_ORIGIN，并与网关允许来源保持一致。跨进程使用 HTTPS 或同机回环 HTTP。服务安全还需 SERVICE_KEY_ID、SERVICE_SIGNING_KEY 和 SERVICE_TRUST_POLICY。后者逐 caller、学校、目标 audience 和 actor_type 列出允许的 scope 与公钥。
- 面试侧的持久 worker 分角色投递。配置正确的数据库和身份后，`SERVICE_ID=interview python -m services.interview.worker --kinds train_complete,project` 投递训练完成事件，`SERVICE_ID=assessment python -m services.interview.worker --kinds score,report,analytics` 消费评分与报告任务并投递分析事件。worker 需配置 LEGACY_SCHOOL_ID，以及各自的 TRAINING_SERVICE_URL 或 ANALYTICS_SERVICE_URL。
- `python -m pytest -q services/training services/analytics` 在临时 SQLite 文件上测试。跨服务用例使用真实 identity、training、analytics 和挂载业务路由的管理/学生网关，以进程内 HTTP 传输请求。身份账号和 Ed25519 密钥仅存在于测试环境，完成与成绩事件由测试中的签名调用方投递。
- `node --test frontend/src/trainingUi.test.js` 测试前端截止时间转换、写入幂等键和请求体。

## 原生管理首页的运营指标

首页把当前学校运营与已下发任务分区展示。运营面板按当前身份、在册关系读取全部可见面试，包含自主练习；班级任务面板使用冻结任务名单与当前学籍的交集。学校管理员与授课教师使用同一组读接口，服务端独立核验每个动作和组织范围。

| 来源与浏览器路径 | 动作 | 与旧工作台对照的统计口径 |
|---|---|---|
| identity · GET /api/admin/identity/v1/student-accounts/summary | student.read | 现存账号按启用、停用和归班统计。登记已撤销的非正常账号计入停用；已启用未归班只统计正常账号。待改密包括首次登录及重置后的修改要求。支持学院、班级编号。 |
| identity · GET /api/admin/identity/v1/student-accounts/pending-summary | registration.read，限本校全校管理员 | 读取本校现行登记表中未归档、未开通的记录。队列包含撤销后待处理的登记。总数覆盖全校，预览最多五人。时间与组织筛选仅作用于其他面板。 |
| interview · GET /api/admin/interview/v1/workbench | interview.records.read | 归属服务按面试更新时间统计可见场次、状态及来源。场次完成率按已完成场次除以总场次；学生参与率按至少完成一场的可见学生数除以当前可见的正常学生数。 |
| assessment · GET /api/admin/assessment/v1/workbench | 网关动作 assessment.records.read，对应人员授权 report.read | 按报告创建时间统计生成和质检状态。待质检为报告当前 review_status=pending，包括尚待生成或补评的报告；实际可办理的复核和改分由评估服务核验报告版本、负责人及独立授权。 |

面试与报告支持 `college_id`、`class_id`、`kind=practice|training` 和上海自然日起止日期。各服务通过 identity 的 `identity.records.scope` 分批获取当前授权学生，并在自己的专库汇总。预览默认五条，接口可请求一至二十条。默认单次最多汇总二万名可见学生，超过上限请缩小范围。只用近期页计算总量会漏掉较早记录，因此计数和分布均从完整授权样本计算。跨域读取的时间可能略有差异，未宣称各服务在同一事务中。

均分及分段以 90、80、70 分为界。新版必须有有效分且全部作答已评分，历史报告在覆盖数未知时须有实际作答、成功生成且未使用降级评分。零分可进入统计，零有效样本返回空均分。报告待办、学校记录和教学薄弱项使用不同权限。获取某区失败时其他已授权面板仍可使用。

网关需按学校分别给 admin-gateway 配置 identity、interview 与 assessment 的上述读取动作。interview、assessment 的 teacher/admin 委派均需在 identity 端获准 identity.records.scope。网关无需旧库账号。接口由原生服务正常启动时自动装配，启动入口和专库环境变量以 `python -m deploy.run_service list` 及部署说明为准。

待质检队列跳转至报告记录时预置 `state=pending`，进行中队列预置 `state=running`。点击成绩段会加上 `score_band`，沿用相同有效成绩判定。运营看板的日期、学院、班级和来源均可带入完整列表。每次变更筛选重新从第一页读取；列表按授权学生编号与记录标识分页，和按时间排序的首页预览各自服务于不同的查询需求。

从仓库根目录可分别复验下列场景：

- `python -m pytest -q tests/integration/test_record_workbench.py tests/integration/test_school_records.py` 验证面试与评估专库的状态分布、隐藏占位分、分段分页及当前名册权限。
- `python -m pytest -q services/identity/test_account_summary.py services/training/test_school_dashboard_gateway.py` 使用签名的学校账号验证登记、归班和撤权，限制 SQLite 只能打开临时身份库。停用面试及评估后，正式网关返回 503，并继续提供已授权的登记待办。
- `node --test admin/tests/nativeTeachingDashboard.test.cjs admin/src/SchoolRecordBrowser.test.cjs` 验证管理入口的服务失败、空样本、原题定位、质检草稿及筛选下钻。需要测试环境提供 jsdom。
