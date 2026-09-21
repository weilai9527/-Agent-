from __future__ import annotations

import os
import unittest


@unittest.skipUnless(
    os.environ.get("RUN_MYSQL_INTEGRATION_TESTS") == "1",
    "set RUN_MYSQL_INTEGRATION_TESTS=1 to test the configured MySQL database",
)
class MySQLCollationIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        from admin_backend.src import main as admin_main
        from admin_backend.src.database import DB_ENGINE, MYSQL_COLLATION, db

        if DB_ENGINE != "mysql":
            raise unittest.SkipTest("the configured database is not MySQL")
        cls.admin_main = admin_main
        cls.collation = MYSQL_COLLATION
        cls.db = db

    def test_cross_schema_columns_use_the_same_collation(self) -> None:
        cursor = self.db.execute(
            """
            SELECT TABLE_NAME, COLUMN_NAME, COLLATION_NAME
            FROM information_schema.COLUMNS
            WHERE TABLE_SCHEMA = DATABASE()
              AND (TABLE_NAME, COLUMN_NAME) IN (
                ('users', 'id'),
                ('student_enrollments', 'user_id'),
                ('catalog_job_roles', 'id'),
                ('program_job_roles', 'job_role_id')
              )
            """
        )
        try:
            collations = {
                (row["TABLE_NAME"], row["COLUMN_NAME"]): row["COLLATION_NAME"]
                for row in cursor.fetchall()
            }
        finally:
            cursor.close()

        self.assertEqual(collations[("users", "id")], self.collation)
        self.assertEqual(collations[("student_enrollments", "user_id")], self.collation)
        self.assertEqual(collations[("catalog_job_roles", "id")], self.collation)
        self.assertEqual(collations[("program_job_roles", "job_role_id")], self.collation)

    def test_campus_queries_execute_without_collation_errors(self) -> None:
        students = self.admin_main.list_campus_students()
        overview = self.admin_main.campus_overview_data()

        self.assertIsInstance(students, list)
        self.assertIn("students", overview)
        self.assertIn("programs", overview)


if __name__ == "__main__":
    unittest.main()
