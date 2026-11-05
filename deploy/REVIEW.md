# 原生运行边界人工核对索引

本轮调整的验收条件是：删去两个旧后端目录后，新学校仍能开户并完成教学流程；任一微服务故障不会激活旧版账号或写入路径。校方应急授权仅允许查询冻结快照的时间、报告数量和生成／复核状态。

| 核对问题 | 建议打开的实现 | 应观察到的行为 |
| --- | --- | --- |
| 日常到底启动哪个框架 | [启动契约](../shared/runtime_mode.py)、[学生网关](../services/gateway/student.py)、[管理网关](../services/gateway/admin.py)、[进程注册](run_service.py) | 未指定模式时走原生网关与独立评估库。显式 legacy/shared 在正常启动、加载持久化模块之前失败。 |
| 新学校有没有隐含旧账号依赖 | [开校命令](../services/identity/bootstrap.py)、[组织与名册接口](../services/identity/INTEGRATION.md) | 初始校管一次创建，不能覆盖已有职员；登录后经原生管理网关创建班级、职员并开户。 |
| 老业务都去了哪里 | [旧管理 82 个接口与原生能力对照](NATIVE-COVERAGE.md)、[学生网关](../services/gateway/native_student.py) | 按业务能力查对应的页面、权限和持有数据的服务。敏感的旧密码回显改为有审计的一次性发放。 |
| 作答、改分和审批谁能写 | [面试运行时](../services/interview/runtime.py)、[评估运行时](../services/assessment/runtime.py)、[报告版本](../services/assessment/versions.py)、[签发](../services/credentials/app.py) | 答案与待投递事件同事务。评分只写评估库；负责教师修改有版本保护。证书审核绑定报告版本；进程重启不能产生第二张证书。 |
| 故障时是否回去写旧库 | [内部 HTTP](../shared/service_http.py)、[作业队列](../services/interview/jobs.py)、[用量结算](../services/usage/TEXT.md)、[诊断与审计](../services/operations/INTEGRATION.md) | 受保护调用在权限不足、来源不可达时拒绝或显示等待；媒体故障时学生可继续文本作答。模型额度不足时保留答案与待办；审计需按确认回执重投。 |
| 旧代码会不会被直接挂回线上 | [学生旧入口](../backend/src/main.py)、[管理旧入口](../admin_backend/src/main.py)、[离线夹具保护](../shared/offline_fixture.py) | 旧 ASGI 入口拒绝启动。历史回归用独立解释器、固定的合成库和进程内客户端；网络服务器不能用夹具受理登录或写业务。 |
| 救援时能看什么 | [只读服务](emergency.py)、[快照与工单](emergency_prepare.py)、[操作步骤](EMERGENCY.md) | 校验真实学校、摘要和表结构。口令只对应一个工单，最长一小时；撤回或过期后拒绝。服务没有审批私钥和业务库权限。 |

## 可复跑的验收

在仓库根目录执行。使用临时学校、合成口令和回环测试供应商，人工审核时不需要接触真实学校数据。

```sh
python -m deploy.run_service list
python scripts/check_chinese_comments.py
python scripts/check_release.py
python scripts/smoke_microservices.py --crash-issuance --restore-drill
python -m services.usage.smoke_worker_usage
python scripts/check_mysql_services.py --mysqld /path/to/mysql/bin/mysqld
```

`check_chinese_comments.py` 从 Git 源码清单读取注释，Python 用 tokenize/AST 处理，JS/JSX 使用项目依赖中的 Babel 解析器；多行说明逐行检查。它列出需要人工核对的文件和行号，保留解释器、许可证、静态检查等机器指令。它只能检测语言覆盖，授权条件、并发顺序和失败行为是否描述准确，仍需结合上表的代码与实际测试核对。

正式服务本地试用见[空学校启动手册](NATIVE-LOCAL.md)。签名学校、跨服务配置、生产前置条件见[部署说明](MICROSERVICES.md)。本地验证记录见[验收记录](ACCEPTANCE.md)。
