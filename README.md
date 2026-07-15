# 多 Agent 面试系统

这是一个前后端分离的 AI 模拟面试项目，包含候选人端、管理端、业务 API 和管理 API。候选人端用于简历分析、面试配置、电话面试、复盘报告和能力画像；管理端用于查看和管理系统数据。

## 项目结构

```text
.
├── frontend/        # 候选人端 React + Vite 应用
├── backend/         # 候选人端 FastAPI 服务，默认端口 3001
├── admin/           # 管理端 React + Vite 应用，默认端口 5174
├── admin_backend/   # 管理端 FastAPI 服务，默认端口 3002
├── data/            # 本地数据库运行数据，已忽略
├── logs/            # 本地服务日志，已忽略
├── package.json     # 根目录脚本入口
└── 项目说明书.md      # 更完整的功能和接口说明
```

## 本地启动

### 1. 安装依赖

```bash
npm install
python3 -m pip install -r backend/requirements.txt
python3 -m pip install -r admin_backend/requirements.txt
```

### 2. 准备环境变量

```bash
cp backend/.env.example backend/.env
cp frontend/.env.example frontend/.env
cp admin_backend/.env.example admin_backend/.env
cp admin/.env.example admin/.env
```

然后按本机数据库和模型服务配置修改 `backend/.env`。候选人端后端默认使用 MySQL；管理端本地示例默认可以读 `backend/data/dev.sqlite`，也可以切换到 MySQL。

### 3. 启动候选人端

```bash
npm run dev:backend
npm run dev:frontend
```

默认地址：

- 前端：http://127.0.0.1:5173/
- 后端：http://127.0.0.1:3001/

### 4. 启动管理端

首次启动前，在 `admin_backend/.env` 中配置独立管理员初始化账号：

```env
ADMIN_BOOTSTRAP_EMAIL=admin@example.com
ADMIN_BOOTSTRAP_PASSWORD=请替换为至少12位的强密码
ADMIN_BOOTSTRAP_NAME=系统管理员
ADMIN_BOOTSTRAP_ROLE=super_admin
ADMIN_COOKIE_SECURE=false
```

初始化账号只会在邮箱不存在时创建。生产环境必须设置 `ADMIN_COOKIE_SECURE=true`，并通过安全的 Secret 管理方式保存管理员密码；初始化完成后可以删除 `ADMIN_BOOTSTRAP_PASSWORD`。

```bash
npm run dev:admin-backend
npm run dev:admin
```

默认地址：

- 管理端前端：http://127.0.0.1:5174/
- 管理端后端：http://127.0.0.1:3002/

管理端使用独立的 `admin_session` HttpOnly Cookie，支持超级管理员、运营管理员和报告审核员三种角色。系统配置和管理员账号管理仅允许超级管理员操作。

## 密码重置（暂缓启用）

当前阶段没有可用的邮件服务，密码重置不纳入交付和验收范围。候选人端默认不展示“忘记密码”入口，后端也不会因为缺少 SMTP 配置而阻止系统启动。

已有的一次性 Token、链接校验、确认改密和旧 Session 撤销代码暂时保留。后续具备邮件服务时，在后端设置 `PASSWORD_RESET_ENABLED=true`、在候选人端设置 `VITE_PASSWORD_RESET_ENABLED=true`，并补充 SMTP 参数后即可重新启用。

## AI 评分与报告

单题回答和综合报告默认按 `EVALUATION_PROVIDER_ORDER`、`REPORT_PROVIDER_ORDER` 调用已配置的 OpenAI 兼容模型。结果会记录 `provider`、`model`、`prompt_version`、生成状态和复核状态。供应商不可用时自动使用本地规则，并以 `fallback=true` 明确标记，不会伪装成 AI 结果。

管理端的超级管理员和报告审核员可以在报告详情中通过或驳回复核，操作会写入管理员审计日志。相关模型超时和输出上限可通过 `AI_EVALUATION_*`、`AI_REPORT_*` 环境变量调整。

文本评分建议分别配置 `QWEN_API_KEY` 和 `OPENAI_API_KEY`，不要只依赖语音服务密钥。修改配置并重启后端后，可以运行下面的无密钥泄露诊断：

超级管理员也可以在管理端“系统与权限 → 系统配置 → 复盘报告 / 单题评价模型”中保存两类文本 API Key、模型、供应商顺序、超时和重试次数，并直接执行脱敏连通性检测。接口不会回传密钥明文，留空保存不会覆盖现有密钥。

```bash
python -m backend.src.provider_diagnostics --config-only  # 只检查供应商、模型和密钥来源
python -m backend.src.provider_diagnostics                # 发送最小 JSON 请求，验证鉴权、网络和结构化输出
```

诊断只输出密钥对应的环境变量名称，不输出密钥内容。若所有供应商均失败，命令会返回非零退出码。真正使用本地规则时，报告状态为 `degraded`；切换到第二个 AI 供应商成功仍属于 AI 报告，不会再误标为本地兜底。

## 职业能力目录

后端使用版本化数据维护“学院 → 专业 → 培养方向 → 就业方向 → 具体岗位 → 能力矩阵”，运行时不写死学院、专业或岗位。首次初始化会写入 `computer-pilot-v1` 计算机类试点版本；新增专业通过新版本和数据导入完成。

