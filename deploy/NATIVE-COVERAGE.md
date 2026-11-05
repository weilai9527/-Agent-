# 旧管理 API 的原生业务归属

以离线历史管理夹具 [82 条历史 HTTP 方法和路径](../admin_backend/offline/main.py) 为盘点底稿。表内数量按方法计数，同一路径的 GET、POST 分开。日常入口为 [原生管理网关](../services/gateway/native_admin.py)，判断功能是否迁出需看实际数据所有者和正式管理页面；应急应用中保留旧实现不代表正常运行会调用它。

|原接口族（省略 /api/admin 前缀）|数目|日常归属及人工复查点|
|---|---:|---|
|health|1|管理网关自身对外健康检查；各域单独提供就绪检查。|
|auth/login、auth/me、auth/logout|3|identity 签发和注销职员会话，网关代理浏览器 HttpOnly Cookie。已撤权角色不能依靠旧会话切换认证源。|
|campus/overview|1|工作台从 identity 取得真实组织、账户及待办，面试和评估记录分别由对应服务给出按权限统计。|
|campus/colleges、programs、classes 的新增/修改/删除，campus/structure/import，organization/structure、organization/import|12|identity 的组织树、逐层说明、实名任教关系及组织导入；变更和停用按学校事务写审计。班级邀请码及辅导员姓名不作为教师权限。|
|campus/program-jobs、campus/programs/{id}/jobs|2|career 持有专业与已发布岗位映射，单独向 identity 核对当前学校和组织授权。|
|campus/students/{id}、campus/students/import|2|身份域名册维护、导入和归班。正式页面在“学校管理”使用已验证的学校、班级与学生标识。|
|student-registrations 的单条登记、批量导入、查询、开通、单条/批量撤销登录、单条/批量清册|8|identity 的登记名册。JSON/XLSX 增量导入，查询后选择对象开通、更新、撤销、归档或恢复。生命周期与学业档案分离，撤销登录或归档名册不能删除历史成绩。|
|resume-form-settings 的读取与保存|2|profile 负责表单配置，组织与岗位选项分别由 identity 和 career 提供。|
|job-postings（8）、job-matches（2）、jd-submissions（5）、catalog 目录版本/实体/岗位能力/发布和建议审核（13）|28|career 负责岗位、工作簿、安全导入导出、发布、匹配和 JD 审核。匹配记录与学生 JD 依当前学校/名册授权。网关保留原浏览器合同，供应域失败时不切入旧处理函数。|
|connection-logs、security-logs|2|operations 独立保存受控 RTC 和审计事件；旧快照离线脱敏迁入。查看日志先查当前授权和名册，平台全域审计另需 allowlist。|
|snapshot|1|由原生身份会话返回页面能力；学校工作台向各所有者读取汇总，目录与模型配置依角色加载。旧单库的跨表快照不作为运行数据源。|
|student-accounts/import、export、temporary-password、reset-password|4|identity 处理账户状态、开户和重置，登记名册支持按辅导员筛选、XLSX 和一次性发放单打印。查看历史明文密码改为作废原密码、生成新密码并重新发放，不从原档案解密旧密码。|
|candidates/{id}|1|账户与当前组织信息属 identity，个人简历和求职偏好属 profile。由 [profile 教学视图](../services/profile/teaching_view.py) 在当前名册授权与访问审计后返回教学所需投影；账户维护权限不能派生读取整份简历的权限。|
|interviews/{id}|1|interview 提供训练及自主练习详情，问答、状态和当前学生归属由服务核验。|
|reports/{id}、export、review|3|assessment 持有报告详情、导出、版本和复核。只读、导出、改分、复核分别授权。证书签发另走 credentials，载明关联版本。|
|agents/{name} 和快照中的模板榜单|1|interview 从实际创建的 Agent 实例汇总名称、类型、职责、策略与使用次数。单独授予 interview.templates.read；显示最近使用的面试和学生时，identity 还要核对 interview.records.read。|
|users 的列出、创建和修改|3|identity 管理职员身份、当前授权及班级范围，可停用并使会话失效。更名和密码重新发放独立授权，不能用改资料动作提升权限。|
|permission-requests 的申请、查阅和审批|3|identity 自助申请和校级审批；迁入的旧申请只读。禁止自批，失效授权快照需重新申请。|
|interviewer-policy 读取与保存|2|interview 按校管理默认策略，修改记录审计；已建面试保留其策略快照。|
|settings PATCH、settings/report-providers/test|2|providers 维护已批准的非敏感参数和连通性探测；平台域运维会话与学校教务会话隔离，供应商密钥由工作负载部署注入。|

## 界面与导出边界

正式管理端是 `admin/`。其旧工作台没有单独“导出全校大屏”的后端路由。原有实际下载分别是报告、招聘工作簿和账户发放相关材料，应从相应业务页面验证。原型 `admin-next/` 的浏览器本地数据不能补充正式页面的数据。

- 原生日志检索和历史导入见 [运行诊断文档](../services/operations/INTEGRATION.md)。核对 RTC 历史时应查看面试号、学生及状态；测试须确认自由文本、令牌和原始信令不进入新库。
- 面试官模板见 [模板汇总](../services/interview/template_usage.py) 与 [正式管理页](../admin/src/NativeAgentTemplates.jsx)。模板权限不能访问逐场使用明细，教师撤出班级后再次打开详情须重新授权。
- [学校资料和职员管理](../services/identity/INTEGRATION.md)、[简历](../services/profile/INTEGRATION.md)、[职业目录](../services/career/INTEGRATION.md) 及 [报告](../services/assessment/INTEGRATION.md) 负责各自权威记录。
- 学生公开自助注册和绕过学校核验的自助重置路径保持关闭。正式开通、撤销和密码重新发放走身份服务，不向前端提供历史明文密码、签发私钥或链交易凭据。旧兼容入口不作为业务故障时的自动重试目标。
