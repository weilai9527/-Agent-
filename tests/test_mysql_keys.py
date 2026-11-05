import pytest

from shared.mysql_keys import EXACT_COLUMNS, require_exact_columns


def test_verifies_actual_columns_and_accepts_mixed_display_collation():
    tables = EXACT_COLUMNS["profile"]
    rows = [{"tbl": table, "col": column, "cmp_rule":"utf8mb4_0900_bin"}
            for table, columns in tables.items() for column in columns.split()]
    rows.append({"tbl":"profile_versions", "col":"profile", "cmp_rule":"utf8mb4_unicode_ci"})
    def fetch(sql, params):
        assert "INFORMATION_SCHEMA.COLUMNS" in sql and tuple(tables) == params
        return rows
    require_exact_columns(fetch, "profile")
    rows[1]["cmp_rule"] = "utf8mb4_0900_ai_ci"
    with pytest.raises(RuntimeError, match="profile_owners.actor_id"):
        require_exact_columns(fetch, "profile")
    rows.pop(1)
    with pytest.raises(RuntimeError, match=r"profile_owners.actor_id \(missing"):
        require_exact_columns(fetch, "profile")
