# 候选人简历服务

从仓库根目录安装 `services/profile/requirements.txt` 后运行
`python -m uvicorn services.profile.app:app --host 127.0.0.1 --port 8102`。
数据库变量为 `PROFILE_DB_ENGINE=sqlite` 与绝对路径 `PROFILE_SQLITE_PATH`，或独立的 `PROFILE_MYSQL_*` 账号和库。服务启动时创建自己的表。配置 `SERVICE_ID=profile` 和 `SERVICE_TRUST_POLICY` 后，服务按委派的学生身份校验请求。SQLite 文件与数据库备份包含私人简历，仅授权给 profile 服务账号。图片和扫描 PDF 的本地识别需要 Tesseract 与对应语言包。

| 方法和内部路径 | 委派 scope | 响应 |
| --- | --- | --- |
| GET、PUT /api/profile | profile.read、profile.write | {profile}，PUT 为完整表单更新，保留上传文件名，额外返回同事务提交的顶层 version，重复保存沿用已有版本 |
| GET、PUT /api/resume-form | profile.read、profile.write | GET 为 {form}，PUT 为 {ok,form,resume_text,profile} |
| GET /api/resume-form/settings | profile.read | 当前学生所在学校合并后的 {colleges} |
| GET、PUT /api/admin/resume-form-settings | profile.settings.read、profile.settings.write | 管理员维护的 {school_id,revision,colleges}，PUT 成功额外返回 ok |
| POST /api/profile/resume-upload | profile.upload | multipart 字段 file，返回 filename、text、char_count、original_char_count、truncated、profile |
| GET /api/profile/resume-analysis | profile.read | {resume_analysis,current_source_hash,stale} |
| POST /api/profile/resume-analysis | profile.analyze | 可选布尔字段 force，返回 {resume_analysis} |
| GET /v1/admin/students/{student_id}/profile | profile.student.read | 当前版本的教学摘要，返回 school_id、student_id、version 与五项 profile 字段 |
| GET /api/profile/versions | profile.versions.read | {versions}，按 version 降序，limit 默认 50、上限 100，before 为可选排他上界 |
| GET /api/profile/versions/{version} | profile.versions.read | {school_id,actor_id,version,source,created_at,profile,form} |
| GET /api/profile/versions/current | profile.snapshot.read | 相同结构，供面试或匹配在开始时冻结，空简历返回 404 |

profile 以签名 school_id 与 actor_id 定位对象，两者均不接受请求体或路径覆盖。原生网关使用身份服务补全账户姓名、学号、学院，表单选项由 profile 服务按学校汇总。调用目录时，网关使用 `enrich_response` 只发送方向名，读取使用 record=False 和 catalog.enrich，生成使用 record=True 和 catalog.suggest 并按分析来源生成固定事件 ID。职业服务负责对同校同学生的重复事件去重。

表单投影、上传和个人资料更新与快照一同提交，每次实际变更产生一个不可修改的版本。分析结果关联资料版本、来源哈希和学校模型策略。上传解析始终在本地完成。文本文件使用 UTF-8，上传上限为 10 MiB。解析支持 TXT、MD、JSON、PDF、DOCX、PNG 与 JPEG，超过 12,000 字的文件正文会截断并返回原始字数。二进制解析在有限并发和 30 秒时限的子进程中运行，Linux 同时限制 CPU 和地址空间。文档大小、解包体积、PDF 页数/几何尺寸、图片像素数均有上限。

旧库无学校列时，迁移工具需先验证来源库的学校绑定，停写后调用 `store.ensure_schema(db)`、`store.import_legacy(db, school_id, actor_id, profile, form, resume_analysis)`。旧分析支持原始 analysis_json 行或序列化 analysis 字典。一次导入在单笔事务内创建版本 1 和分析缓存，遇到任何已有版本均返回 False，不覆盖后来的写入。导入网络端点未暴露。

## 网关与历史迁移

