#!/usr/bin/env python3
"""Exploratory group-level analysis for counterintuitive collaboration patterns."""

from __future__ import annotations

import json
import math
import random
import statistics
from collections import Counter, defaultdict, deque
from pathlib import Path


ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
DATASETS = {
    "旧数据": DATA,
    "数据集A": DATA / "datasets" / "cond-a",
    "数据集B": DATA / "datasets" / "cond-b",
    "数据集C": DATA / "datasets" / "cond-c",
    "数据集D": DATA / "datasets" / "cond-d",
}
WINDOW_MS = 5 * 60 * 1000
RANDOM_SEED = 20261116


def visual_valid(code: str) -> bool:
    try:
        spec = json.loads(code)
    except (TypeError, json.JSONDecodeError):
        return False
    return isinstance(spec, dict) and any(key in spec for key in ("mark", "layer", "hconcat", "vconcat", "concat", "repeat", "facet"))


def rank(values: list[float]) -> list[float]:
    indexed = sorted(enumerate(values), key=lambda item: item[1])
    ranks = [0.0] * len(values)
    cursor = 0
    while cursor < len(indexed):
        end = cursor + 1
        while end < len(indexed) and indexed[end][1] == indexed[cursor][1]:
            end += 1
        average = (cursor + 1 + end) / 2
        for index in range(cursor, end):
            ranks[indexed[index][0]] = average
        cursor = end
    return ranks


def pearson(left: list[float], right: list[float]) -> float | None:
    if len(left) < 3 or len(left) != len(right):
        return None
    mean_left = statistics.mean(left)
    mean_right = statistics.mean(right)
    numerator = sum((a - mean_left) * (b - mean_right) for a, b in zip(left, right))
    denominator = math.sqrt(sum((a - mean_left) ** 2 for a in left) * sum((b - mean_right) ** 2 for b in right))
    return numerator / denominator if denominator else None


def spearman(left: list[float], right: list[float]) -> float | None:
    return pearson(rank(left), rank(right))


def bootstrap_spearman(left: list[float], right: list[float], iterations: int = 3000) -> tuple[float | None, float | None]:
    if len(left) < 5:
        return None, None
    rng = random.Random(RANDOM_SEED + len(left))
    estimates = []
    for _ in range(iterations):
        indices = [rng.randrange(len(left)) for _ in left]
        estimate = spearman([left[index] for index in indices], [right[index] for index in indices])
        if estimate is not None and math.isfinite(estimate):
            estimates.append(estimate)
    if len(estimates) < iterations // 2:
        return None, None
    estimates.sort()
    return estimates[int(0.025 * len(estimates))], estimates[int(0.975 * len(estimates)) - 1]


def share(counter: Counter, actor: str) -> float:
    total = sum(counter.values())
    return counter[actor] / total if total else 0.0


def dominant(counter: Counter) -> tuple[str, float]:
    if not counter or sum(counter.values()) <= 0:
        return "", 0.0
    actor, count = counter.most_common(1)[0]
    return actor, count / sum(counter.values())


def active_minutes(events: list[dict]) -> float:
    if len(events) < 2:
        return 0.0
    times = sorted(event["t"] for event in events)
    return sum(min(WINDOW_MS, max(0, current - previous)) for previous, current in zip(times, times[1:])) / 60000


def final_owner_counts(snapshot: dict | None, content_key: str) -> Counter:
    if not snapshot:
        return Counter()
    lines = str(snapshot.get(content_key, "")).replace("\r\n", "\n").split("\n")
    owners = snapshot.get("owners", [])
    result = Counter()
    for index, line in enumerate(lines):
        if not line.strip():
            continue
        result[owners[index] if index < len(owners) else snapshot.get("actor", "")] += 1
    return result


def load_groups(dataset_name: str, root: Path) -> list[dict]:
    index = json.loads((root / "index.json").read_text(encoding="utf-8"))
    groups = []
    for meta in index["groups"]:
        payload = json.loads((ROOT / meta["file"]).read_text(encoding="utf-8"))
        payload["_dataset"] = dataset_name
        groups.append(payload)
    return groups


