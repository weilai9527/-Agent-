# 面试平台的微服务运行边界

本文描述重构版的服务边界和部署要求，不表示生产已完成切换。旧版维护与微服务开发分开管理；服务器日常更新、补丁移植、正式迁移及回退约定见[分支管理、服务器更新与微服务切换](RELEASE-WORKFLOW.md)。在微服务验收完成前，旧版服务器继续按已验收的旧版发布标签更新。

在代码库根目录执行 `python -m deploy.run_service list` 查看当前 HTTP 服务、端口、Worker 及其执行身份。在独立 Python 环境安装 `deploy/requirements.txt`。正式运行包由 services、shared、deploy 构成，两个旧后端目录均可从发布包中剔除。每个运行单元用自己的环境调用 `python -m deploy.run_service <name>`，并由进程管理器监管。默认监听回环地址。跨主机访问使用部署方的 HTTPS 入口。

## 服务边界与故障影响

| 业务归属 | 持有的数据和决定权 | 依赖中断时的行为 |
| --- | --- | --- |
| identity | 学校、班级、账户、会话、教师授权和当前名册 | 无法确认授权时拒绝受保护的请求 |
| profile、career | 前者持有简历和分析，后者持有职业目录、岗位和匹配结果 | 按学校显式选择外部模型，默认在本地处理。面试使用开场时冻结的简历上下文 |
| training、interview | 前者持有任务、负责教师、下发时的名单和尝试，后者持有会话、题目和作答 | 提交答案与登记投递事件同事务。评估恢复后继续，重复提交沿用原答题结果 |
| assessment、analytics | 前者持有评分证据、报告版本和复核记录，后者按可见班级消费完成事件，生成教学统计和复练依据 | 报告未就绪时显示处理中。没有样本的班级不借用其他班级数据 |
| media、usage、providers | 媒体会话和短期授权、学校配额和结算、模型配置分别归属三个服务 | 媒体中断保留文本作答。付费任务无法确认额度或上次派发结果时等待核对 |
| credentials、provenance | 前者负责学校签名、证书状态及撤销，后者负责锚点投递、交易回执和确认 | 存证中断仍可撤销证书。公开验真区分业务状态与链上确认状态 |

一次教学任务的主线为「教师下发 → 学生作答 → 评估生成版本 → 负责教师改分或复核 → 教师审核证书申请 → 签发 → 异步存证」。报告复核和证书审核分别授权。签发许可与改分使用同一个报告锁；重试时按申请、证据版本、签名摘要和证书序号核对。

视频面试可通过 media 接入视频会话、授权与录制，将可供评分的证据引用交给 assessment。视频对象、播放授权和保存期限单独管理。学生记录、原始音视频、简历正文和评分明细留在链下。

## 学校数据保存与恢复

切换前，学校需区分教学档案（任务、答案、评分历史、审核、证书与撤销）、原始材料（简历、音视频）和运行数据（会话令牌、临时媒体授权、技术日志）。教学档案按学校的长期保存意向设计。原始材料的保存年限、访问人和删除审批由学校确认；临时凭据按有效期失效。正式证明的签章主体和用途单独确认，当前流程按教学证书验收。

生产运维应按同一个停写点或可回放水位，备份各域数据库、媒体对象清单、迁移清单、证书历史公钥及撤销状态，加密并隔离保管。恢复演练时先隔离模型和链提交出口，再核对任务尝试、报告版本、教师审批、证书序号与撤销状态，确认消费水位后才重启投递。学校决定备份频率和允许恢复时长。

新学校先在 identity 的专属环境设置 `SERVICE_ID=identity`、`LEGACY_SCHOOL_ID=<学校>` 和 `IDENTITY_DB_ENGINE`、数据库连接。运行 `python -m services.identity.bootstrap --school <学校> --email <校管邮箱> --name <校管姓名>`，按提示设置口令，再通过管理网关创建老师、组织和名册。该命令不会覆盖已有职员；导入旧学校则走停写、备份及分域迁移流程。[旧框架只读应急操作](EMERGENCY.md)与初始化使用不同身份和入口。

运营审计与 RTC 历史查询由独立 operations 服务持有，端口为 8114。每个网关使用自己的 `OPERATIONS_JOURNAL_DIR` 持久卷保存尚未投递的脱敏事件。生产环境按 [诊断与安全审计](../services/operations/INTEGRATION.md) 配置服务签名、目的地和数据范围。

## 权限和数据

- 公网只路由两个业务网关及证书的公开验证端点。身份的内部会话解析、训练完成事件、评分证据、配额预留和存证提交仅向对应服务开放。
- 内部调用使用 Ed25519 签发的短期凭据。每个进程单独配置 `SERVICE_ID`。调用方还需要自己的 `SERVICE_KEY_ID` 和 PEM 格式的 `SERVICE_SIGNING_KEY`，接收方通过 `SERVICE_TRUST_POLICY` 校验调用者、公钥、目标服务、学校、角色和具体动作。信任配置示例结构如下，实际公钥由部署环境提供。

```json
{
  "student-gateway": {
    "keys": {"k1": "<Ed25519 public key PEM>"},
    "schools": ["school-a"],
    "grants": {"training": {"student": ["training.read", "training.start"]}}
  }
}
```

