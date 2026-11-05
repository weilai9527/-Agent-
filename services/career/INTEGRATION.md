# 职业目录与招聘服务

在发布目录执行 `python -m pip install -r services/career/requirements.txt`。本地入口为 `python -m uvicorn services.career.app:app --host 127.0.0.1 --port 8103`。`GET /health` 检查进程，`GET /ready` 检查已配置的各校数据库。可在 `/openapi.json` 查看参数与数据结构。

## 学校、存储和出站

- 单校进程显式配置 `CAREER_SCHOOL_ID` 与 `CAREER_DB_ENGINE`。SQLite 使用绝对路径 `CAREER_SQLITE_PATH`，MySQL 使用 `CAREER_MYSQL_HOST/PORT/DATABASE/USER/PASSWORD` 及可选 `CAREER_MYSQL_SSL_CA`。数据库账号应仅有本服务表的读写与初始化所需 DDL 权限。
- 多校进程通过 `CAREER_SCHOOL_DATABASES` 指定 JSON 对象。键为学校 ID，值为 SQLite 绝对文件路径或同一 MySQL 实例下的数据库名。每所学校必须使用独立数据库。数据库内的学校绑定会在事务开始时复核。已有旧库请先停写并离线迁移到空目标库，再启动服务。正常启动会给未含目录的校库初始化计算机试点目录。
- 进程身份为 `SERVICE_ID=career`，验证入站需要 `SERVICE_TRUST_POLICY`。向 profile 调用时配置 `SERVICE_SIGNING_KEY`、`SERVICE_KEY_ID`、`PROFILE_SERVICE_URL`。服务 URL 必须为 HTTPS origin 或回环 HTTP origin；请求禁用重定向与环境代理。
- 岗位对比从 profile 的 `GET /api/profile/versions/current` 拉取单个快照。委派的 `actor_id/school_id/actor_type` 与入站学生相同，作用域为 `profile.snapshot.read`。career 核对快照所属学生、学校，再在本地规则引擎计算分数。结果包含 `result.profileVersion` 和兼容旧版的 `resume_hash`。证据仅保留匹配技能，岗位对比记录中不写入简历原文。profile 不可用时返回错误。
- 通过 `CAREER_MODEL_BY_SCHOOL` 为各校选择单一供应商，例如 `{"school-a":"custom","school-b":"local"}`。未配置的学校使用本地规则。已授权的外部模型需要配置 `PROVIDERS_SERVICE_URL` 和 `providers.runtime.read` 工作负载授权。自定义供应商要求 `AI_BASE_URL` 命中 `PROVIDER_ALLOWED_CUSTOM_ENDPOINTS`，同时提供部署侧 `AI_API_KEY` 与 `AI_MODEL`。私有模型调用硬时限由 `PRIVATE_MODEL_TIMEOUT_SECONDS` 指定，默认 5 秒，上限 8 秒，进程最多同时处理 4 个私有模型调用。发给供应商的内容限定为规则分、技能词典中命中的技能名称和要求满足情况计数。模型只增强 summary、strengths、gaps、suggestions、interviewFocus。响应无有效建议、供应商超时或并发容量耗尽时，保留规则结果并标记 fallback=true。策略配置无效时返回 503。结果中的 provider、model 记录实际生成建议的来源。
- 模型计算期间不持有数据库锁。写入时重新检查岗位是否仍已发布及对比字段是否变化。岗位信息已更新返回 409，删除或下架返回 404，均不保存陈旧匹配记录。模型处理期间学校策略变更会返回 409。同期修改简历不影响此次使用的已冻结版本。
- 招聘同步的运维变量为 `JOB_POSTING_SYNC_ENDPOINT`、`JOB_POSTING_SYNC_SOURCE`、可选 `JOB_POSTING_SYNC_TOKEN`。通过 `JOB_POSTING_SYNC_SCHOOL_ID` 指定可使用该数据源的学校；未设时仅可使用显式单校绑定。网关请求不能提供 URL 或凭据。令牌须使用 HTTPS，数据源不跟随重定向，单次响应上限 5 MiB、2000 条。相同来源与外部编号执行更新。

## 学生侧契约