def measure_group(group: dict) -> dict:
    members = [member["id"] for member in group["members"]]
    member_set = set(members)
    streams = []
    behavior = Counter()
    production = Counter()
    code_counts = Counter(item["actor"] for item in group["code"] if item["actor"] in member_set)
    note_counts = Counter(item["actor"] for item in group["notes"] if item["actor"] in member_set)
    chat_counts = Counter()

    for kind, field in (("code", "code"), ("note", "notes"), ("action", "actions"), ("cursor", "cursor")):
        for item in group[field]:
            actor = item.get("actor", "")
            if actor not in member_set:
                continue
            event = {"t": item["t"], "actor": actor, "kind": kind}
            streams.append(event)
            behavior[actor] += 1
            if kind != "cursor":
                production[actor] += 1

    room_chat = shared_questions = private_questions = forwards = 0
    ai_replies = []
    questions = []
    pending: dict[tuple[str, str], deque] = defaultdict(deque)
    for item in group["chat"]:
        kind = item.get("kind", "chat")
        channel = item.get("channel") or ("shared" if kind in {"ai-question", "ai-reply"} else "room")
        actor = item.get("actor", "")
        if kind == "chat":
            room_chat += 1
        elif kind == "private-forward":
            forwards += 1
        elif kind == "ai-question":
            if channel == "private":
                private_questions += 1
            else:
                shared_questions += 1
            owner = item.get("owner") or actor
            question = {"t": item["t"], "actor": owner, "channel": channel, "reply": None}
            questions.append(question)
            pending[(channel, owner)].append(question)
        elif kind == "ai-reply":
            owner = item.get("owner") or ""
            reply = {"t": item["t"], "owner": owner, "channel": channel, "questioner": ""}
            key = (channel, owner)
            if pending[key]:
                question = pending[key].popleft()
                question["reply"] = reply
                reply["questioner"] = question["actor"]
            elif channel == "shared":
                candidate = next((queue for (candidate_channel, _), queue in pending.items() if candidate_channel == "shared" and queue), None)
                if candidate:
                    question = candidate.popleft()
                    question["reply"] = reply
                    reply["questioner"] = question["actor"]
            ai_replies.append(reply)

        if actor in member_set and kind not in {"system", "ai-reply"}:
            streams.append({"t": item["t"], "actor": actor, "kind": "chat"})
            behavior[actor] += 1
            production[actor] += 1
            chat_counts[actor] += 1

    streams.sort(key=lambda item: item["t"])
    production_stream = [item for item in streams if item["kind"] != "cursor"]
    handoffs = sum(left["actor"] != right["actor"] for left, right in zip(production_stream, production_stream[1:]))
    handoff_rate = handoffs / max(1, len(production_stream) - 1)
    active = active_minutes(production_stream)

    first_times = {}
    for event in production_stream:
        first_times.setdefault(event["actor"], event["t"])
    span = max(1, group["timelineEnd"] - group["timelineStart"])
    onset = {actor: (first_times.get(actor, group["timelineEnd"]) - group["timelineStart"]) / span for actor in members}

    final_code = final_owner_counts(group["code"][-1] if group["code"] else None, "code")
    final_note = final_owner_counts(group["notes"][-1] if group["notes"] else None, "text")
    final_artifact = final_code + final_note
    dominant_behavior_actor, dominance = dominant(behavior)
    dominant_production_actor, production_dominance = dominant(production)
    dominant_code_actor, code_dominance = dominant(code_counts)
    dominant_note_actor, note_dominance = dominant(note_counts)
    dominant_chat_actor, chat_dominance = dominant(chat_counts)
    dominant_final_actor, final_dominance = dominant(Counter({actor: final_artifact[actor] for actor in members}))

    response_other = response_any = response_artifact = 0
    for reply in ai_replies:
        after = [event for event in production_stream if reply["t"] < event["t"] <= reply["t"] + WINDOW_MS]
        if after:
            response_any += 1
        if any(event["kind"] in {"code", "note"} for event in after):
            response_artifact += 1
        questioner = reply.get("questioner", "")
        if questioner and any(event["actor"] != questioner for event in after):
            response_other += 1

    repair_opportunities = repair_successes = 0
    code = group["code"]
    for question in questions:
        before = next((item for item in reversed(code) if item["t"] <= question["t"]), None)
        after = next((item for item in code if question["t"] < item["t"] <= question["t"] + WINDOW_MS), None)
        if before and after and not visual_valid(before.get("code", "")):
            repair_opportunities += 1
            if visual_valid(after.get("code", "")):
                repair_successes += 1

    change_entries = sum(len(item.get("changes", [])) for item in group["code"])
    final_code_lines = sum(final_code.values())
    valid_snapshots = sum(visual_valid(item.get("code", "")) for item in group["code"])
    total_human_behaviors = sum(behavior.values())
    total_production = sum(production.values())
    ai_questions = shared_questions + private_questions
    eligible = (len(group["code"]) + len(group["notes"]) >= 10) and (total_human_behaviors >= 100)

    member_rows = []
    for actor in members:
        behavior_share = share(behavior, actor)
        artifact_share = share(final_artifact, actor)
        member_rows.append({
            "actor": actor,
            "behavior_share": behavior_share,
            "production_share": share(production, actor),
            "final_code_share": share(final_code, actor),
            "final_note_share": share(final_note, actor),
            "artifact_share": artifact_share,
            "share_gap": artifact_share - behavior_share,
            "onset": onset[actor],
        })

    return {
        "dataset": group["_dataset"],
        "group": group["groupId"],
        "members": len(members),
        "eligible": eligible,
        "completed": bool(group["completion"]),
        "duration_min": (group["timelineEnd"] - group["timelineStart"]) / 60000,
        "active_min": active,
        "behavior_total": total_human_behaviors,
        "production_total": total_production,
        "code": len(group["code"]),
        "notes": len(group["notes"]),
        "room_chat": room_chat,
        "shared_questions": shared_questions,
        "private_questions": private_questions,
        "ai_questions": ai_questions,
        "ai_replies": len(ai_replies),
        "forwards": forwards,
        "ai_per_100": 100 * ai_questions / max(1, total_production),
        "context_events_per_100": 100 * (room_chat + len(group["notes"])) / max(1, total_production),
        "handoff_rate": handoff_rate,
        "dominance": dominance,
        "production_dominance": production_dominance,
        "final_dominance": final_dominance,
        "dominant_behavior": dominant_behavior_actor,
        "dominant_production": dominant_production_actor,
        "dominant_code": dominant_code_actor,
        "dominant_note": dominant_note_actor,
        "dominant_chat": dominant_chat_actor,
        "dominant_final": dominant_final_actor,
        "code_dominance": code_dominance,
        "note_dominance": note_dominance,
        "chat_dominance": chat_dominance,
        "final_code_lines": final_code_lines,
        "final_ai_lines": final_code["AI"],
        "ai_final_share": share(final_code, "AI"),
        "change_entries": change_entries,
        "churn_per_final_line": change_entries / max(1, final_code_lines),
        "valid_snapshot_rate": valid_snapshots / max(1, len(group["code"])),
        "reply_response_any": response_any,
        "reply_response_artifact": response_artifact,
        "reply_response_other": response_other,
        "reply_count": len(ai_replies),
        "repair_opportunities": repair_opportunities,
        "repair_successes": repair_successes,
        "member_rows": member_rows,
    }