- 将同一身份的旧公钥保留至现存凭据过期，再完成轮换。服务接线使用受控的 `<SERVICE>_SERVICE_URL`。应用发出的请求仅认可固定目的地；每个服务仍需独立校验资源所属学校和负责人。密钥仅注入使用它的进程。学校签名私钥、链交易提交凭据和模型密钥分别管理。
- 新业务库使用服务专属配置，例如 `TRAINING_DB_ENGINE=sqlite` 配绝对路径 `TRAINING_SQLITE_PATH`，或 MySQL 专属账号与预建 schema。面试和评估分别使用 `INTERVIEW_*` 和 `ASSESSMENT_*` 专库配置，默认独立存储，两端和 Worker 共用本域配置。面试在本地事务登记带序号的投影事件；评估在自己的库消费证据、评分和保存复核版本。为 assessment 单独配置 `ASSESSMENT_DB_ENGINE` 和对应专库地址，切勿传入面试源库。正常进程拒绝 shared。历史数据在经核对的冷副本上迁入服务专库；`LEGACY_SCHOOL_ID` 是沿用的学校绑定变量名，不能开启旧应用。
- 教师改分与证书审核属于不同授权动作。应将教师绑定到真实任课/任务关系，保留原分、新分、理由、操作者及证据版本。存证关闭或未确认时，公开页面仍读取证书当前撤销状态。

## 运行与验收

本地可按[空学校启动手册](NATIVE-LOCAL.md)生成独立配置；学校部署可按[分域 MySQL 计划](NATIVE-MYSQL.md)先由 DBA 审核。旧管理能力归属见[82 条历史入口对照](NATIVE-COVERAGE.md)。

1. 为各域配置隔离数据库、接入地址与最小公钥信任。在生产环境将实际秘密保存在部署系统中。新服务尚无配置时不应将业务流量导入该域。
2. 使用各域的迁移命令在备份的只读旧库副本上核对结果。按学校切换身份数据源时统一登录、组织、授权和学生侧入口。单校旧库不可承接来自其他学校的令牌。
3. 启动业务服务、`interview-events`、`assessment-jobs`、`credential-relay` 和 `chain-worker`。仅模型运维控制服务使用平台管理员白名单 `PROVIDER_PLATFORM_ADMIN_IDS`。真实视频与链操作需配置获准的供应商。测试替身仅用于验收。
4. 运行两个网关和现有 Web 客户端。学生从“我的”进入班级任务或证书；教师按独立授权访问教学任务、复练、评分历史与发证。网关向下游重新签发身份，不转发浏览器提交的角色头。
5. 使用 `python scripts/smoke_microservices.py --assessment-mode isolated` 在独立临时目录和回环端口执行合成学校场景。使用 `python scripts/check_mysql_services.py --mysqld /path/to/bin/mysqld` 临时启动 MySQL 8，验证各域以独立账号首次建表及重启；该脚本需要本机回环和 OpenSSL，不接收外部数据库 DSN。测试密钥、模拟模型与测试数据不用于实际部署。集中开考容量和生产云端性能另行实测。

正式切换前对各进程执行 `python -m deploy.run_service <name> --check` 核对身份、敏感配置的归属和面试/评估存储绑定。不传模式配置时网关就是 native，评估就是 isolated。显式 legacy 或 shared 会被拒绝。原生网关环境不传业务 SQL 密码及文件路径。生产独立评估服务和 Worker 均需注入用量服务地址。已有 MySQL 库另用只读账号逐列检查学校、人员和对象标识，见 [MySQL 身份标识检查](MYSQL-IDENTIFIERS.md)。预检通过后仍需以实际受限账户完成启动及业务验收。

开发回归使用 `python scripts/check_release.py` 从临时源码副本运行 Python 套件，不加载工作区的部署配置。证书故障演练可用 `python scripts/smoke_microservices.py --assessment-mode isolated --crash-issuance`，在取得签发许可后终止临时签发进程，验证重启后仍使用原序号。已执行项目及生产待办见 [验收记录](ACCEPTANCE.md)。

各服务的接口、作用域和故障语义见 [身份](../services/identity/INTEGRATION.md)、[简历](../services/profile/INTEGRATION.md)、[职业目录与匹配](../services/career/INTEGRATION.md)、[教学与分析](../services/training/INTEGRATION.md)、[面试](../services/interview/INTEGRATION.md)、[评估](../services/assessment/INTEGRATION.md)、[媒体](../services/media/INTEGRATION.md)、[用量](../services/usage/INTEGRATION.md)、[证书](../services/credentials/INTEGRATION.md) 和 [存证](../services/provenance/INTEGRATION.md)。

配置 `PROVIDERS_SERVICE_URL` 后，模型调用进程通过 `GET /internal/runtime-settings` 读取其获准的非敏感参数。控制服务的信任配置为每个调用方单列公钥、受众 `providers`、学校 `platform`、角色 `system` 和动作 `providers.runtime.read`。机器令牌的主体必须等于其工作负载名。网关不能使用这个接口。学校范围的业务令牌不混用平台身份。

只有控制服务持有 `PROVIDERS_DB_ENGINE` 和对应数据库连接配置。调用方的供应商密钥由自身部署环境注入。管理端修改模型后，工作负载在短缓存到期时向控制服务读取新配置；已配置控制服务但无法取得有效配置时，调用暂停。

MySQL 切换前应逐列检查库内实际租户与主体标识，详见 [MySQL 标识校验与已有库切换](MYSQL-IDENTIFIERS.md)。
