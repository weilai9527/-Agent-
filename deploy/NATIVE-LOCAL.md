# 从空目录启动本地单校原生系统

适用于单机人工审查和教学演练。启动器使用 SQLite、每进程独立的环境和本机回环端口。它不读取项目的 .env，不继承 shell 中的数据库/供应商/应急凭据，也不依赖烟测脚本或历史快照。下列命令在仓库根目录运行。已实测 macOS；需要支持项目依赖的 Python、Node.js、npm 和空闲的本机端口。

## 1. 安装与初始化

使用专门的虚拟环境。必须用安装过依赖的同一个 Python 启动，子进程会沿用它。请勿把依赖只装到临时 PYTHONPATH 中。

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r deploy/requirements.txt
npm ci
npm --prefix admin ci

# 目录必须在仓库外且此前不存在；重跑 init 不会覆盖已有密钥。
state="$HOME/.local/share/interview-school-demo"
python -m deploy.local_native --state "$state" init --school campus-demo
python -m deploy.local_native --state "$state" check
python -m deploy.local_native --state "$state" bootstrap --email manager@campus.test --name '演练校管'
```

最后一条命令交互读取不少于 12 个字符的临时管理员口令。如运维在封闭终端自动化执行，`--password-stdin` 从受保护标准输入读取。空身份库只能初始化一次，工具不能覆盖已有职员。记住刚输入的口令，后续从管理页面登录。

实例目录中的 `instance.json` 保存学校编号与公钥。`keys/` 下分别保存每个调用进程的本机 Ed25519 私钥和本机教学证书私钥；文件权限 0600，顶层目录 0700。学校编号不可用于建立平台管理员实例。已有实例重启使用同一目录，重建签发密钥会影响历史证书验签。

## 2. 启动服务与页面

**后端终端**保持运行，按 Ctrl+C 同时停止本次监管器启动的进程。

```sh
python -m deploy.local_native --state "$state" up
```

启动器先检查端口冲突，再调用 [逐进程启动器](run_service.py) 启动 13 个领域/支撑服务，等其就绪后启动 2 个网关、1 个只读验真入口及 3 个本地 Worker。服务全都绑定 `127.0.0.1`。遇到启动失败或工作进程意外退出时停止本次栈，日志在 `$state/logs/`，可修复后重启，不会启动应急服务。

**学生页面终端**和**管理页面终端**分别执行下列一行。

```sh
VITE_API_BASE_URL=http://127.0.0.1:3001 npm run dev --workspace frontend -- --host 127.0.0.1 --port 5173 --strictPort
```

```sh
VITE_ADMIN_API_BASE_URL=http://127.0.0.1:3002 npm --prefix admin run dev -- --strictPort
```

浏览器分别访问 `http://127.0.0.1:5173/` 与 `http://127.0.0.1:5174/`。请保持主机名及端口一致；前端来源、Cookie 和跨域检查以这两个地址配置。公开证书入口为 `http://127.0.0.1:8113/verify/<序号>`。

## 3. 空学校核验

1. 在管理页面用刚初始化的校管登录，进入“学校管理”。创建学院、专业、班级，创建教师并明确授予组织读取、任务读取和布置任务权限。把教师加入目标班级任课名单。
2. 导入合成学生名单并开通账号，保管本次的临时密码发放单，将该学生加入班级名册。
3. 使用独立浏览器会话以教师身份登录管理端。确认只能看到被分配的班级与学生，在教学任务中选择该班级、填写题目及截止时间并下发。
4. 学生从学生页面使用学号和初始密码登录，按要求修改密码。在“我的”中的班级任务核对教师下发的任务。以未获该班级授权的教师再次请求管理记录，应被拒绝或只返回其可见范围。
5. 校管可在“安全审计”按 `admin.login` 查登录审计。刚启动时网关的脱敏事件可能正在从 `journals/` 送达，请稍后刷新。

该实测链路使用真实 Cookie、身份存储、HTTP 签名及独立训练库。它不要求云端模型、RTC 供应商或真实链凭据。空校尚未配置付费调用额度时，工作任务可能等待学校配置；外部调用无有效配置时，页面呈现不可用或等待状态。合成演练不设置学校正式证明签章，不模拟真实链确认，不启动 `chain-worker`。原生凭证转发器可以把待处理摘要交给 provenance，确认要靠经批准的实际链后端与交易账户。

## 4. 人工审查服务信任

```sh
python -m deploy.run_service list
python -m deploy.local_native --state "$state" policy identity
python -m deploy.local_native --state "$state" policy providers
python -m deploy.local_native --state "$state" policy provenance
```

[授权清单](local_grants.py) 显式列出“调用进程 → 接收服务 → 角色 → 动作”。每个服务收到自己的入站公开策略及真正需要的下游服务地址。机器读取非敏感模型配置的声明绑定 `platform`、角色 `system`、程序自身和 `providers.runtime.read`，不授予任何学校用户修改平台模型或读取其他学校数据的权力。本机学校没有平台配置写授权。

同一领域的 API 和 Worker 使用不同的 kid/私钥。例如 credentials 的 HTTP 进程可以查询锚点，但只有 credential-relay 的 kid 可以提交。服务先验证签名、受众、过期时间和学校，再同时检查领域策略 `grants` 与密钥策略 `key_grants`。省略逐密钥限制的旧企业策略需人工核对后再用于生产；本机生成器始终输出两层限制。业务端依然逐请求核对人的授权、班级、面试归属、证据版本和负责人。这组动作不代替学校给具体人员授予权限。

## 生产与演练的界限

本机签发密钥和同一系统用户下的 SQLite 文件仅供本地使用。逐进程环境阻止误发凭据；要防止一个被攻陷的进程访问同一台机器上的其他文件，生产环境还需独立操作系统账户或容器、独立数据库账户/SSL、受限挂载和网络策略。公开验真使用仅有 SELECT 的证书库账号，签发私钥只挂载给签发进程，真实链交易令牌只挂载给链 Worker。生产签发材料使用学校认可的密钥管理系统，不能复用本机生成的文件。

真实部署参见 [运行边界](MICROSERVICES.md)、[MySQL 标识检查](MYSQL-IDENTIFIERS.md)、[运行诊断](../services/operations/INTEGRATION.md) 与 [存证配置](../services/provenance/INTEGRATION.md)。旧框架应急访问单独按 [应急手册](EMERGENCY.md) 执行。