def correlation_table(rows: list[dict]) -> list[dict]:
    outcomes = {
        "成员主导度": "dominance",
        "成员交接率": "handoff_rate",
        "共享上下文事件率": "context_events_per_100",
        "代码返工强度": "churn_per_final_line",
        "有效可视化快照率": "valid_snapshot_rate",
        "活跃分钟": "active_min",
    }
    results = []
    for dataset in DATASETS:
        subset = [row for row in rows if row["dataset"] == dataset and row["eligible"]]
        for label, key in outcomes.items():
            left = [row["ai_questions"] for row in subset]
            right = [row[key] for row in subset]
            # Correlation is not interpretable when AI use barely varies.
            if len(set(left)) < 3:
                results.append({
                    "dataset": dataset,
                    "outcome": label,
                    "n": len(subset),
                    "rho": None,
                    "ci_low": None,
                    "ci_high": None,
                    "reason": "AI question count has fewer than three distinct values",
                })
                continue
            rho = spearman(left, right)
            low, high = bootstrap_spearman(left, right)
            results.append({"dataset": dataset, "outcome": label, "n": len(subset), "rho": rho, "ci_low": low, "ci_high": high})
    return results


def summarize(rows: list[dict]) -> dict:
    dataset_summary = []
    for dataset in DATASETS:
        subset = [row for row in rows if row["dataset"] == dataset]
        eligible = [row for row in subset if row["eligible"]]
        dataset_summary.append({
            "dataset": dataset,
            "groups": len(subset),
            "eligible": len(eligible),
            "completed": sum(row["completed"] for row in subset),
            "ai_questions": sum(row["ai_questions"] for row in subset),
            "median_ai": statistics.median([row["ai_questions"] for row in eligible]) if eligible else 0,
            "median_dominance": statistics.median([row["dominance"] for row in eligible]) if eligible else 0,
            "median_handoff": statistics.median([row["handoff_rate"] for row in eligible]) if eligible else 0,
            "median_context": statistics.median([row["context_events_per_100"] for row in eligible]) if eligible else 0,
        })

    quiet_contributors = []
    busy_low_artifact = []
    late_contributors = []
    for row in rows:
        if not row["eligible"]:
            continue
        for member in row["member_rows"]:
            base = {"dataset": row["dataset"], "group": row["group"], **member}
            if member["behavior_share"] <= 0.25 and member["artifact_share"] >= 0.35 and member["share_gap"] >= 0.15:
                quiet_contributors.append(base)
            if member["behavior_share"] >= 0.45 and member["artifact_share"] <= 0.20:
                busy_low_artifact.append(base)
            if member["onset"] >= 0.35 and member["artifact_share"] >= 0.30:
                late_contributors.append(base)

    eligible_completed = [row for row in rows if row["eligible"] and row["completed"]]
    low_ai_efficient = sorted(
        eligible_completed,
        key=lambda row: (row["ai_questions"], row["active_min"], row["production_total"]),
    )[:12]
    high_ai_no_copy = sorted(
        [row for row in rows if row["eligible"] and row["ai_questions"] >= 5 and row["ai_final_share"] == 0],
        key=lambda row: (-row["ai_questions"], row["dataset"], row["group"]),
    )
    high_activity_incomplete = sorted(
        [row for row in rows if row["eligible"] and not row["completed"]],
        key=lambda row: -row["behavior_total"],
    )
    specialized = [
        row for row in rows
        if row["eligible"] and len({actor for actor in (row["dominant_code"], row["dominant_note"], row["dominant_chat"]) if actor}) >= 2
    ]
    ai_repair = [row for row in rows if row["repair_opportunities"]]
    private_groups = [row for row in rows if row["private_questions"]]

    return {
        "analysis_date": "2026-11-16",
        "unit": "dataset-by-group session",
        "groups_total": len(rows),
        "groups_eligible": sum(row["eligible"] for row in rows),
        "dataset_summary": dataset_summary,
        "correlations": correlation_table(rows),
        "quiet_contributors": sorted(quiet_contributors, key=lambda item: -item["share_gap"]),
        "busy_low_artifact": sorted(busy_low_artifact, key=lambda item: item["artifact_share"] - item["behavior_share"]),
        "late_contributors": sorted(late_contributors, key=lambda item: (-item["artifact_share"], -item["onset"])),
        "low_ai_efficient": low_ai_efficient,
        "high_ai_no_copy": high_ai_no_copy,
        "high_activity_incomplete": high_activity_incomplete,
        "specialized": specialized,
        "ai_repair": ai_repair,
        "private_summary": {
            "groups": len(private_groups),
            "questions": sum(row["private_questions"] for row in private_groups),
            "forwards": sum(row["forwards"] for row in private_groups),
            "groups_with_forward": sum(row["forwards"] > 0 for row in private_groups),
            "reply_count": sum(row["reply_count"] for row in private_groups),
            "reply_other_response": sum(row["reply_response_other"] for row in private_groups),
        },
        "rows": rows,
    }


def main() -> None:
    groups = [group for dataset, root in DATASETS.items() for group in load_groups(dataset, root)]
    rows = [measure_group(group) for group in groups]
    print(json.dumps(summarize(rows), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
