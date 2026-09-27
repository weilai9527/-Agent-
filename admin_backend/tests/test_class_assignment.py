import os
from pathlib import Path
import subprocess
import sys
import textwrap

from cryptography.fernet import Fernet


def run_isolated(tmp_path, script):
    completed = subprocess.run(
        [sys.executable, "-c", textwrap.dedent(script)],
        cwd=Path(__file__).resolve().parents[2],
        env={
            **os.environ,
            "DB_ENGINE": "sqlite",
            "SQLITE_PATH": str(tmp_path / "classes.sqlite"),
            "STUDENT_TEMP_PASSWORD_KEY": Fernet.generate_key().decode("ascii"),
            "PYTHONIOENCODING": "utf-8",
        },
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr


def test_numbered_classes_and_existing_enrollment_are_assigned_safely(tmp_path):
    run_isolated(tmp_path, '''
        import admin_backend.src.main as main

        for name, expected in [
            ("G22计算机应用技术1班", ("计算机应用技术", "G22")),
            ("G22计算机应用技术12班", ("计算机应用技术", "G22")),
            ("G22数字媒体技术(中外合作办学)2班", ("数字媒体技术(中外合作办学)", "G22")),
            ("GWG20计算机应用技术班", ("计算机应用技术", "GWG20")),
            ("2301软件工程班", ("软件工程", "2301")),
            ("1计算机1班", ("计算机", "1")),
            ("2301CP", (None, "2301CP")),
            ("123班", (None, "123班")),
        ]:
            assert main.split_registration_class_name(name) == expected, name

        for user_id in ("first", "second", "unassigned", "ambiguous", "rollback"):
            main.db.execute(
                "INSERT INTO users (id, email, password_hash, name) VALUES (?, ?, ?, ?)",
                (user_id, f"{user_id}@example.com", "unused", user_id),
            )
        main.db.commit()
        main.db.begin()
        main.assign_registration_to_class("first", "20260001", "计算机学院", "G22计算机应用技术1班")
        main.assign_registration_to_class("second", "20260002", "计算机学院", "G22计算机应用技术2班")
        main.db.commit()
        programs = main.all_rows("SELECT * FROM campus_programs")
        assert len(programs) == 1
        assert programs[0]["name"] == "计算机应用技术"
        classes = main.all_rows("SELECT * FROM campus_classes")
        assert {row["name"] for row in classes} == {"G22计算机应用技术1班", "G22计算机应用技术2班"}
        first = main.one("SELECT * FROM student_enrollments WHERE user_id = 'first'")
        second = main.one("SELECT * FROM student_enrollments WHERE user_id = 'second'")
        assert first["class_id"] != second["class_id"]

        # A focus action creates an enrollment even before the class is known.
        main.upsert_student_enrollment("unassigned", class_id=None, status="inactive", focus_flag=True, note="keep")
        main.db.begin()
        main.assign_registration_to_class("unassigned", "20260003", "计算机学院", "G22计算机应用技术1班")
        main.db.commit()
        assigned = main.one("SELECT * FROM student_enrollments WHERE user_id = 'unassigned'")
        assert assigned["class_id"] == first["class_id"]
        assert assigned["focus_flag"] == 1 and assigned["status"] == "inactive" and assigned["note"] == "keep"
        main.assign_registration_to_class("first", "20260001", "计算机学院", "G22计算机应用技术2班")
        assert main.one("SELECT * FROM student_enrollments WHERE user_id = 'first'") == first
        assert len(main.all_rows("SELECT id FROM campus_classes")) == 2

        # Class assignment must be part of the caller's import transaction.
        main.db.begin()
        main.assign_registration_to_class("rollback", "20260004", "计算机学院", "G22计算机应用技术3班")
        main.db.rollback()
        assert main.one("SELECT id FROM student_enrollments WHERE user_id = 'rollback'") is None
        assert len(main.all_rows("SELECT id FROM campus_classes")) == 2

        college_id = programs[0]["college_id"]
        main.db.execute("INSERT INTO campus_programs (id, college_id, name) VALUES (?, ?, ?)",
                        ("other", college_id, "Other program"))
        main.db.execute("INSERT INTO campus_classes (id, program_id, name, invite_code) VALUES (?, ?, ?, ?)",
                        ("duplicate", "other", "G22计算机应用技术1班", "duplicate"))
        main.db.commit()
        main.assign_registration_to_class("ambiguous", "20260005", "计算机学院", "G22计算机应用技术1班")
        assert main.one("SELECT id FROM student_enrollments WHERE user_id = 'ambiguous'") is None
    ''')


def test_workbook_import_assigns_new_updated_and_migrated_accounts_atomically(tmp_path):
    run_isolated(tmp_path, '''
        from io import BytesIO
        from openpyxl import Workbook
        import admin_backend.src.main as main

        def workbook(numbers):
            book = Workbook()
            book.active.append(["学号", "姓名", "学院", "班级"])
            for number in numbers:
                book.active.append([number, "Test student", "计算机学院", "G22计算机应用技术1班"])
            output = BytesIO()
            book.save(output)
            return output.getvalue()

        for user_id, number in [("existing", "20260002"), ("legacy", "20260003")]:
            main.db.execute(
                "INSERT INTO users (id,email,password_hash,student_no,name) VALUES (?,?,?,?,?)",
                (user_id, f"{number}@student.local", "existing-hash", number if user_id == "existing" else None, user_id),
            )
        main.db.commit()
        result = main.import_student_accounts_from_workbook(workbook(["20260001", "20260002", "20260003"]))
        assert (result["created"], result["updated"], result["migrated"]) == (1, 1, 1)
        assert len(main.all_rows("SELECT id FROM student_enrollments WHERE class_id IS NOT NULL")) == 3
        assert len(main.all_rows("SELECT id FROM campus_classes")) == 1
        assert main.one("SELECT password_hash FROM users WHERE id='existing'")["password_hash"] == "existing-hash"
        main.import_student_accounts_from_workbook(workbook(["20260001", "20260002", "20260003"]))
        assert len(main.all_rows("SELECT id FROM student_enrollments")) == 3

        original = main.assign_registration_to_class
        def fail_second(user_id, student_no, college, class_name):
            original(user_id, student_no, college, class_name)
            if student_no == "20260005":
                raise RuntimeError("test import failure")
        main.assign_registration_to_class = fail_second
        try:
            main.import_student_accounts_from_workbook(workbook(["20260004", "20260005"]))
        except RuntimeError as exc:
            assert str(exc) == "test import failure"
        else:
            raise AssertionError("Expected import rollback")
        assert len(main.all_rows("SELECT id FROM users")) == 3
        assert len(main.all_rows("SELECT id FROM student_enrollments")) == 3
    ''')
