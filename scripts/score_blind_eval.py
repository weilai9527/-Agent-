#!/usr/bin/env python3
"""生成供评审员盲评的表格，比较两个评分版本对同一组回答的评分。"""

import argparse
import csv
import hashlib
import json
import math
from pathlib import Path


def read_rows(path, required):
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        missing = set(required) - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"{path}: missing columns {sorted(missing)}")
        rows = []
        for row in reader:
            if None in row or any(value is None for value in row.values()):
                raise ValueError(f"{path}:{reader.line_num}: row length differs from header")
            rows.append(row)
        return rows


def index_rows(rows, source):
    result = {}
    for row in rows:
        key = row["sample_id"].strip()
        if not key or key in result:
            raise ValueError(f"{source}: empty or duplicate sample_id {key!r}")
        result[key] = row
    return result


def stable_hash(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def load_samples(args):
    required = ["sample_id", args.group_by, "interview_id", "question", "answer"]
    if args.command == "compare":
        required += ["old_score", "new_score"]
    all_samples = index_rows(read_rows(args.samples, required), args.samples)
    selected = {}
    interview_groups = {}
    for key, row in all_samples.items():
        group = row[args.group_by].strip()
        interview = row["interview_id"].strip()
        if not group or not interview:
            raise ValueError(f"{key}: missing group or interview id")
        if interview_groups.setdefault(interview, group) != group:
            raise ValueError(f"{key}: conflicting groups for interview {interview}")
        # 整个候选人或整场面试进入同一子集，防止其相邻回答同时出现在调参集与留出集。
        bucket = int(stable_hash(f"{args.seed}/{group}"), 16) % 100
        split = "holdout" if bucket < args.holdout_percent else "dev"
        if args.split in ("all", split):
            selected[key] = row
    if not selected:
        raise ValueError(f"no samples selected for {args.split}")
    return selected


def prepare(samples, args):
    paths = [args.out / f"reviewer_{reviewer}.csv" for reviewer in ("a", "b")]
    if any(path.exists() for path in paths):
        raise ValueError("review sheets already exist; choose a new output directory")
    args.out.mkdir(parents=True, exist_ok=True)
    fields = ["sample_id", "question", "answer", "rubric", "band", "reason"]
    for path in paths:
        with path.open("x", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            for key in sorted(samples, key=lambda k: stable_hash(f"{args.seed}/{path.name}/{k}")):
                row = samples[key]
                writer.writerow({field: row.get(field, "") for field in fields[:4]})
    print(f"{len(samples)} samples per reviewer in {args.out}")


def load_labels(path, keys, partial=False):
    rows = index_rows(read_rows(path, ["sample_id", "band"]), path)
    unexpected = rows.keys() - keys
    missing = keys - rows.keys()
    if unexpected or (missing and not partial):
        raise ValueError(f"{path}: unexpected IDs {sorted(unexpected)[:5]}, missing {sorted(missing)[:5]}")
    labels = {}
    for key, row in rows.items():
        raw = row["band"].strip()
        if raw not in {"0", "1", "2", "3", "4"}:
            raise ValueError(f"{path}: {key}: human band must be an integer 0..4")
        labels[key] = int(raw)
    return labels


def machine_band(row, field, cuts):
    value = row[field].strip()
    if not value:
        return None
    try:
        score = float(value)
    except ValueError:
        raise ValueError(f"{row['sample_id']}: invalid {field} {value!r}") from None
    if not math.isfinite(score) or not 0 <= score <= 100:
        raise ValueError(f"{row['sample_id']}: {field} must be blank or 0..100")
    return sum(score > cut for cut in cuts)


def rate(numerator, denominator):
    return {"n": numerator, "of": denominator, "rate": numerator / denominator if denominator else None}


def agreement(pairs):
    # 采用线性权重时，计算加权 kappa 的分子和分母会约去同一个距离缩放因子。
    n = len(pairs)
    actual = [0] * 5
    predicted = [0] * 5
    observed = 0
    for left, right in pairs:
        actual[left] += 1
        predicted[right] += 1
        observed += abs(left - right)
    expected_sum = sum(actual[i] * predicted[j] * abs(i - j) for i in range(5) for j in range(5))
    return {
        "exact": rate(sum(left == right for left, right in pairs), n),
        "linear_weighted_kappa": 1 - observed * n / expected_sum if expected_sum else None,
    }


def metrics(predictions, gold, keys):
    scored = [k for k in keys if predictions[k] is not None]
    # 误高评率只在实际出分的低档回答中计算，同时报告其覆盖率，避免拒评过多造成误读。
    scored_low = [k for k in scored if gold[k] <= 1]
    return {
        "coverage": rate(len(scored), len(keys)),
        "low_answer_coverage": rate(len(scored_low), sum(gold[k] <= 1 for k in keys)),
        "false_high_among_scored_low": rate(sum(predictions[k] >= 3 for k in scored_low), len(scored_low)),
        "agreement_with_gold": agreement([(gold[k], predictions[k]) for k in scored]),
    }


def compare(samples, args):
    if args.cutoffs and (args.old_cutoffs or args.new_cutoffs):
        raise ValueError("choose either shared --cutoffs or version-specific cutoffs")
    cutoffs = {
        "old": args.cutoffs or args.old_cutoffs or [30, 50, 70, 90],
        "new": args.cutoffs or args.new_cutoffs or [20, 40, 60, 80],
    }
    for version, cuts in cutoffs.items():
        if len(set(cuts)) != 4 or sorted(cuts) != cuts or not all(0 <= cut < 100 for cut in cuts):
            raise ValueError(f"{version}: provide four increasing cutoffs within [0,100)")
    keys = samples.keys()
    first = load_labels(args.reviewer_a, keys)
    second = load_labels(args.reviewer_b, keys)
    disputes = {k for k in keys if first[k] != second[k]}
    adjudicated = load_labels(args.adjudication, disputes, partial=True) if args.adjudication else {}
    if disputes - adjudicated.keys():
        raise ValueError(f"{len(disputes - adjudicated.keys())} disagreements require adjudication; sample IDs: {sorted(disputes - adjudicated.keys())}")
    gold = {**first, **adjudicated}
    predictions = {
        version: {key: machine_band(row, f"{version}_score", cutoffs[version]) for key, row in samples.items()}
        for version in ("old", "new")
    }
    both = [k for k in keys if all(p[k] is not None for p in predictions.values())]
    print(json.dumps({
        "subset": args.split, "group_by": args.group_by,
        "groups": len({row[args.group_by].strip() for row in samples.values()}),
        "samples": len(keys), "group_split_seed": args.seed, "holdout_percent": args.holdout_percent,
        "band_cutoffs": cutoffs, "cutoff_mode": "shared" if args.cutoffs else "per_version", "adjudicated_count": len(disputes),
        "human_agreement_before_adjudication": agreement([(first[k], second[k]) for k in keys]),
        "all_samples": {version: metrics(p, gold, keys) for version, p in predictions.items()},
        "both_scored": {version: metrics(p, gold, both) for version, p in predictions.items()},
    }, ensure_ascii=False, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    prep = sub.add_parser("prepare")
    comp = sub.add_parser("compare")
    for command in (prep, comp):
        command.add_argument("samples", type=Path)
        command.add_argument("--group-by", choices=["candidate_id", "interview_id"], default="candidate_id")
        command.add_argument("--seed", default="score-v1")
        command.add_argument("--split", choices=["holdout", "dev", "all"], default="holdout")
        command.add_argument("--holdout-percent", type=int, choices=range(1, 100), metavar="1-99", default=25)
    prep.add_argument("--out", type=Path, required=True)
    comp.add_argument("reviewer_a", type=Path)
    comp.add_argument("reviewer_b", type=Path)
    comp.add_argument("--adjudication", type=Path)
    comp.add_argument("--cutoffs", type=float, nargs=4, help="common band boundaries for a shared decision policy")
    comp.add_argument("--old-cutoffs", type=float, nargs=4, help="old rubric boundaries (default: 30 50 70 90)")
    comp.add_argument("--new-cutoffs", type=float, nargs=4, help="new rubric boundaries (default: 20 40 60 80)")
    args = parser.parse_args()
    try:
        samples = load_samples(args)
        if args.command == "prepare":
            prepare(samples, args)
        else:
            compare(samples, args)
    except (OSError, ValueError, csv.Error) as exc:
        parser.exit(2, f"error: {exc}\n")


if __name__ == "__main__":
    main()
