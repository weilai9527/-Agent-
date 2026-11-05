import sqlite3
import ssl
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from unittest.mock import Mock, patch

from shared.service_db import ServiceDatabase, Transaction


class ServiceDatabaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.env = {
            "TRAINING_DB_ENGINE": "sqlite",
            "TRAINING_SQLITE_PATH": str(Path(self.temp.name) / "training.sqlite"),
        }
        self.store = ServiceDatabase.from_env("training", self.env)
        self.schema = ["CREATE TABLE IF NOT EXISTS attempts (id INTEGER PRIMARY KEY, value TEXT)"]
        self.store.ensure_schema(self.schema)

    def test_commit_rollback_restart_and_binding(self):
        self.assertFalse(Path(self.env["TRAINING_SQLITE_PATH"]).stat().st_mode & 0o077)
        text = "O'Reilly? 50%; DROP TABLE attempts;"
        with self.store.transaction(write=True) as tx:
            self.assertEqual(tx.execute("INSERT INTO attempts VALUES (?, ?)", (1, text)), 1)
        with self.assertRaises(sqlite3.IntegrityError), self.store.transaction(write=True) as tx:
            tx.execute("INSERT INTO attempts VALUES (2, 'discard')")
            tx.execute("INSERT INTO attempts VALUES (1, 'duplicate')")

        restarted = ServiceDatabase.from_env("training", self.env)
        restarted.ensure_schema(self.schema)
        self.assertTrue(restarted.ping())
        with restarted.transaction() as tx:
            self.assertEqual(tx.all("SELECT * FROM attempts"), [{"id": 1, "value": text}])
            self.assertIsNone(tx.one("SELECT id FROM attempts WHERE value = ?", ("missing",)))
            with self.assertRaises(sqlite3.OperationalError):
                tx.execute("DELETE FROM attempts")

    def test_services_do_not_inherit_a_global_database(self):
        global_env = {**self.env, "DB_ENGINE": "sqlite", "SQLITE_PATH": self.env["TRAINING_SQLITE_PATH"]}
        with self.assertRaisesRegex(ValueError, "ANALYTICS_DB_ENGINE"):
            ServiceDatabase.from_env("analytics", global_env)
        other = ServiceDatabase.from_env("analytics", {
            **global_env, "ANALYTICS_DB_ENGINE": "sqlite",
            "ANALYTICS_SQLITE_PATH": str(Path(self.temp.name) / "analytics.sqlite"),
        })
        with other.transaction() as tx:
            self.assertIsNone(tx.one("SELECT name FROM sqlite_master WHERE name = 'attempts'"))
        with self.assertRaisesRegex(ValueError, "absolute"):
            ServiceDatabase.from_env("training", {**self.env, "TRAINING_SQLITE_PATH": ":memory:"})

    def test_concurrent_writers_do_not_lose_updates(self):
        with self.store.transaction(write=True) as tx:
            tx.execute("INSERT INTO attempts VALUES (1, '0')")
        barrier = Barrier(4, timeout=5)

        def increment(_):
            barrier.wait()
            for _ in range(8):
                with self.store.transaction(write=True) as tx:
                    old = tx.one("SELECT value FROM attempts WHERE id = 1")
                    tx.execute("UPDATE attempts SET value = ? WHERE id = 1", (int(old["value"]) + 1,))

        with ThreadPoolExecutor(max_workers=4) as workers:
            list(workers.map(increment, range(4)))
        with self.store.transaction() as tx:
            self.assertEqual(tx.one("SELECT value FROM attempts"), {"value": "32"})

    def test_mysql_params_only_replace_real_markers(self):
        cursor = Mock()
        Transaction(cursor, "mysql").execute(
            "SELECT '?' AS `?%`, ? AS value /* ? */ FROM attempts WHERE value LIKE 'x%' -- ?",
            ("I'm data?",),
        )
        cursor.execute.assert_called_once_with(
            "SELECT '?' AS `?%%`, %s AS value /* ? */ FROM attempts WHERE value LIKE 'x%%' -- ?",
            ("I'm data?",),
        )

    def test_mysql_connects_to_explicit_database_with_verified_tls(self):
        env = {
            "TRAINING_DB_ENGINE": "mysql", "TRAINING_MYSQL_HOST": "mysql.example.test",
            "TRAINING_MYSQL_USER": "training", "TRAINING_MYSQL_PASSWORD": "dummy-secret",
            "TRAINING_MYSQL_DATABASE": "training_db",
        }
        config = ServiceDatabase.from_env("training", env)
        self.assertNotIn("dummy-secret", repr(config))
        with patch("pymysql.connect") as connect:
            with config.transaction(write=True) as tx:
                tx.execute("UPDATE attempts SET value = ? WHERE id = ?", ("x", 1))
            kwargs = connect.call_args.kwargs
            self.assertEqual(kwargs["database"], "training_db")
            self.assertEqual(kwargs["user"], "training")
            self.assertTrue(kwargs["ssl"].check_hostname)
            self.assertEqual(kwargs["ssl"].verify_mode, ssl.CERT_REQUIRED)
            db = connect.return_value
            self.assertEqual([c.args[0] for c in db.cursor.return_value.execute.call_args_list],
                             ["START TRANSACTION READ WRITE", "UPDATE attempts SET value = %s WHERE id = %s"])
            db.commit.assert_called_once_with()
            db.close.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
