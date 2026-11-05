"""运行存证工作进程。可用 --once 仅处理一个到期事件。"""
import argparse
import logging
import signal
import time
from threading import Event

import httpx

from shared.service_db import ServiceDatabase
from .adapter import ManagedEvm
from .store import AnchorStore

log = logging.getLogger("provenance.worker")


def run_once(store, adapter, clock=time.time):
    now = int(clock())
    row = store.claim(now, adapter.network, adapter.binding)
    if row is None:
        return False

    status, tx_hash, block = row["status"], row["tx_hash"], None
    try:
        if tx_hash:
            status, block = adapter.inspect(row)
        else:
            tx_hash = adapter.submit(row)
            status = "submitted"
    except (httpx.HTTPError, ValueError, TypeError, KeyError, AttributeError) as error:
        # 广播后也可能超时。保留原事件和状态重试，日志仅记录异常类别。
        log.warning("Anchor %s will retry (%s)", row["event_id"], type(error).__name__)
    store.finish(row, status, tx_hash, block, int(clock()) + 10)
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true")
    options = parser.parse_args()
    store = AnchorStore(ServiceDatabase.from_env("provenance"))
    store.initialize()
    stopped = Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: stopped.set())
    logging.basicConfig(level=logging.WARNING)
    # HTTP 客户端的请求日志会写出完整 URL，托管节点的路径或查询参数可能含令牌。
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    with httpx.Client(timeout=5, follow_redirects=False, trust_env=False) as client:
        adapter = ManagedEvm.from_env(client)
        while not stopped.is_set():
            try:
                found = run_once(store, adapter)
            except Exception as error:
                if options.once:
                    raise
                log.warning("Worker iteration failed (%s)", type(error).__name__)
                found = False
            if options.once:
                return
            if not found:
                stopped.wait(1)


if __name__ == "__main__":
    main()
