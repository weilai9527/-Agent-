# 教学证书存证

credentials 的事务 outbox 将签发、撤销、补发分别投递为独立的不可变事件。provenance 只接收事件标识与摘要。教学证书签名归 credentials 管理，链上零金额交易由独立托管链账户签署。

## 服务接口

从项目根目录运行 `uvicorn services.provenance.app:app` 和独立的 `python -m services.provenance.worker`。worker 支持 `--once` 以处理一个到期事件。两个进程指向同一个 provenance 专库，使用 `shared.service_db` 规定的 `PROVENANCE_DB_ENGINE` 及 SQLite 绝对路径或 MySQL TLS 配置。HTTP 服务的 `SERVICE_ID=provenance`，`SERVICE_TRUST_POLICY` 按下列规则配置两套独立公钥与明确的学校列表。仅放行 credentials 与 credentials-verifier 的内网访问。

| 方法与路径 | scope | 内容 |
| --- | --- | --- |
| POST /internal/anchors | provenance.submit | JSON 字段 event_id 为 32 位小写十六进制，digest 为 64 位小写十六进制。相同学校、事件、摘要可重复投递，摘要冲突返回 409 |
| GET /internal/anchors/{event_id} | provenance.read | 同校事件的当前结果，其他学校的记录不可见 |
| GET /health | 无 | 服务数据库探测 |

两个业务接口均要求受众 provenance、actor_type system，并使用受信身份中的 school_id 定位记录。服务身份和路由授权如下。

| caller | actor_id | 可授予 scope |
| --- | --- | --- |
| credentials | credentials-relay | provenance.submit、provenance.read |
| credentials-verifier | credentials-verifier | 仅 provenance.read |

公网验真进程使用 credentials-verifier 的独立服务签名密钥。即使部署策略误授 provenance.submit，提交路由也会拒绝该身份。

两者均返回 `{event_id, digest, status, network, tx_hash, block_number}`。network 在首次认领前为 null，此后形如 eip155:31337。测试 fixture 明确标为 fixture。pending 尚未取得提交哈希，submitted 已获得交易哈希，confirmed 已独立核验最终链上交易，failed 表示已终结交易回滚或交易内容不匹配。tx_hash、block_number 在对应事实尚不可用时为 null。即时撤销状态以 credentials 的业务记录为准。

## 托管提交与独立 RPC 核验

worker 配置如下。所有密钥和令牌从部署环境注入。

| 环境变量 | 设置 |
| --- | --- |
| PROVENANCE_SUBMIT_URL | 支持下列幂等协议的托管签名提交端完整地址 |
| PROVENANCE_SUBMIT_TOKEN | 仅授权该链账户和发送目标的 Bearer 令牌 |
| PROVENANCE_RPC_URL | 独立可信的 EVM JSON-RPC 只读节点，支持 finalized 区块标签 |
| PROVENANCE_CHAIN_ID | 预期 chain ID 的十进制整数 |
| PROVENANCE_ACCOUNT、PROVENANCE_RECIPIENT | 链账户、专用存证接收地址，均为 0x 加 40 位十六进制 |

使用 HTTPS，开发机环回地址允许 HTTP。配置示例中的 31337 是本地链 ID。worker 不内置学校、链账户、生产端点或测试密钥。

提交端接收 POST 和 Idempotency-Key，JSON 包含 chainId（十进制整数）、from、to、value（固定 0x0）、data（32 字节承诺）。托管服务应限制 chainId、from、to 和金额，在签发交易前持久化幂等键，重试始终返回同一交易的 `{"transactionHash":"0x…"}`。供应商原生协议不同的部署需要适配这个提交端。代付账户、nonce、付费和广播由托管端负责。RPC 核验不会向该节点传送托管令牌。

承诺算法为 SHA-256，输入依次是 ASCII 域标记 `teaching-anchor-v1`、一个 0 字节、SHA-256(UTF-8(school_id)) 的 32 个原始字节、event_id 的 16 个原始字节和 digest 的 32 个原始字节。提交端只收到承诺，不收到学生信息。

worker 在提交前固定链、账户和目标。接管未完成任务时必须保留同一配置。写入交易哈希后轮询 receipt、finalized head、规范高度的区块及交易本身。只有交易位于已最终确定的规范区块，成功回执、交易哈希、发送方、目标、金额和承诺全部一致，才能返回 confirmed。节点掉线、未出块、finalized 暂不可用或遇到孤块时保留待验证状态。链切换前应先排空原配置队列。RPC 方法遵循 [Ethereum JSON-RPC](https://ethereum.org/developers/docs/apis/json-rpc/)。

## 代码审查入口

查看 `app.py` 的调用方和学校校验，以及 `store.py` 的事件唯一键和租约更新条件，核对跨校读取、重投和过期租约回写。再查看 `adapter.py` 的 commitment、submit、inspect，核对托管提交端收到的字段和判定最终确认所需的回执。交易载荷中的 data 只有 32 字节承诺；学生姓名、回答、成绩、签名文件和撤销原因保留在链下。worker 日志避免记录提交端或 RPC 的完整 URL，以免泄露路径中的访问令牌。

## 离线验证

运行 `python -m pytest -q services/provenance`。测试创建临时 SQLite、一次性 Ed25519 服务密钥，使用内存 HTTP transport 模拟幂等提交端和独立 RPC。测试覆盖隔离、并发、提交响应丢失、租约接管、未确认与孤块、最终确认和错误交易。跨服务测试从 credentials outbox 经签名 HTTP 请求投递至 provenance，再验证 relay 对断连、恢复和测试链最终确认的区分。
