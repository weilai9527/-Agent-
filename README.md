# 🎙 AI Interview Agent

> **微服务开发分支，尚未完成上线验收。** 本分支为 `codex/refactor-microservices`，用于保存和继续开发重构。旧版维护继续使用 `main`，生产服务器使用已验收的发布标签；不要将本分支作为生产更新来源。分支与发布约定见[版本管理说明](deploy/RELEASE-WORKFLOW.md)。

<h3 align="center">
Multi-Agent Real-Time AI Interview Platform
</h3>


<p align="center">
一个基于 AI Agent 的智能面试系统，
支持实时语音交互、多智能体协作以及自动化面试分析。
</p>


<p align="center">

React · FastAPI · Qwen · WebRTC · MySQL · Nginx

</p>



---

# 🌟 Overview

AI Interview Agent 是一个面向招聘与人才评估场景的智能面试平台。

系统通过 **Multi-Agent 架构** 模拟真实面试流程，
结合实时语音通信、AI 推理和结构化分析能力，
实现从面试交互到结果分析的完整流程。


核心目标：

> 让 AI 成为专业、高效、可扩展的智能面试官。


---

# ✨ Features


## 🎙 Real-Time Voice Interview

支持实时语音面试交互：

- 🎧 实时语音输入
- 🔊 AI 语音反馈
- 💬 实时对话流程
- 🌐 WebRTC 低延迟通信



## 🤖 Multi-Agent Interview System

通过多个 AI Agent 协同完成面试流程：


| Agent | Responsibility |
| --- | --- |
| 👨‍💻 Technical Agent | 技术能力评估 |
| 🏗 Architecture Agent | 系统设计分析 |
| 👩‍💼 HR Agent | 综合能力评价 |


不同 Agent 根据职责完成独立分析，
最终生成综合面试结果。



## 🧠 AI Interview Analysis

自动分析面试表现：

- 技术能力评价
- 回答质量分析
- 优势与不足总结
- 面试建议生成
- 综合评分报告



## 📊 Interview Management System

提供后台管理能力：

- 候选人管理
- 面试记录查询
- AI 报告查看
- 数据统计分析


## 🎓 School Student Accounts

- 学校名单通过 `.xlsx` 增量导入
- 学号作为学生唯一登录账号
- 每名学生生成不同的随机临时密码
- 管理端支持按辅导员查询并导出打印表
- 首次登录强制改密，完成后临时密码立即清除
- 学生自主注册入口和生产注册接口均已关闭



---

# 🏗 System Architecture

本文下述架构说明对应 `codex/refactor-microservices` 中正在开发的微服务重构，不代表生产服务器已完成切换。过渡阶段由 `main` 维护旧版，微服务改动保存在专属开发分支；运行版本以实际提交与部署记录为准。

学生端与管理端使用独立的原生网关。身份、档案、职业、训练、面试、媒体、评估、教学分析、证书、存证、用量、模型配置和运营审计各有自己的服务。面试与评估分别持有专库，提交、评分和签发通过持久任务或版本化凭据衔接。

从项目根目录运行 `python -m deploy.run_service list` 查看入口。日常运行默认 native 与 isolated，某个服务不可用时不会启用旧系统。新学校可从原生身份库直接开户。配置、权限和迁移见[微服务运行说明](deploy/MICROSERVICES.md)，临时读取冻结快照见[限时应急操作](deploy/EMERGENCY.md)，旧管理能力的归属见[原生覆盖清单](deploy/NATIVE-COVERAGE.md)。

## 本机运行与人工审核

从空目录启动全部原生服务、单独签发各进程密钥、创建第一所学校并登录，见[本地原生启动手册](deploy/NATIVE-LOCAL.md)。代码审查按[人工核对索引](deploy/REVIEW.md)逐条检查。

## 本地配置与 Git 提交

