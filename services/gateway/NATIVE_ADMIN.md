# 原生管理网关

入口为 `services.gateway.admin:app`。在受管部署中执行 `python -m deploy.run_service admin-gateway --check` 检查环境，再按相同的运行环境启动网关。原生模式设置 `IDENTITY_SESSION_MODE=native`、网关绑定的 `LEGACY_SCHOOL_ID`、`ADMIN_FRONTEND_ORIGIN`、`IDENTITY_SERVICE_URL`、网关签发凭据及所用业务服务的内部地址。生产身份服务地址须使用 HTTPS。原生网关不读取业务数据库，也不使用旧管理登录 cookie。

## 请求边界

- 登录、会话、快照、组织与人员授权通过 identity。快照只暴露当前角色获准的功能，读取或修改业务对象时重新核验当前会话和动作。
- 训练、教学分析、版本化评分与复核、证书和学校配额使用固定的代理路由。允许的方法和下游动作见 `routes.py` 及 `compatibility.py`。网关内部授权令牌不会返回给浏览器。
- 职业目录、招聘岗位、JD 及匹配记录保留原浏览器 URL。涉及学生的名单由网关使用 identity 的 `identity.classes.read` 和 `identity.roster.read` 生成，然后连同该次调用的身份送入 career。浏览器提供的学校、用户标识和名单不参与授权。Excel 上传可按实际字节拒绝超限文件，解析和数据库写入由 career 服务完成。
- 平台模型配置仅在 identity 认证的 `platform` 学校域中开放；平台管理员 ID 必须同时列入网关与 providers 的部署白名单 `PROVIDER_PLATFORM_ADMIN_IDS`。读取需要 `model.config.read`，修改及连通性测试需要 `model.config.write`。下游 grants 分别为 `providers.read`、`providers.configure`、`providers.diagnose`。普通学校的管理账号不能因为同名或持有校内模型配置权限而被改写为平台账号。部署网关无须注入供应商或存储密码。

## 学校面试和报告记录

“记录与质检”中的“学校面试记录”和“学校报告记录”可查看自主练习和教学训练。教师及限班管理员只能读取当前所负责班级的在册学生。具备相应读取权限的全校管理员也可以查看未分班的正常学生。班级变动、停用或撤权在下次列表与详情请求时生效。仅负责人可以通过原有评分命令调整成绩。

| 管理入口 | 人员权限 | 网关到业务服务的授权 |
| --- | --- | --- |
| `GET /api/admin/interview/v1/records` 及 `/{record_id}` | `interview.records.read` | interview 的 `interview.records.read` |
| `GET /api/admin/assessment/v1/records` 及 `/{record_id}` | `report.read` | assessment 的 `assessment.records.read` |

两项服务都需要到 identity 的 `identity.records.scope` 动作，放行角色为 teacher、admin。旧库首次迁移将 `viewInterviews`、`viewReports` 分别映射为对应读取权限。已切换学校的管理员可以在人员授权页补授新增的面试读取权限。

列表接受 `q`（姓名或学号的字面子串）、`class_name`（班级名称子串）、`student_id`、`class_id`、`kind=practice|training`、`limit=1..50` 和 `cursor`。结果按学生和记录编号稳定排序。身份服务每批至多处理 100 个匹配学生。空页仍可能提供 `next_cursor`，为空时才表示结束。游标校验服务签名、学校、操作者及筛选条件。面试详情每页返回 20 条历史问答。报告详情返回当前版本的可展示成绩、复核状态、摘要及建议。原生评估的报告列表读取本域已经接收的投影及报告。

## 验收

```sh
python -m pytest -q services/gateway/test_native_admin_routes.py services/identity/test_staff_adapter.py services/career/test_admin_adapter.py
python -m pytest -q services/gateway/test_native_admin.py
```

第二条命令使用临时源码副本、生成的签发凭据、合成名单和三个真实本机 HTTP 进程。它在管理网关进程禁止 SQL 与旧业务模块导入，覆盖原生登录、跨班拒绝、XLSX 导入导出、管理授权隔离及 career 停机。如果执行环境禁止监听本机端口，应在可监听的测试机上运行。