正常在线部署由 `services.gateway.student:app` 和 `services.gateway.admin:app` 接受浏览器会话并逐操作向 identity 核权，再用独立服务凭据委派至 profile。学生网关以 identity.student.read 查询 `/internal/students/me` 补全姓名、学号、学院。设置相关服务需配置 PROFILE_SERVICE_URL、CAREER_SERVICE_URL 和 IDENTITY_SERVICE_URL。快照 `/versions/current` 仅供服务间使用。

### 教学档案查看

学校管理员可在「学校管理」的职员授权中单独授予 `profile.student.read`。初始化主管、旧库迁移、账号名册读取和报告读取均不会自动发放此项权限。有权教职员在「学生账号」选取学生并点击「查看教学档案」，仅有档案权限时可按已知学生编号查看。

浏览器访问 `GET /api/admin/students/{student_id}/profile`。信任策略须允许 admin-gateway 将教师或管理员的 `profile.student.read` 委派给 profile，允许 profile 以相同学校、职员和角色向 identity 委派 `identity.student.authorize`。profile 每次读取前调用 `POST /internal/staff/authorize-student`，比对学校、职员、角色、目标学生和动作。拒绝访问返回 403，身份服务不可用返回 503，已获准但没有档案返回 404。成功响应禁止缓存。

响应中的 profile 只含 target_role、skills、education_level、project_experience 与 resume_summary。服务清理已知姓名、编号、联系信息、地址、链接等片段，并从经历提取有长度限制的职责、成果和时长。原始全文、文件名、学号、证书和历史版本不在该接口返回。访问结果写入独立简历库 profile_access_audit，包含学校、操作者与目标标识、角色、版本、结果与时间；可能含个人地址的非标准标识仅保存哈希，日志不记录资料内容。成功审计和查询同笔提交，提交失败返回 503。

### 学院与专业选项

profile 用学生的签名身份调用 identity 的 `GET /internal/resume-form/organization`（organization.options.read）和 career 的 `GET /internal/resume-form/catalog`（catalog.read）。两者返回同校的 `{school_id,colleges}`。合并时使用组织内启用的学院和专业，同名学院下没有专业才用发布目录补充，再用管理员配置补缺。服务断网或缺配置返回 503，返回的学校或数据结构不符返回 502，权限错误返回 403。此时不会用旧库或其他学校的设置填补。

管理 GET/PUT 使用 identity 的 `GET /internal/staff/resume-form-settings/read` 或 `/write` 复核同一账号的即时权限。教师或管理员持有读授权可以查看，写操作限有写授权的本校全校管理员。PUT 请求为 `{"colleges":[{"id":"c1","name":"计算机学院","majors":[{"id":"m1","name":"软件工程"}]}],"expected_revision":0}`。学院和专业名称各限 160 字，与学生保存表单时的上限一致。每级名称和编号不能重复。首次配置版本为 0，版本冲突返回 409，客户端应重新载入。旧客户端可省略 expected_revision。用空学院列表清空手工配置，组织与目录仍由各自服务维护。

`migrate profile` 会在迁移资料的同时从同一快照读取最近一次保存的 resume_form_settings。若旧管理端独立使用另一数据库，先把 LEGACY_SOURCE 配置指向管理端快照，运行 `python -m services.career.migrate profile-settings --school <学校编号>`，再从候选端快照迁移资料。导入在只读快照中核验所有带 school_id 的实体表，包括学院、专业、班级和学籍表；任一不符或缺失即拒绝。源库确实没有学校标记时仍须运维显式绑定单一学校。已有原生配置时跳过。同校组织数据通过 identity 的迁移导入，已发布目录通过 career 的迁移导入。

### 每所学校的模型选择

