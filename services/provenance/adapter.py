"""经托管链账户幂等提交，再用独立 EVM 节点核对存证。"""
from hashlib import sha256
import os
import re
from urllib.parse import urlsplit

HASH = re.compile(r"0x[0-9a-fA-F]{64}\Z")
ADDRESS = re.compile(r"0x[0-9a-fA-F]{40}\Z")
QUANTITY = re.compile(r"0x(0|[1-9a-fA-F][0-9a-fA-F]*)\Z")


def endpoint(value):
    parsed = urlsplit(value)
    local = parsed.hostname in {"localhost", "127.0.0.1", "::1"}
    if (not parsed.hostname or parsed.username or parsed.password or parsed.fragment
            or (parsed.scheme != "https" and not (local and parsed.scheme == "http"))):
        raise ValueError("Service endpoint requires HTTPS or a loopback HTTP endpoint")
    return value


def quantity(value):
    if not isinstance(value, str) or not QUANTITY.fullmatch(value):
        raise ValueError("Invalid RPC quantity")
    return int(value, 16)


class ManagedEvm:
    def __init__(self, client, *, submit_url, rpc_url, chain_id, account, recipient, token):
        if chain_id < 1 or not ADDRESS.fullmatch(account) or not ADDRESS.fullmatch(recipient) or not token:
            raise ValueError("Invalid chain account configuration")
        self.client = client
        self.submit_url, self.rpc_url = endpoint(submit_url), endpoint(rpc_url)
        self.chain_id, self.account, self.recipient = chain_id, account.lower(), recipient.lower()
        self.token = token
        self.network = f"eip155:{chain_id}"

    @property
    def binding(self):
        return sha256(f"{self.network}/{self.account}/{self.recipient}".encode()).hexdigest()

    @classmethod
    def from_env(cls, client):
        env = os.environ
        return cls(client, submit_url=env["PROVENANCE_SUBMIT_URL"],
                   rpc_url=env["PROVENANCE_RPC_URL"], chain_id=int(env["PROVENANCE_CHAIN_ID"]),
                   account=env["PROVENANCE_ACCOUNT"], recipient=env["PROVENANCE_RECIPIENT"],
                   token=env["PROVENANCE_SUBMIT_TOKEN"])

    @staticmethod
    def commitment(row):
        # 将固定长度的学校摘要、事件标识、证书摘要合并散列，提交端只收到承诺值。
        return "0x" + sha256(b"teaching-anchor-v1\0" + bytes.fromhex(
            row["school_key"] + row["event_id"] + row["digest"])).hexdigest()

    def rpc(self, method, params):
        response = self.client.post(self.rpc_url, json={
            "jsonrpc": "2.0", "id": 1, "method": method, "params": params,
        })
        response.raise_for_status()
        obj = response.json()
        if (not isinstance(obj, dict) or obj.get("jsonrpc") != "2.0"
                or type(obj.get("id")) is not int or obj["id"] != 1
                or "error" in obj or "result" not in obj):
            raise ValueError("Invalid RPC response")
        return obj["result"]

    def check_network(self):
        if quantity(self.rpc("eth_chainId", [])) != self.chain_id:
            raise ValueError("RPC chain mismatch")

    def submit(self, row):
        self.check_network()
        data = self.commitment(row)
        # 托管端持久保存幂等键对应的交易，响应丢失或租约到期后仍能找回。
        key = sha256(f"{self.binding}/{data}".encode()).hexdigest()
        response = self.client.post(self.submit_url, headers={
            "Authorization": f"Bearer {self.token}", "Idempotency-Key": key,
        }, json={"chainId": self.chain_id, "from": self.account, "to": self.recipient,
                 "value": "0x0", "data": data})
        response.raise_for_status()
        tx_hash = response.json()["transactionHash"]
        if not isinstance(tx_hash, str) or not HASH.fullmatch(tx_hash):
            raise ValueError("Invalid transaction hash")
        return tx_hash.lower()

    def inspect(self, row):
        """核验最终区块中的交易并返回状态和高度。RPC 异常由调用方重试。"""
        self.check_network()
        tx_hash = row["tx_hash"]
        receipt = self.rpc("eth_getTransactionReceipt", [tx_hash])
        if receipt is None:
            return "submitted", None
        block_hash = receipt["blockHash"].lower()
        height = quantity(receipt["blockNumber"])
        if receipt["transactionHash"].lower() != tx_hash or not HASH.fullmatch(block_hash):
            raise ValueError("Receipt does not identify transaction and block")

        # 同时查最终区块和同高度的规范块，排除孤块回执。
        head = self.rpc("eth_getBlockByNumber", ["finalized", False])
        if head is None:
            return "submitted", None
        finalized_height, finalized_hash = quantity(head["number"]), head["hash"].lower()
        if not HASH.fullmatch(finalized_hash):
            raise ValueError("Invalid finalized block")
        if finalized_height < height or (finalized_height == height and finalized_hash != block_hash):
            return "submitted", None
        block = self.rpc("eth_getBlockByNumber", [hex(height), False])
        if (not block or block["hash"].lower() != block_hash or quantity(block["number"]) != height
                or tx_hash not in [h.lower() for h in block["transactions"]]):
            return "submitted", None
        tx = self.rpc("eth_getTransactionByHash", [tx_hash])
        if (not tx or tx["hash"].lower() != tx_hash or tx["blockHash"].lower() != block_hash
                or quantity(tx["blockNumber"]) != height):
            return "submitted", None

        status = quantity(receipt["status"])
        if status not in (0, 1):
            raise ValueError("Invalid receipt status")
        if (not status or tx["from"].lower() != self.account or tx.get("to") is None
                or tx["to"].lower() != self.recipient or quantity(tx["value"]) != 0
                or tx["input"].lower() != self.commitment(row)):
            return "failed", height
        return "confirmed", height
