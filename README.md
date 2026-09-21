# 🎙 AI Interview Agent

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

- 候选人端：React + Vite，负责面试配置、实时通话和复盘展示。
- 业务后端：FastAPI，负责身份、面试状态机、AI 调用、RTC 会话和报告生成。
- 管理端：独立 FastAPI 服务，负责候选人、职业目录、连接日志和统计管理。
- 数据层：MySQL 用于生产数据，SQLite 用于本地开发与自动化测试。


## ☁️ Alibaba Cloud RTC

“阿里云 RTC AI”模式使用 `dingrtc`、`dingrtc-aiagent` 以及阿里云
`StartAgent` / `StopAgent` 接口。每场面试拥有唯一、持久化的 RTC 会话；启动、停止、重连、
心跳超时和服务重启恢复均通过服务端状态机处理。

最终字幕按 RTC `turn_id` 幂等写入正式面试消息，再进入单题评价、追问、面试官切换和报告链路。
临时字幕只用于实时展示，不作为评分证据。结束面试时客户端会退出频道，并等待服务端 Agent 停止。

在 `backend/.env` 中至少配置：

```env
RTC_APP_ID=
RTC_APP_KEY=
RTC_AI_AGENT_TEMPLATE_ID=
ALIBABA_CLOUD_ACCESS_KEY_ID=
ALIBABA_CLOUD_ACCESS_KEY_SECRET=
```

完整 RTC、会话回收和诊断日志选项见 `backend/.env.example`。所有密钥只保存在后端，
浏览器仅获取与当前面试和用户绑定的短期音频 Token。

