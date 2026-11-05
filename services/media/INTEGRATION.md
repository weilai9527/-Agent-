# 媒体服务接入

在仓库根目录启动 `uvicorn services.media.app:app`。指定独立 `MEDIA_DB_ENGINE` 和数据库配置（SQLite 测试需要绝对路径 `MEDIA_SQLITE_PATH`）。配置 `SERVICE_ID=media`、签名私钥、key ID 及入站信任策略。媒体出站到 `USAGE_SERVICE_URL`，委派学生身份，授予 `usage.reserve`、`usage.settle`。用量契约见 ../usage/INTEGRATION.md。media 预留并结算的一个单位是一次媒体操作准入；它不计时长、流量或供应商账单。

## 与面试引擎的边界

受信网关或面试服务先验证学生、学校和 interview 的归属，从服务器读取当前题和角色，使用 `media.context.sync` 调用 `PUT /interviews/{id}/context`。此端点只供服务调用，禁止透传浏览器 JSON。请求字段见 access.Context，school/owner 来自签名。请在每次学生操作前同步。终态不可回到进行中，题目序号不得倒退。及时同步结束并调用 stop，失败后 RTC 心跳超时回收。文字回答和最终字幕仍走面试服务同一个原子提交入口：绑定初始 question_id、submission_id 和 round_agent_id，重投复用原 submission_id。RTC 字幕预检不能替代面试事务内对当前题的比较。

## 内部操作

- RTC 的 `/interviews/{id}/rtc/token`、`session`（GET）、`session/heartbeat`、`agent/start`、`agent/notify`、`agent/stop`、`caption/validate` 分别需要 `media.rtc.token/read/heartbeat/start/notify/stop/caption`（逐项对应，最后一段替换）。清理、心跳和幂等重放不消耗媒体配额。
- 语音的 `/interviews/{id}/qwen/tts`、`qwen/realtime-tts`、`qwen/speech` 需要 `media.speech.synthesize`；`realtime/sdp`、`qwen/omni-realtime/sdp` 和别名 `qwen/omni-webrtc/offer` 需要 `media.voice.connect`。Qwen WS 试验模式使用 `media.voice.connect`。
- 新增 POST `/interviews/{id}/media/video/token`、`media/questions/{qid}/recording/start`、`media/questions/{qid}/recording/stop`、`media/questions/{qid}/playback` 分别需要 `media.video.publish`、`media.recording.start`、`media.recording.stop`、`media.playback.read`。访问权、真实 provider 和预算三者均通过才可启动。适配器契约见 [PROVIDER.md](PROVIDER.md)。

## 浏览器和部署

学生入口 `services.gateway.student:app` 保留 `/api/interviews/{id}/` 下的媒体动作，以及 `/ws/interviews/{id}/qwen/omni-realtime` 语音连接。媒体服务启动时先校验原生会话模式、独立存储模式和 `SERVICE_ID=media`，再访问独立媒体库、运行任务恢复循环。RTC 令牌默认有效期为 300 秒，最多 900 秒，重连时重新申请。

HTTP 请求经身份服务核验原生学生 Cookie 后，网关委派 `interview.media.context`，通过 `GET /internal/interviews/{id}/media-context` 取得面试服务在同一事务内读取的角色、题目、冻结的简历上下文和所有者。网关核对响应的面试 ID、学生 ID 和学校，再以 `media.context.sync` 写入媒体服务。WebSocket 在握手、开录和停录时分别核验。面试或身份服务缺地址、离线或拒绝时，请求在相应步骤终止，不会访问旧面试库。面试进程使用 `MEDIA_SERVICE_URL`、`media.context.sync`、`media.rtc.stop` 同步终态并结束语音任务。只有浏览器媒体动作和诊断路径对外开放。

模型控制面地址使用 `PROVIDERS_SERVICE_URL`，为媒体工作负载授予 `providers.runtime.read`，按控制面契约配置签名身份。建立语音 SDP、合成语音、Omni WebSocket 握手和每段录音提交前，媒体服务均检查当前授权配置。控制面无可用配置时，此次操作不领用媒体额度，返回错误和 `fallback=text`。计量单位是一次准入，准入之后供应商拒绝或断开时仍可能已扣除这一单位。

Omni 录音需部署端选择接收方，两种方式如下。

| 配置 | 音频接收方与凭据 |
| --- | --- |
| `QWEN_OMNI_TRANSPORT=ws` | 仅将音频发送到白名单内的 `QWEN_OMNI_REALTIME_WS_URL`，使用该网关的专用 `QWEN_OMNI_REALTIME_API_KEY`。既有部署若已明确配置此 URL，也可省略传输选项。 |
| `QWEN_OMNI_TRANSPORT=http` | 使用经白名单校验的 `QWEN_OMNI_BASE_URL`（默认官方 DashScope 地址），凭据为 `QWEN_OMNI_API_KEY` 或 `DASHSCOPE_API_KEY`。 |

仅设置通用密钥不能启用录音上传。所选接收方未配置、被拒绝或连接中断时，当前录音不会改投另一接收方，界面可提示转回文字面试。实时 TTS 显式选择 `realtime` 时仅尝试该链路；由客户端选择 `auto` 时才允许降级到同一供应商的标准合成。

切流前让旧入口停止发新 RTC，待旧库的非终态任务全部停止、重试清空，再关闭旧恢复循环。新媒体库的频道由学校、学生及面试共同生成，不能接管旧频道。长连接需在切流后重新接入。配置正式录制后，由部署侧 provider 依学校策略管理素材保留、授权过期与清理。

文字调用方使用 [文字配额协议](../usage/TEXT.md)。媒体预算耗尽，HTTP 429 返回 fallback=text；文字输入沿用当前题号与提交 ID。文字模型预算不足时返回 deferred，已保存的原文由回合服务保留。RTC 旧客户端仍依靠本地连接代次、服务端 question_id 和 submission_id 防止迟到写入；需要绑定供应商任务时，用 caption/validate 预检 task_id 和 question_id。

## 验证边界

“100 人在 5 分钟内进入”是待测场景。当前本机独立 SQLite 功能测试中，16 个申请竞争 5 份余量，5 个成功、11 个超额；对已获准的 5 笔并发重复结算，已用仍为 5。这组数据检验同校配额锁，不代表在线人数、媒体吞吐或生产 MySQL 性能。真实云端音视频、浏览器跨网络通话和场次容量需另行联测。

`python -m pytest -q services/media services/usage` 可复跑服务测试。test_usage_integration.py 在两个独立 Python 进程中运行 media、usage ASGI 应用，以管道承载 HTTP 请求内容，保留两端的验签和各自数据库。测试将媒体额度设为 1，首次领到可解码的音频发布 token，第二次返回 429；学校余额已用 1、预留 0。该测试没有监听端口或调用真实云厂商。
