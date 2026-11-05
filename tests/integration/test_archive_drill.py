"""验证恢复演练实际使用的备份操作能保留已提交但尚未合并的 WAL 数据。"""
from contextlib import closing
import sqlite3

from scripts.smoke_restore import read_only, snapshot_file


def test_backup_includes_committed_revocation_that_only_exists_in_wal(tmp_path):
    live = tmp_path / "synthetic.sqlite"
    archive = tmp_path / "snapshot.sqlite"
    with closing(sqlite3.connect(live)) as writer, read_only(live) as pinned_reader:
        writer.execute("PRAGMA journal_mode=WAL")
        writer.execute("PRAGMA wal_autocheckpoint=0")
        writer.execute("CREATE TABLE credential (id INTEGER PRIMARY KEY,status TEXT)")
        writer.execute("INSERT INTO credential VALUES (1,'issued')")
        writer.commit()
        writer.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        pinned_reader.execute("BEGIN")
        assert pinned_reader.execute("SELECT status FROM credential").fetchone() == ("issued",)
        writer.execute("UPDATE credential SET status='revoked'")
        writer.commit()
        assert (tmp_path / "synthetic.sqlite-wal").stat().st_size > 0
        assert pinned_reader.execute("SELECT status FROM credential").fetchone() == ("issued",)
        snapshot_file(live, archive)
    with read_only(archive) as restored:
        assert restored.execute("SELECT status FROM credential").fetchone() == ("revoked",)
