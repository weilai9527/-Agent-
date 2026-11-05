"""作答和提交任务必须复用同一业务事务，工作进程按租约串行发布结果。"""
from .jobs import JobQueue
from .storage import DB_ENGINE, db

interview_jobs = JobQueue(db, DB_ENGINE)
