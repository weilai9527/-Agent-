"""在仓库根目录运行 python -m services.interview.worker [--once]。"""
import argparse
import logging
import math
import os
import signal
from threading import Event, Thread

log = logging.getLogger("interview.worker")


def run_once(queue, prepare, *, job_id=None, lease_seconds=None, kinds=None):
    """最多领取一个任务。返回 False 表示本轮未领到已到执行时间的任务。"""
    if lease_seconds is None:
        lease_seconds = int(os.environ.get("INTERVIEW_JOB_LEASE_SECONDS", "120"))
    job = queue.claim(lease_seconds, job_id=job_id, kinds=kinds)
    if not job:
        return False

    stopped = Event()

    def heartbeat():
        connection = None
        try:
            while not stopped.wait(lease_seconds / 3):
                try:
                    # 数据库适配器为每个线程单独分配连接。
                    # 心跳线程退出前须自行关闭连接。
                    connection = queue.db.connect()
                    if not queue.renew(job, lease_seconds):
                        return
                except Exception as exc:
                    # 即使稍后续约成功，finish 发布结果前仍会核验租约。
                    log.warning("lease renewal %s failed (%s)", job["id"], type(exc).__name__)
        finally:
            if connection is not None and getattr(connection, "open", True):
                connection.close()

    lease_keeper = Thread(target=heartbeat, name="interview-lease", daemon=True)
    lease_keeper.start()
    try:
        publish = prepare(job)
        queue.finish(job, publish)
    except Exception as exc:
        queue.retry(job, exc)
        log.warning("job %s attempt %d failed (%s)", job["id"], job["attempts"], type(exc).__name__)
    finally:
        stopped.set()
        lease_keeper.join()
    return True


def main():
    from shared.runtime_mode import require_native_runtime
    require_native_runtime()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true", help="reconcile, process one due job, then exit")
    parser.add_argument("--kinds", help="comma-separated job types (including project for isolated assessment)")
    args = parser.parse_args()
    from .jobs import JOB_KINDS
    from services.assessment.storage_mode import assessment_owner, isolated
    if isolated():
        actor = os.environ.get("SERVICE_ID")
        if actor not in {"assessment", "interview"}:
            parser.error("Isolated workers require a dedicated interview or assessment identity")
        allowed = ("score", "report", "analytics") if assessment_owner() else ("train_complete", "project", "media_close")
    else:
        allowed = tuple(kind for kind in JOB_KINDS if kind != "project")
    kinds = tuple(args.kinds.split(",")) if args.kinds is not None else allowed
    if not set(kinds).issubset(allowed):
        parser.error("unsupported --kinds value")
    if assessment_owner():
        from services.assessment import runtime as engine
    else:
        from services.interview import runtime as engine

    logging.basicConfig(level=logging.INFO)
    poll = float(os.environ.get("INTERVIEW_WORKER_POLL_SECONDS", "1"))
    lease = int(os.environ.get("INTERVIEW_JOB_LEASE_SECONDS", "120"))
    if not math.isfinite(poll) or poll <= 0 or lease < 3:
        parser.error("poll interval must be positive and lease must be at least 3 seconds")
    stopped = Event()

    def stop(_signal, _frame):
        stopped.set()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    if set(kinds) & {"score", "report"}:
        engine.reconcile_queued_reports()
    while not stopped.is_set():
        try:
            found = run_once(engine.interview_jobs, engine.prepare_interview_job, lease_seconds=lease, kinds=kinds)
        except Exception as exc:
            if args.once:
                raise
            # 数据库短暂不可用时保留工作进程，等待下一轮轮询。
            log.warning("worker iteration failed (%s)", type(exc).__name__)
            found = False
        if args.once:
            return
        if not found:
            stopped.wait(poll)


if __name__ == "__main__":
    main()
