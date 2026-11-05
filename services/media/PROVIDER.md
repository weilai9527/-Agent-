# 视频、录制与回放 provider 契约

媒体服务不保存厂商密钥或录制文件。部署侧适配器负责连接真实视频 SDK、云端录制及片段存储，配置 `MEDIA_PROVIDER_SERVICE_URL` 为该适配器的 HTTPS origin（本机测试允许 loopback HTTP）。`MEDIA_PROVIDER_ACTIONS` 为显式启用的 scope，以逗号分隔。缺少地址、动作未启用时，媒体动作返回 503，附带 `code=media_provider_disabled`、操作名及 `fallback=text`。启用开始录制还要求启用停录。已配置的适配器也必须根据厂商连接、账号权限和素材状态自行拒绝不可执行的请求。

| 步骤 | 媒体内部 POST 路径（前缀 /interviews/{id}/media） | 委派给适配器的唯一 scope | 适配器 POST 路径 |
|---|---|---|---|
| 候选人推送视频 | /video/token | media.video.publish | /v1/video/token |
| 对当前题开始录制 | /questions/{qid}/recording/start | media.recording.start | /v1/recording/start |
| 停止该题的录制 | /questions/{qid}/recording/stop | media.recording.stop | /v1/recording/stop |
| 读取该题的片段 | /questions/{qid}/playback | media.playback.read | /v1/playback |

浏览器无须提交请求体。媒体服务取已验证的学生 session，检查所属学校、学生和面试。开始录制另外要求题号等于新鲜的权威当前题号。视频凭证、开始录制或回放的计费单位为一次付费操作准入。停录可在面试结束、当前题目切换或学校配额用完后执行。

适配器使用 `SERVICE_ID=media_provider` 并配置针对 `media` 的公钥、学校列表与学生动作授权。每条路由以 `Depends(require_service("media_provider", scope))` 或等效校验验证签名身份，再对照资产归属。媒体服务每次重新签发单一动作凭据。管理员必须给厂商侧账号授予对应真实能力。

每个适配器请求的 `binding` 包含 `school_id, actor_id, interview_id, channel_id, user_id, question_id, scope`。视频频道与用户编码复用本次面试的 RTC 频道和候选人标识。视频 token 的 question_id 为 null。签发播放链接与视频 token 的请求额外提供整数 `max_expires_at`（UTC epoch 秒，上限为发送后 120 秒）。

- 适配器必须验证完整 binding 与底层资源匹配。视频凭证只允许相应学生在相应频道发送视频，签名 URL 只允许读取这一题的独立对象或已裁剪的片段。应从厂商结果得到实际有效期并据此返回。若厂商无法限制动作、频道、用户、时长或具体片段，拒绝签发。
- 适配器需持久化按学校、学生、面试、题号唯一的录制条目及对应厂商任务 ID。同一题的重复 start/stop 应返回已有结果；受理超时后须查询厂商任务恢复结果。关闭画面、切题、结束和失联时必须由适配器与媒体工作流处理片段边界和清理，再提供回放。只有确认厂商录制后才返回 recording。停录后转码中可返回 processing，未就绪的回放请求返回 409。找不到完整元组对应的素材时返回 404。
- 成功响应返回**实际验权的**完整 binding。视频响应另含 `token, app_id, expires_at`，录制响应另含 `recording_id, state`，回放响应另含 `url, recording_id, expires_at`。stop 只接受 processing 或 ready。回放 URL 必须为 HTTPS 且仅可在指定期限内使用。媒体服务校验这些结果，仅向调用方暴露白名单字段，视频和回放响应使用 no-store。
- 错误示例为无资产 404、越权 403、尚未生成片段 409、未开通厂商能力或服务故障 5xx。媒体服务不把厂商错误正文转发给客户端。厂商状态或凭证不满足契约时也会失败。

`test_providers.py` 使用临时 SQLite 和临时 Ed25519 密钥测试真实入站鉴权、出站签名和下游 HTTP 契约。测试适配器不提供生产录制、存储或厂商能力测量。
