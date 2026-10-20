"""Persistent, process-safe pacing. An unknown submission is never silently freed."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
import sqlite3
import time
import uuid

from .core import ProductionError, require


class CachedSubmission(Exception):
    def __init__(self, data):
        self.data = data


def retry_after(value, now, fallback):
    try:
        return max(0, float(value))
    except (ValueError, TypeError):
        try:
            return max(0, parsedate_to_datetime(value).timestamp() - now)
        except (TypeError, ValueError, OverflowError):
            return fallback


class Scheduler:
    def __init__(self, path, profile, run_id, budget=12, clock=time.time, sleep=time.sleep):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.profile = profile
        self.pool = profile["quota_pool"]
        self.run_id = run_id
        self.budget = budget
        self.clock, self.sleep = clock, sleep
        with self.connection() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS attempts(
                    id TEXT PRIMARY KEY,pool TEXT,run_id TEXT,job TEXT,kind TEXT,
                    started REAL,status TEXT,task_json TEXT,updated REAL);
                CREATE INDEX IF NOT EXISTS attempt_pool_time ON attempts(pool,started);
                CREATE TABLE IF NOT EXISTS controls(pool TEXT PRIMARY KEY,cooldown REAL,concurrency INTEGER);
            """)

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA busy_timeout=15000")
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def acquire(self, job, kind="image"):
        limits = self.profile["limits"]
        pool = self.pool if kind == "image" or limits.get("poll_shares_rpm", False) else self.pool + ":poll"
        interval = limits["start_interval_seconds"] if kind == "image" else limits.get("poll_interval_seconds", 3)
        rpm = limits.get("requests_per_minute") if kind == "image" or limits.get("poll_shares_rpm", False) else limits.get("poll_requests_per_minute")
        waited = 0
        while True:
            now = self.clock()
            delay = 0.0
            with self.connection() as db:
                db.execute("BEGIN IMMEDIATE")
                if kind == "image":
                    done = db.execute("SELECT task_json FROM attempts WHERE pool=? AND job=? AND kind='image' AND status='done' AND task_json IS NOT NULL ORDER BY started DESC LIMIT 1", (self.pool, job)).fetchone()
                    if done:
                        import json
                        raise CachedSubmission(json.loads(done["task_json"]))
                    spent = db.execute("SELECT COUNT(*) FROM attempts WHERE run_id=? AND kind='image'", (self.run_id,)).fetchone()[0]
                    require(spent < self.budget, "实际图片提交次数已达预算（含失败、参考和重试），未继续请求。")
                    unknown = db.execute("SELECT job FROM attempts WHERE pool=? AND kind='image' AND status='unknown' LIMIT 1", (self.pool,)).fetchone()
                    require(not unknown, "同一配额池存在提交状态未知的任务，请先查询／处理后再续作；未重复提交。")
                    active = db.execute("SELECT COUNT(*) FROM attempts WHERE pool=? AND kind='image' AND status IN ('sending','submitted')", (self.pool,)).fetchone()[0]
                    same_job = db.execute("SELECT 1 FROM attempts WHERE pool=? AND job=? AND kind='image' AND status IN ('sending','submitted') LIMIT 1", (self.pool, job)).fetchone()
                    control = db.execute("SELECT * FROM controls WHERE pool=?", (self.pool,)).fetchone()
                    cap = min(limits["max_inflight"], control["concurrency"]) if control else limits["max_inflight"]
                    if active >= cap or same_job:
                        delay = max(delay, 1)
                    if control:
                        delay = max(delay, control["cooldown"] - now)
                    daily = limits.get("images_per_day")
                    if daily is not None:
                        offset = limits.get("day_boundary_utc_hour", 0) * 3600
                        boundary = int((now-offset)//86400)*86400+offset
                        count = db.execute("SELECT COUNT(*) FROM attempts WHERE pool=? AND kind='image' AND started>=?", (self.pool, boundary)).fetchone()[0]
                        require(count < daily, "记录的每日图片提交额度已用完，未继续请求。")
                last = db.execute("SELECT MAX(started) FROM attempts WHERE pool=?", (pool,)).fetchone()[0]
                if last is not None:
                    delay = max(delay, interval - (now-last))
                if rpm is not None:
                    starts = db.execute("SELECT started FROM attempts WHERE pool=? AND started>? ORDER BY started", (pool, now-60)).fetchall()
                    if len(starts) >= rpm:
                        delay = max(delay, starts[len(starts)-rpm]["started"]+60-now+.01)
                if delay <= .0001:
                    ticket = uuid.uuid4().hex
                    db.execute("INSERT INTO attempts VALUES(?,?,?,?,?,?,?,?,?)", (ticket, pool, self.run_id, job, kind, now, "sending", None, now))
                    return ticket
            pause = min(max(delay, .01), 20)
            waited += pause
            require(waited <= self.profile.get("max_queue_wait_seconds", 600), "等待在途任务达到上限，请检查持久任务记录；未释放未知任务。")
            self.sleep(pause)

    def finish(self, ticket, status, task=None):
        import json
        require(status in {"done", "failed", "unknown", "submitted", "abandoned"}, "未知调度状态。")
        with self.connection() as db:
            db.execute("UPDATE attempts SET status=?,task_json=COALESCE(?,task_json),updated=? WHERE id=?",
                       (status, json.dumps(task) if task else None, self.clock(), ticket))

    def pending(self, job):
        with self.connection() as db:
            return db.execute("SELECT * FROM attempts WHERE job=? AND pool=? AND status IN ('submitted','unknown','sending') ORDER BY started DESC LIMIT 1", (job, self.pool)).fetchone()

    def completed(self, job):
        with self.connection() as db:
            return db.execute("SELECT * FROM attempts WHERE job=? AND pool=? AND kind='image' AND status='done' AND task_json IS NOT NULL ORDER BY started DESC LIMIT 1", (job, self.pool)).fetchone()

    def backoff(self, seconds):
        with self.connection() as db:
            old = db.execute("SELECT * FROM controls WHERE pool=?", (self.pool,)).fetchone()
            cap = max(1, (old["concurrency"] if old else self.profile["limits"]["max_inflight"]) // 2)
            until = max(self.clock()+seconds, old["cooldown"] if old else 0)
            db.execute("INSERT OR REPLACE INTO controls VALUES(?,?,?)", (self.pool, until, cap))

    def report(self):
        with self.connection() as db:
            rows = db.execute("SELECT id,job,kind,started,status,updated FROM attempts WHERE run_id=? ORDER BY started", (self.run_id,)).fetchall()
        return {"image_attempts": sum(r["kind"] == "image" for r in rows), "budget": self.budget,
                "events": [dict(r) for r in rows]}
