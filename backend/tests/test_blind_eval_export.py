import csv
from types import SimpleNamespace

import pytest

from scripts.score_blind_eval import load_labels, prepare, read_rows


def test_formula_safe_sheets_keep_original_samples_and_roundtrip_ids(tmp_path):
    payloads = ["=HYPERLINK(\"https://example.test\")", " +SUM(1,2)", "-2+3", "@SUM(1)", "\ttext", "\n=1"]
    samples = {f"sample-{index}": {"question": value, "answer": value, "rubric": value}
               for index, value in enumerate(payloads)}
    original = {key: dict(row) for key, row in samples.items()}
    prepare(samples, SimpleNamespace(out=tmp_path / "sheets", seed="test"))
    assert samples == original
    for name in ("a", "b"):
        path = tmp_path / "sheets" / f"reviewer_{name}.csv"
        rows = read_rows(path, ["sample_id", "question", "answer", "rubric", "band"])
        assert {row["sample_id"] for row in rows} == set(samples)
        for row in rows:
            assert all(row[field] == "'" + samples[row["sample_id"]][field]
                       for field in ("question", "answer", "rubric"))
            row["band"] = "2"
        with path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=rows[0].keys())
            writer.writeheader()
            writer.writerows(rows)
        assert load_labels(path, samples.keys()) == dict.fromkeys(samples, 2)


def test_formula_sample_id_is_rejected_before_creating_sheets(tmp_path):
    output = tmp_path / "sheets"
    with pytest.raises(ValueError, match="sample_id"):
        prepare({"=1+1": {}}, SimpleNamespace(out=output, seed="test"))
    assert not output.exists()