候选人网关已挂载 `/api/catalog/{versions,tree}`、`/api/job-postings`、`/api/job-matches` 和匹配详情；配置 `CAREER_SERVICE_URL` 后对接下列 `/v1` 路由。入站 Bearer 使用 `require_service("career", scope)`，公开目录可通过显式绑定了 `PUBLIC_CATALOG_SCHOOL_ID` 的 system 身份读取。其他学生操作使用 student 身份。

| 已挂载的内部方法与路径 | Scope | 输入与响应 |
| --- | --- | --- |
| GET /v1/catalog/versions、GET /v1/catalog/tree | catalog.read | 发布的版本列表，或可按 version 查询的目录树 |
| POST /v1/catalog/directions | catalog.enrich | {names,record:false} → {directions}。最多 20 个方向名，每个不超过 160 字 |
| POST /v1/catalog/suggestions | catalog.suggest | {names,record:true,event_id?} → {directions}。按学生、事件及规范化名称去重，写入未匹配名称供审核 |
| GET /v1/job-postings | posting.read | 可按 keyword 筛选，仅返回 active 且已发布的岗位，最多 200 条 |
| POST /v1/job-matches | match.create | job_posting_id 或 20–20000 字的 jd_text，可附 job_title、company。网关按已登录学生重建 student，包含 name、student_no、college。返回 201 与 {job_match} |
| GET /v1/job-matches、GET /v1/job-matches/{match_id} | match.read | {matches} 或 {job_match}，只查当前学校及当前学生 |

## 管理侧契约

管理网关已挂载下列既有 `/api/admin` 路径。内部请求将前缀换为 `/v1/admin`；表格传 multipart 字段 file，导出与模板返回 XLSX，其余响应沿用旧 JSON 结构。网关验证登录、具体动作权限与写请求来源。签发的 actor_type 为 admin 或 teacher，管理员代录无所属人的 JD 使用 admin。

| 前缀 /v1/admin 下的方法与路径 | Scope |
| --- | --- |
| GET /job-postings、GET /job-postings/template、GET /job-postings/export | posting.admin.read |
| POST /job-postings、PUT /job-postings/{id} | posting.write |
| DELETE /job-postings/{id} | posting.delete |
| POST /job-postings/import、POST /job-postings/sync | posting.import、posting.sync |
| GET /job-matches、GET /job-matches/{id} | match.admin.read |
| GET /jd-submissions | jd.read |
| POST /jd-submissions、PUT /jd-submissions/{id} | jd.write |
| DELETE /jd-submissions/{id}、POST /jd-submissions/{id}/approve | jd.delete、jd.approve |
| GET /catalog/versions、GET /catalog/tree、GET /catalog/job-suggestions | catalog.admin.read |
| POST /catalog/versions、POST /catalog/versions/{id}/entities/{type}、PATCH 或 DELETE /catalog/versions/{id}/entities/{type}/{entity_id}、PUT /catalog/versions/{id}/jobs/{role_id}/competencies | catalog.write |
| POST /catalog/versions/{id}/publish、POST /catalog/versions/{id}/imports | catalog.publish、catalog.import |
| POST /catalog/job-suggestions/{id}/review、/merge、/approve-to-draft（相同前缀） | catalog.review |

**管理员学生名单属于受信网关的授权决定。** `SERVICE_TRUST_POLICY` 必须仅向执行管理鉴权和名单计算的管理网关 caller 授予 `match.admin.read` 与 `jd.*` 中的具体动作。候选人网关和其他服务不得获得这些动作。管理网关依据已认证管理员的班级/学生范围计算并替换请求正文。career 信任此调用方提供的名单，仅在已绑定的学校库中访问这些学生的记录。

匹配和 JD 管理请求均须携带 JSON，包括 GET 和 DELETE。结构为 `{"student_ids":["student-id"],"payload":null}`。最多 10000 个 ID，列表和详情均在 SQL 查询中过滤，先授权再分页。空数组表示没有可管理的学生；本校管理员可访问无归属学生的手工 JD。只有有权访问全校的管理网关请求可传 `student_ids:null`，教师不能使用 null。前端原有的写入字段放入 payload。审批 JD 和生成岗位在一个事务中完成，重复批准沿用已有岗位。目录与招聘表格分别限制 10 MiB 和 5 MiB，解包总大小 16 MiB，导入纯表格 OOXML，每张表最多 5000 行、64 列。

