# 评估服务与报告版本

正式环境通过 `python -m deploy.run_service assessment` 和 `python -m deploy.run_service assessment-jobs` 启动，两个进程使用同一个评估专库。评估读取面试服务投递的证据；不安装旧登录、学生资料、岗位和 RTC 数据表。历史迁移与专库参数详见[面试切换说明](../interview/INTEGRATION.md#正常运行)。

评估 HTTP 服务需 `SERVICE_ID=assessment`、`SERVICE_TRUST_POLICY`、`SERVICE_KEY_ID`、`SERVICE_SIGNING_KEY` 和 `TRAINING_SERVICE_URL`。训练服务要接受 assessment 代教师或管理员调用 `training.verify`。内部 URL 用 HTTPS，回环地址可用 HTTP。独立 Worker 须按本机职责配置评分模型及对应的服务身份。面试 Worker 通过 `TRAINING_SERVICE_URL` 以 system 权限 `training.complete` 投递训练完成事件，评估 Worker 通过 `ANALYTICS_SERVICE_URL` 以 system 权限 `analytics.completion.write` 投递教学分析事件。两进程分别使用与其 `SERVICE_ID` 对应的签名密钥。

| 接口 | 委派身份 | scope |
|---|---|---|
| GET /api/interviews/{id}/evaluations、/report、/report/download；GET /api/reports、/api/reports/{id} | 本校学生本人 | assessment.read |
| POST /api/interviews/{id}/evaluations | 本校学生本人 | assessment.evaluate |
| POST /api/interviews/{id}/report | 本校学生本人 | assessment.generate |
| GET /api/admin/reports/{id}/history | 负责教师 | assessment.history |
| PATCH /api/admin/reports/{id}/score | 负责教师 | assessment.score |
| PATCH /api/admin/reports/{id}/review | 负责教师 | assessment.review |
| POST /internal/credential-evidence/{id}/authorize | 仅 credentials 委派有资格签发或补发的教师、管理员 | assessment.credential-authorize |
| GET /internal/credential-evidence/{id} | 仅 credentials 委派本人或经教学服务核验的教师、管理员 | assessment.credential-evidence |

网关应将浏览器的旧报告路径映射到这些端点。下载需转发 Markdown 字节及 Content-Disposition。历史接口返回 `report.version`、不可变 `versions` 及按版本保存的 `reviews`。改分示例为 `{"expected_version":2,"total_score":86,"reason":"核对项目实现与评分标准"}`，复核示例为 `{"expected_version":3,"status":"approved","note":"已核对回答证据"}`。409 需刷新报告。总分调整同时更新等级及推进建议，单题评分保留其原始依据。每次新发布或改分都会生成待复核版本。旧复核仍可在历史中查阅。若模型暂不可用，Worker 可保留降级摘要，并在模型恢复后以同一证据发布一次成功版本。已有复核记录或教师改分的版本会保留。

证书查证在会话及报告锁内读取已成功发布、全题有据且与当前证据一致的版本，返回 `{report_id,interview_id,student_id,school_id,version,digest}`。教学负责人关系来自 `GET /interviews/{interview_id}/attempt`。缺失训练绑定、教师不再负责或教学服务不可用时，教师操作失败。独立读写权限在身份服务与网关配置，旧管理接口的写入也必须经过本服务。

assessment_issuance_permits 记录每份申请每个代次的签发许可。服务在与改分一致的会话/报告锁中比较当前版本和依据摘要；许可提交是判定签发与改分先后的依据。重复的申请代次必须提交同一个序号、版本、证据及签名产物摘要，才能取回已提交的许可。旧报告改分后仍可恢复已提交许可，未获许可的旧版申请返回 409。将此表与报告版本一同备份。

## 证书集成测试的报告样例

在隔离 SQLite 中建立一条主问题消息，再建立一条 `reply_to_message_id` 指向该问题的候选人回答，例如 `row lock`。评价行的 `message_id` 指向回答，`generation_status=succeeded`、`fallback=0`，使用测试模型标识与当前 `EVALUATION_PROMPT_VERSION`。将 `dimension_scores` 设为 `{"technical_depth":80}`，`dimension_evidence` 设为 `{"technical_depth":"row lock"}`，每条引文均摘自原答。面试完成后用测试替身返回成功的报告摘要，调用 `POST /api/interviews/{id}/report` 并从响应取实际报告 ID。该发布路径会一并生成时间线、版本、证据 head。可执行样例见同目录 `test_assessment.py`。

直接插入 `timeline_review='[]'`、再设置 `scored_answer_count=answer_count=1` 的报告缺少原题、原答和逐维引文。证书查证应返回 409，此数据适合作为拒签样例。成功签发用例需要以上发布流程。

## 独立存储

评估进程按 `ASSESSMENT_DB_ENGINE` 和 `ASSESSMENT_SQLITE_PATH` 或 `ASSESSMENT_MYSQL_*` 连接预建专库，SQLite 路径必须为绝对路径。它不会使用面试服务的连接，也不接受共享存储开关。首次必须是空库，此后检查既有的学校绑定标记。模型调用在 SQL 事务外执行，按学校配额预留和结算。

面试提交作答时同步登记投递事件。评估服务通过 `POST /internal/interview-projections` 核对签名学校、面试编号、学生、序号和摘要；乱序事件等待重试，冲突的重复事件拒绝，匹配回执才确认投递。教师在评估库查看的记录与签发服务核验的不可变版本共享同一事务边界。

## 历史切换

停写原系统，核对影子账号归属，排空评分和未确认用量，请按[只读源迁移说明](../interview/INTEGRATION.md#正常运行)将冻结记录导入新面试库。等待所有历史投递完成，逐校核对原报告编号、作答数、评分版本、教师复核和签发许可，再开放新系统写入。签发许可按学校、学生、报告、代数与摘要校验；旧清单曾遗漏许可时，按上一份清单摘要追加回填，避免覆盖随后形成的有效评分。