MySQL 分域建库、只读验真账号和离线 IBD 整理见[分域数据库运维说明](deploy/NATIVE-MYSQL.md)。

日常服务从各自的进程环境读取配置。学校账号直接在原生身份库创建；生产网关不持有旧数据库密码。历史 `.env.example` 仅用于查阅迁移前字段，不能作为日常启动步骤。

实际管理端位于 `admin/`，用 `npm run dev:admin` 启动、`npm run build:admin` 构建；`admin-next/` 是独立原型。管理员数据范围同时约束学生名单、训练记录和报告，服务端也会检查详情与修改操作的权限。

提交源码、测试、依赖锁文件及 `.env.example`；真实 `.env`、数据库、日志、依赖目录、构建产物，以及 `outputs/` 中的验收截图、临时脚本和备份均保留在本地，不纳入 Git。不要使用 `git add -f` 强制提交这些本地产物。

## 分支管理与服务器更新

旧版修复经审核和验收后合入 `main`，按固定发布标签更新服务器；微服务开发分支在完成业务验收和数据迁移演练前不发布到生产。旧版补丁需按问题场景移植到对应的新服务，不能直接用旧后端文件覆盖重构代码。

分支职责、当前 PR 遗留问题、服务器基线核对、日常发布、微服务切换及数据回退步骤见[分支管理、服务器更新与微服务切换](deploy/RELEASE-WORKFLOW.md)。本次开发快照不表示旧版修复已移植、代码已合入 `main` 或服务器已更新。

## Cloudflare 前端部署

### 双品牌入口

候选人端和管理端共用同一套功能代码、接口和数据。默认入口显示“乐业通”；访问路径中包含 `/xinghe/` 时显示“星河面试”。两版使用相同的标志、页面和功能，仅展示名称不同。后续功能更新在现有代码中完成，两版会同时获得更新。

本地预览地址：候选人端 `http://127.0.0.1:5173/` 与 `http://127.0.0.1:5173/xinghe/`；管理端 `http://127.0.0.1:5174/` 与 `http://127.0.0.1:5174/xinghe/`。部署时需让 `/xinghe/` 路径回退到对应前端的 `index.html`。

根目录的 `wrangler.jsonc` 将 `npm run build` 生成的 `frontend/dist` 作为静态资源部署到名为 `agent` 的 Worker，并为前端单页路由返回 `index.html`。这个部署不包含两个 Python API 服务或数据库。

正式使用前，请单独部署业务后端，并为前端构建设置 `VITE_API_BASE_URL`，同时把前端域名加入后端的 `FRONTEND_ORIGIN`。当前登录 Cookie 使用 `SameSite=Lax`，前端与 API 应使用同站点域名；仅部署静态页面时，登录和面试接口无法使用。


## ☁️ Alibaba Cloud RTC

“阿里云 RTC AI”模式使用 `dingrtc`、`dingrtc-aiagent` 以及阿里云
`StartAgent` / `StopAgent` 接口。每场面试拥有唯一、持久化的 RTC 会话；启动、停止、重连、
心跳超时和服务重启恢复均通过服务端状态机处理。

最终字幕按 RTC `turn_id` 幂等写入正式面试消息，再进入单题评价、追问、面试官切换和报告链路。
临时字幕只用于实时展示，不作为评分证据。结束面试时客户端会退出频道，并等待服务端 Agent 停止。

真实音视频需要在 media 进程的秘密存储中配置下列字段。

```env
RTC_APP_ID=
RTC_APP_KEY=
RTC_AI_AGENT_TEMPLATE_ID=
ALIBABA_CLOUD_ACCESS_KEY_ID=
ALIBABA_CLOUD_ACCESS_KEY_SECRET=
```

完整 RTC、会话回收和诊断日志选项见[媒体服务说明](services/media/INTEGRATION.md)。媒体密钥只注入媒体服务，
浏览器仅获取与当前面试和用户绑定的短期音频 Token。