可用 `python -m pytest -q services/career` 验证。服务测试使用临时生成的签名密钥和独立校库；同步测试注入固定运维 feed，快照调用也使用固定响应，均无需访问第三方。

历史数据使用同一离线迁移程序。先配置并核实单校来源库、空目标校库，停写后执行，再启动 career。来源/目标变量、重跑和回切条件见 [简历与职业数据迁移](../profile/INTEGRATION.md#网关与历史迁移)。

```sh
python -m services.career.migrate career --school "$LEGACY_SCHOOL_ID"
```

## 原生管理端的入口

管理端从登录快照中的具体动作生成侧栏及操作按钮。仅有 `posting.import` 的账号可在「招聘信息 → 招聘岗位」上传岗位表格。仅有 `catalog.import` 的账号可在「岗位信息」输入已获知的草稿 ID 并导入职业目录；同时有 `catalog.admin.read` 时可从版本列表选草稿。目录 Excel 沿用七个工作表，导入结果包含实际写入行数。

持有 `jd.write` 的原生管理员可在「招聘信息 → 学生 JD 审核」新增粘贴的岗位描述，初始状态为待审核。列表读取和审核入库分别需要 `jd.read` 与 `jd.approve`。目录建议审核使用 `catalog.review`。岗位导入、目录导入和 JD 新增页面仅请求当前操作所需数据。

使用已构建的管理端可运行 `python admin/tests/career_browser_smoke.py`。脚本通过本机回环端口启动临时 identity、career 和管理网关，创建合成原生账号，使用 Playwright 检查侧栏点击、表单提交与职业数据库记录。

## 学校专业关联岗位

原生管理网关继续提供 `GET /api/admin/campus/program-jobs` 与 `PUT /api/admin/campus/programs/{program_id}/jobs`。内部对应 `GET /v1/admin/campus/program-jobs`（program_jobs.read）与 `PUT /v1/admin/campus/programs/{program_id}/jobs`（program_jobs.write）。员工委派保持原 actor_id、actor_type、school_id。career 通过 `IDENTITY_SERVICE_URL`，以自己签发的身份调用下列 identity 接口。

| 身份核验方法与路径 | 委派动作 | 用途 |
| --- | --- | --- |
| GET /internal/staff/program-job-options | program_jobs.read | 查询本人可见的活动学院、专业及各专业的编辑权限 |
| GET /internal/staff/program-job-options/write | program_jobs.write | 每次保存前重新核验真实角色、当前写权限和专业范围 |

读接口返回 school_id、colleges、programs、jobs、publishedVersion、canEdit。programs 中每条含 canEdit、revision、jobs，每个关联含 job_role_id、priority、job_name。教师只读。获得写权限的管理员还须有该专业所有活动班级的管理范围，或具备全校范围。候选岗位来自本校已发布且各上级均启用的职业目录。旧关联指向撤下的岗位时，保留其标识和推荐程度，便于管理员移除。

写请求接受 `{"jobs":[{"jobRoleId":"岗位标识","priority":"optional"}],"expectedRevision":1}`。最多 50 项，priority 可选 recommended 或 optional，空数组清除全部关联。兼容旧客户端的 jobRoleIds 数组，先去重再将前三项标记为重点推荐。新客户端应带上读到的 revision。并发版本不符返回 409，写成功返回 school_id、revision、ok、jobs、jobRoleIds。职业库在单个事务内核对已发布岗位、替换关联并递增版本。身份服务不可达时中止请求。

离线 `python -m services.career.migrate career --school 学校标识` 同时迁移旧 program_job_roles，保留原 ID、专业标识、岗位标识、推荐程度和时间。若同一学校已完成旧版职业迁移，重跑会依据旧回执仅补迁专业岗位关系。目标已经有人工配置时，补迁会停止。请在启用新配置前完成身份组织迁移，使专业标识与原学校一致。

简历服务可用 student 身份和 catalog.read 委派调用 `GET /internal/resume-form/catalog`。返回 school_id 及 colleges，每个学院只含 id、name、majors，每个专业只含 id、name。本校尚无发布目录时 colleges 为空。