候选人端只读接口：

- `GET /api/catalog/versions`：已发布版本
- `GET /api/catalog/tree?version=computer-pilot-v1`：完整层级和岗位能力矩阵

管理端接口受 `catalog_role_permissions` 数据权限控制：

- `GET/POST /api/admin/catalog/versions`
- `GET /api/admin/catalog/tree?version=版本编码`
- `POST /api/admin/catalog/versions/{version_id}/imports?mode=merge`
- `POST /api/admin/catalog/versions/{version_id}/publish`

管理端登录后可从左侧导航进入“职业目录”。超级管理员可以在页面中新建草稿版本、上传 Excel 和发布目录；运营管理员可以维护与导入，报告审核员只能查看。已发布版本不能直接修改，需要先建立草稿版本。

Excel 仅导入草稿版本，支持 `merge` 和 `replace`。工作簿需要包含以下工作表和表头：

- `学院`：编码、名称，可选说明
- `专业`：编码、名称、学院编码
- `培养方向`：编码、名称、专业编码
- `就业方向`：编码、名称、培养方向编码
- `岗位`：编码、名称、就业方向编码
- `能力`：编码、名称、类别
- `岗位能力`：岗位编码、能力编码、要求等级、权重（等级和权重均为 1-5）

每次导入都会在 `catalog_import_jobs` 中记录文件哈希、模式、行数、状态和错误；发布新版本时会归档原发布版本，并校验六层目录与能力矩阵是否完整。

### 岗位数据治理与维护原则

岗位属于需要维护的业务数据，但不得写死在前端或后端代码中，也不要求开发人员逐条修改代码添加岗位。系统采用以下数据来源和维护方式：

1. 系统初始化时写入少量试点岗位，用于验证目录和匹配流程。
2. 全校首次建设时，由各学院整理专业、培养方向、标准岗位和能力矩阵，通过 Excel 批量导入草稿版本。
3. 日常增删改由管理端完成，并通过新目录版本审核、发布；历史版本保留用于结果追溯。
4. AI 可以根据培养方案、简历样本和招聘数据提出新增岗位、合并重复岗位或补充能力矩阵的建议，但 AI 建议必须经过学院负责人或管理员审核后才能进入正式目录。

系统需要区分两类岗位数据：

- **标准岗位**：如后端开发工程师、数据工程师、产品经理，数量相对稳定，用于能力标准、学生匹配和模拟面试，是职业能力目录的一部分。
- **企业招聘职位**：如某公司某届 Java 后端实习生，数量大且时效性强，后续应通过招聘数据接口或文件同步，并映射到一个标准岗位，不能直接替代学校维护的岗位标准。

推荐的数据治理流程为“学院提供基础数据 → Excel 批量导入草稿 → 系统校验与 AI 辅助补全 → 专业负责人审核 → 管理员发布 → 学生端使用已发布版本”。学生简历分析不得将模型临时生成的岗位直接写入正式目录。

### AI 岗位发现与审核池

简历分析返回的每个推荐岗位都会先与当前已发布目录匹配：正式名称或已登记别名完全匹配时，结果直接关联标准岗位、目录版本和能力矩阵；未匹配时仍可展示为“目录外 AI 建议”，但只会按规范化岗位名称汇总进 `catalog_job_suggestions` 待审核池，不会自动新增正式岗位。

管理端“职业目录 → AI 岗位建议池”提供以下处理方式：

- **合并为别名**：将建议映射到一个已发布标准岗位，登记到 `catalog_job_aliases`；以后相同名称可直接匹配该岗位及能力矩阵。
- **批准新增**：把建议标记为已批准，管理员随后在新目录草稿中补齐就业方向、岗位编码和能力矩阵，再通过 Excel 导入及版本发布进入正式目录。
- **驳回**：保留审核记录，但不纳入正式目录。

建议池只保存岗位名称、出现次数、AI 供应商、相似岗位提示和审核状态，不保存简历正文、用户身份或联系方式。名称相似度只用于提示管理员，不会自动判定为同一岗位。

管理接口：

- `GET /api/admin/catalog/job-suggestions?status=pending`
- `POST /api/admin/catalog/job-suggestions/{suggestion_id}/review`
- `POST /api/admin/catalog/job-suggestions/{suggestion_id}/merge`

## 常用命令

```bash
npm run build          # 构建候选人端
npm run build:admin    # 构建管理端
npm run preview        # 预览候选人端构建产物
npm run preview:admin  # 预览管理端构建产物
```

## ngrok 调试

如果用 ngrok 暴露 Vite 开发服务，需要把当前 ngrok 域名加入 `frontend/vite.config.js` 的 `server.allowedHosts`。例如：

```js
server: {
  host: '127.0.0.1',
  allowedHosts: ['freckles-flying-patio.ngrok-free.dev'],
}
```

ngrok 免费域名变化后，需要同步更新这里并重启前端服务。

## 本地运行产物

以下目录和文件是本地运行产物，已经通过 `.gitignore` 忽略：

- `node_modules/`
- `dist/`
- `logs/`
- `data/`
- `backend/data/`
- `.env`
- `.DS_Store`

