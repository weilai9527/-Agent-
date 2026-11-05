"""根据当前教职员授权和发布时冻结的名单，计算可见任务与班级完成情况。"""

import json
from collections import Counter, defaultdict

from . import identity


def visible_targets(targets, visible):
    return [cid for cid in targets if cid in visible]


def batches(values):
    values = list(values)
    for i in range(0, len(values), 100):
        yield values[i:i + 100]


def read_staff_tasks(db, ctx, task_view, *, workbench=False):
    classes = {row["class_id"]: row for row in identity.classes(ctx)}
    by_class = {cid: set() for cid in classes}
    if workbench:
        # 覆盖率的分母包括尚未领到任务的同班学生。按授权班级分批取名单，每班只取一次。
        for batch in batches(classes):
            by_class.update({cid: set(ids) for cid, ids in identity.roster(ctx, batch).items()})

    attr = "school_id=?"
    params = (ctx["school_id"],)
    if ctx["actor_type"] == "teacher":
        attr += " AND teacher_id=?"
        params += (ctx["actor_id"],)

    items = {}
    changed = set()
    task_totals = Counter()
    task_done = Counter()
    task_classes = defaultdict(set)
    assigned = defaultdict(set)
    done = defaultdict(set)
    class_expected = Counter()
    class_done = Counter()

    with db.transaction() as tx:
        # 先用任务和班级标识裁剪范围，再分批读取可见题文，避免受限管理员加载校内其他班级的题目。
        headers = tx.all(f"SELECT task_id,class_ids FROM training_tasks WHERE {attr} ORDER BY created_us DESC,task_id", params)
        allowed = {}
        for row in headers:
            targets = json.loads(row["class_ids"])
            subset = visible_targets(targets, classes)
            if subset:
                tid = row["task_id"]
                allowed[tid] = subset
                if len(subset) != len(targets):
                    changed.add(tid)

        for batch in batches(allowed):
            marks = ",".join("?" for _ in batch)
            for row in tx.all(f"SELECT * FROM training_tasks WHERE task_id IN ({marks})", tuple(batch)):
                item = task_view(row)
                item["class_ids"] = allowed[row["task_id"]]
                items[row["task_id"]] = item

        if not workbench:
            # 历史目录保留发布时的冻结人数。班级授权变更后，只能汇总仍可见班级的冻结人数。
            for batch in batches(changed):
                marks = ",".join("?" for _ in batch)
                grouped = tx.all(f"""SELECT task_id,class_id,COUNT(*) AS n FROM training_enrollments
                                    WHERE task_id IN ({marks}) GROUP BY task_id,class_id""", tuple(batch))
                for row in grouped:
                    if row["class_id"] in classes:
                        task_totals[row["task_id"]] += row["n"]
            for tid in changed:
                items[tid]["student_count"] = task_totals[tid]
            return {"items": [items[tid] for tid in allowed]}

        # 每项任务按学生唯一登记。先判断是否存在已完成的尝试，再汇总人数，重复完成不会增加分子。
        for batch in batches(allowed):
            marks = ",".join("?" for _ in batch)
            rows = tx.all(f"""SELECT e.task_id,e.class_id,e.student_id,EXISTS(
                       SELECT 1 FROM training_attempts a WHERE a.task_id=e.task_id
                       AND a.student_id=e.student_id AND a.status='completed') AS completed
                       FROM training_enrollments e WHERE e.task_id IN ({marks})""", tuple(batch))
            for row in rows:
                tid, cid, sid = row["task_id"], row["class_id"], row["student_id"]
                if cid not in by_class or sid not in by_class[cid]:
                    continue
                task_classes[cid].add(tid)
                assigned[cid].add(sid)
                class_expected[cid] += 1
                task_totals[tid] += 1
                if row["completed"]:
                    done[cid].add(sid)
                    class_done[cid] += 1
                    task_done[tid] += 1

    current = []
    for tid in allowed:
        if task_totals[tid]:
            active_classes = [cid for cid in allowed[tid] if tid in task_classes[cid]]
            current.append({**items[tid], "class_ids": active_classes,
                            "student_count": task_totals[tid], "completed_count": task_done[tid]})
    groups = [{
        **group, "enrolled_students": len(by_class[cid]), "task_count": len(task_classes[cid]),
        "assigned_students": len(assigned[cid]), "completed_students": len(done[cid]),
        "assigned_task_students": class_expected[cid], "completed_task_students": class_done[cid],
    } for cid, group in classes.items()]
    return {
        "items": current, "classes": groups,
        "summary": {"task_count": len(current), "enrolled_students": len(set().union(*by_class.values())),
                    "assigned_students": len(set().union(*assigned.values())),
                    "completed_students": len(set().union(*done.values())),
                    "assigned_task_students": sum(task_totals.values()), "completed_task_students": sum(task_done.values())}
    }