无授权时，简历分析与岗位匹配均在本地完成。管理员可在 profile 和 career 的部署环境分别配置 `PROFILE_MODEL_BY_SCHOOL` 和 `CAREER_MODEL_BY_SCHOOL`，例如 `{"school-a":"custom","school-b":"local"}`。学校 ID 精确匹配，未列出的学校继续使用本地规则。可选值为 `local`、`openai`、`qwen`、`kimi`、`deepseek` 和 `custom`。学校来自已验证的服务凭证，学生端只能请求生成或强制刷新。单校旧库的兼容路径使用 `LEGACY_SCHOOL_ID`；在没有对应学校映射的配置项时，也接受既有的任务专属单供应商选择 `RESUME_ANALYSIS_PROVIDER_ORDER` 或 `JOB_MATCH_PROVIDER_ORDER`。

外部模型的公开参数须从 `PROVIDERS_SERVICE_URL` 获取，工作负载须具备 `providers.runtime.read` 权限。推理服务保管自己的供应商密钥并检查 HTTPS 端点白名单，不能连接模型控制服务数据库。例如 custom 需配置 `AI_API_KEY`、`AI_MODEL`、`AI_BASE_URL` 并把该 URL 加入 `PROVIDER_ALLOWED_CUSTOM_ENDPOINTS`。内部 CA 可通过 `PRIVATE_MODEL_CA_FILE` 配置。每次最多发一次请求，禁用环境代理及跳转，返回体上限 128 KiB；`PRIVATE_MODEL_TIMEOUT_SECONDS` 默认 5 秒，上限 8 秒。每个进程最多同时发出 4 个私有模型请求。既有任务超时可进一步收紧总时限， `RESUME_ANALYSIS_MAX_TOKENS` 和 `JOB_MATCH_MAX_TOKENS` 可分别调低 1400 与 1200 的输出上限。

简历分析仅发送本地技能词典的命中项、职业方向名和从材料中识别的固定活动词。真实姓名、学号、联系方式、简历原文和文件名保留在本地。接口返回实际 provider、model 和 fallback。没有识别出可用证据、供应商响应无效、超时或请求容量已满时返回本地分析；已选择外部模型的后续 POST 可重试。无效的部署授权、缺少凭据或未获许可的 URL 返回 503。

分析开始时锁定资料版本并领取生成任务，在事务外发起 HTTP 请求。相同版本及策略正在分析时返回 409。写回前复核任务、资料版本及所选策略；切换模型或版本后，迟到响应无法覆盖新结果。已迁移的历史分析在本地默认策略下可复用，读取历史不会触发模型调用。

### 离线导入

离线导入命令适用于有明确单校归属的旧数据库。使用只读来源账号，暂停旧档案与招聘写入，在目标服务首次启动前运行。来源使用 LEGACY_SOURCE_DB_ENGINE 与 LEGACY_SOURCE_SQLITE_PATH 或 LEGACY_SOURCE_MYSQL_*，目标按各自服务的数据库配置定位。profile 启动与迁移前先只读核对结构，仅接受空库或只含已知 profile 服务表的库；指向单体库或混合库会在执行 DDL 前失败。命令要求 --school 与部署的 LEGACY_SCHOOL_ID 完全一致，遇到混校标记或无法确认归属的私有记录会停止。

```sh
python -m services.career.migrate profile --school "$LEGACY_SCHOOL_ID"
python -m services.career.migrate career --school "$LEGACY_SCHOOL_ID"
```

简历按学生导入版本 1，保留 ID、原表单和已有分析；重跑跳过已导入或已有新版的学生。职业数据导入空校库，保留目录关联、招聘、匹配、审核历史和原 ID。全部表复制和导入回执一起提交，重复运行返回之前的各表计数。切换前应将计数与停写源库核对。原生网关在服务地址缺失或服务不可用时返回错误。已产生原生新写入后，如需恢复旧部署，须先停写并回迁数据。

## 面试与媒体的接入边界

面试开场通过 `GET /internal/interview-context` 委派 profile.snapshot.read，按学校与学生只获取当前版本及提示词需要的分析字段。面试服务将这份内容与会话一起提交。没有简历时记录版本 0，已配置却不可达的服务返回不可用，不会静默使用旧库。后续问答、语音和报告读取已固定的内容；岗位匹配仍使用 `/api/profile/versions/current`。
