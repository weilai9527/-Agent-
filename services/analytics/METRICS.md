# 教学分析指标与定位

管理网关下的 `GET /api/admin/analytics/v1/teaching/summary` 和 `GET /api/admin/analytics/v1/teaching/weaknesses` 使用 `analytics.teaching.read`。两者都接受 `class_id, task_id, job_role, dimension` 筛选。学校从签名身份获取，每次读取都与身份服务的当前班级和学生名单求交集。教师还须是冻结任务的负责教师。学生仅可用 `analytics.self.read` 从 `GET /api/analytics/v1/me/weaknesses` 读取本人数据。

## 样本与覆盖

顶层和 `by_task, by_class, by_job, by_dimension` 使用相同口径。只计入已由训练服务核验完成、且收到评估服务评分事件的尝试。每次尝试以最新版本全量快照为准。

| 字段 | 计算方式 |
| --- | --- |
| `attempts` | 当前范围内的不同尝试数。一名学生重做任务会产生新的尝试。无维度过滤时包含提交空评分快照的尝试。 |
| `scored_attempts` | 其中至少一题有有效维度评分的尝试数。有效评分的零分也计入。 |
| `valid_attempts` | 该尝试的所有冻结原题各有至少一项有效评分。 |
| `insufficient_attempts` | 已知冻结题数，缺一题或多题评分，包括整份任务没有评分。 |
| `unknown_coverage_attempts` | 历史投影缺少权威冻结题数。与有效、覆盖不足两类相加等于 attempts。 |
| `completed_questions` | 当前筛选下，有效评分的「尝试、原题」唯一组合数。 |
| `average_score` | 先在一题内平均匹配维度分，再平均这些题分。包括部分覆盖和历史未知尝试中的已评题，无已评题返回 null。 |

维度分组或维度筛选只包含该维度有观察记录的尝试。有效、覆盖不足和未知的判定仍使用该次尝试所有冻结原题和所有维度。上述分母不代表班级总人数、布置任务人数或全部参训者。

## 班级薄弱项与复核

`summary.class_weaknesses` 按班级和维度汇总，列出至少一题该维度得分低于 60 分的组合。`weak_questions/scored_questions` 为该班该维度薄弱题次占有效评分题次的比例，题次按尝试与原题去重。`affected_students` 按薄弱学生去重。`average_score` 包含该班该维度的全部有效评分。

弱项明细提供 `task_id, attempt_id, question_id, question_text, original_answer, interview_id, version`。报告通过 `GET /api/admin/interviews/{interview_id}/report-reference` 解析，评估端另行核验报告读取权限。旧投影的 interview_id 可能为 null，收到该尝试的下一次已验证投递后可补齐。班级薄弱项原回答和复练受同一当前可见范围约束。

新增的 `analytics_attempt_context` 从训练服务的权威尝试保存面试 ID 与冻结原题数，服务启动时幂等建表。旧写入端可继续使用已有表，读取端保留历史分数，对缺少上下文的行显示未知覆盖。回放已投递的同一事件可补齐上下文，评分版本不变。
