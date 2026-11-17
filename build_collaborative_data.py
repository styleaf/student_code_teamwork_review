#!/usr/bin/env python3
"""Build replay-ready datasets from unified collaborative event CSV files."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from collections import Counter, defaultdict, deque
from datetime import datetime
from pathlib import Path

from build_data import (
    LOCAL_TZ,
    MEMBER_COLORS,
    add_content_owners,
    add_image_owners,
    clean_note,
    parse_json,
    parse_time,
    safe_int,
)


ROOT = Path(__file__).resolve().parent
DEFAULT_SOURCE_DIR = ROOT / "raw_data"
OUTPUT = ROOT / "data" / "datasets"
ASSETS = ROOT / "data" / "assets"
DATASETS = [
    ("cond-a", "数据集 A", "collaborative_cond_a_events.csv"),
    ("cond-b", "数据集 B", "collaborative_cond_b_events.csv"),
    ("cond-c", "数据集 C", "collaborative_cond_c_events.csv"),
    ("cond-d", "数据集 D", "collaborative_cond_d_events.csv"),
]


def actor_fallback(user_id: str) -> str:
    compact = re.sub(r"[^0-9A-Za-z]", "", user_id or "")
    return f"成员-{compact[-6:] or '未知'}"


def group_filename(group_id: str) -> str:
    return f"group-{hashlib.sha1(group_id.encode('utf-8')).hexdigest()[:12]}.json"


def infer_member_names(rows: list[dict]) -> dict[str, str]:
    names: dict[str, str] = {}
    for row in rows:
        user_id = row.get("user_id", "")
        name = row.get("anonym_name", "").strip()
        content = parse_json(row.get("content", ""), {})
        is_ai = name == "AI" or (
            row.get("type") == "chat"
            and isinstance(content, dict)
            and content.get("ai_role") == "assistant"
        )
        if user_id and name and not is_ai:
            names[user_id] = name
    return names


def new_group(dataset_id: str, dataset_name: str, group_id: str) -> dict:
    return {
        "datasetId": dataset_id,
        "datasetName": dataset_name,
        "groupId": group_id,
        "members": {},
        "code": [],
        "notes": [],
        "cursor": [],
        "actions": [],
        "chat": [],
        "status": [],
        "completion": [],
    }


def build_dataset(dataset_id: str, dataset_name: str, source: Path, asset_cache: dict[str, str]) -> dict:
    if not source.exists():
        raise FileNotFoundError(f"Missing dataset: {source}")

    dataset_root = OUTPUT / dataset_id
    groups_dir = dataset_root / "groups"
    analysis_dir = dataset_root / "analysis"
    groups_dir.mkdir(parents=True, exist_ok=True)
    analysis_dir.mkdir(parents=True, exist_ok=True)

    with source.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))

    rows_by_group: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        rows_by_group[row["group_id"]].append(row)

    totals = Counter()
    group_index: list[dict] = []
    analysis_index: list[dict] = []

    for group_id, group_rows in sorted(rows_by_group.items()):
        member_names = infer_member_names(group_rows)
        group = new_group(dataset_id, dataset_name, group_id)

        def human_actor(row: dict) -> str:
            user_id = row.get("user_id", "")
            return row.get("anonym_name", "").strip() or member_names.get(user_id) or actor_fallback(user_id)

        def register(actor: str, user_id: str = "") -> None:
            if actor and actor != "AI" and actor not in group["members"]:
                group["members"][actor] = {
                    "id": actor,
                    "name": actor,
                    "username": user_id,
                    "userId": user_id,
                }

        for row in group_rows:
            event_type = row["type"]
            content = parse_json(row.get("content", ""), {})
            if not isinstance(content, dict):
                content = {}
            timestamp = parse_time(row.get("timestamp", ""))
            actor = human_actor(row)

            if event_type == "code":
                register(actor, row.get("user_id", ""))
                changes = []
                source_changes = content.get("changes", [])
                for change in source_changes if isinstance(source_changes, list) else []:
                    if isinstance(change, dict):
                        changes.append({
                            "line": safe_int(change.get("line")),
                            "old": str(change.get("oldContent", "")),
                            "new": str(change.get("newContent", "")),
                        })
                group["code"].append({
                    "t": timestamp,
                    "actor": actor,
                    "code": str(content.get("code", "")),
                    "bulk": bool(content.get("is_paste")),
                    "changes": changes,
                })
            elif event_type == "note":
                register(actor, row.get("user_id", ""))
                note_text, images = clean_note(str(content.get("note", "")), ASSETS, asset_cache)
                group["notes"].append({
                    "t": timestamp,
                    "actor": actor,
                    "text": note_text,
                    "images": images,
                    "bulk": bool(content.get("is_paste")),
                })
            elif event_type == "cursor":
                register(actor, row.get("user_id", ""))
                position = content.get("end_position") or content.get("start_position") or {}
                selection = content.get("end_selection") or content.get("start_selection") or {}
                position = position if isinstance(position, dict) else {}
                selection = selection if isinstance(selection, dict) else {}
                group["cursor"].append({
                    "t": timestamp,
                    "actor": actor,
                    "line": safe_int(position.get("line")),
                    "column": safe_int(position.get("column")),
                    "selection": selection,
                    "hasMovement": bool(content.get("has_movement")),
                    "windowDuration": content.get("window_duration"),
                })
            elif event_type == "action":
                register(actor, row.get("user_id", ""))
                group["actions"].append({
                    "t": timestamp,
                    "actor": actor,
                    "type": str(content.get("action_type", "action")),
                    "label": str(content.get("target", "页面操作")),
                    "category": str(content.get("category", "")),
                })
            elif event_type == "user_status":
                register(actor, row.get("user_id", ""))
                group["status"].append({
                    "t": timestamp,
                    "actor": actor,
                    "status": str(content.get("status", "unknown")),
                    "session": content.get("session_number"),
                })
            elif event_type == "task_completion":
                register(actor, row.get("user_id", ""))
                group["completion"].append({
                    "t": timestamp,
                    "actor": actor,
                    "finalCodeLength": len(str(content.get("final_code", ""))),
                    "finalNoteLength": len(str(content.get("final_note", ""))),
                })
            elif event_type == "private_ai":
                owner = member_names.get(row.get("user_id", "")) or actor
                register(owner, row.get("user_id", ""))
                role = str(content.get("role", "user"))
                group["chat"].append({
                    "id": row.get("_id", ""),
                    "t": timestamp,
                    "actor": "AI" if role == "assistant" else owner,
                    "owner": owner,
                    "kind": "ai-reply" if role == "assistant" else "ai-question",
                    "channel": "private",
                    "message": str(content.get("message", "")),
                    "replyTo": "",
                    "hasCode": False,
                    "code": "",
                    "codeType": "",
                    "hasImage": bool(content.get("has_image")),
                    "imageDescription": str(content.get("image_description") or ""),
                })
            elif event_type == "chat":
                mode = str(content.get("ai_mode") or "")
                role = str(content.get("ai_role") or "")
                source_type = str(content.get("source_type") or "")
                if mode == "shared":
                    kind = "ai-reply" if role == "assistant" else "ai-question"
                    channel = "shared"
                    chat_actor = "AI" if role == "assistant" else actor
                elif mode == "private_forward" or source_type == "private-ai-forward":
                    kind = "private-forward"
                    channel = "forwarded"
                    chat_actor = actor
                else:
                    message = str(content.get("message", ""))
                    kind = "system" if message.endswith(" Joined the room") or message.endswith(" Left the room") else "chat"
                    channel = "room"
                    chat_actor = actor
                if chat_actor != "AI":
                    register(chat_actor, row.get("user_id", ""))
                group["chat"].append({
                    "id": row.get("_id", ""),
                    "t": timestamp,
                    "actor": chat_actor,
                    "owner": "",
                    "kind": kind,
                    "channel": channel,
                    "message": str(content.get("message", "")),
                    "replyTo": content.get("reply_to") or "",
                    "hasCode": bool(content.get("has_code")),
                    "code": str(content.get("code_content") or ""),
                    "codeType": str(content.get("code_type") or ""),
                    "hasImage": bool(content.get("has_image")),
                    "imageDescription": str(content.get("image_description") or ""),
                })

        for field in ("code", "notes", "cursor", "actions", "chat", "status", "completion"):
            group[field].sort(key=lambda item: item["t"])
        event_times = [
            item["t"]
            for field in ("code", "notes", "cursor", "actions", "chat", "status", "completion")
            for item in group[field]
            if item["t"]
        ]
        substantive = sum(len(group[field]) for field in ("code", "notes", "cursor", "actions", "chat"))
        if not event_times or not substantive:
            continue

        add_content_owners(group["code"], "code", group["chat"], min_ai_length=12)
        add_content_owners(group["notes"], "text", group["chat"], min_ai_length=18)
        add_image_owners(group["notes"])

        members = sorted(group["members"].values(), key=lambda item: item["id"])
        for index, member in enumerate(members):
            member["color"] = MEMBER_COLORS[index % len(MEMBER_COLORS)]
        group["members"] = members

        counts = {field: len(group[field]) for field in ("code", "notes", "cursor", "actions", "chat", "status", "completion")}
        counts.update({
            "aiQuestions": sum(item["kind"] == "ai-question" for item in group["chat"]),
            "aiReplies": sum(item["kind"] == "ai-reply" for item in group["chat"]),
            "sharedAI": sum(item.get("channel") == "shared" for item in group["chat"]),
            "privateAI": sum(item.get("channel") == "private" for item in group["chat"]),
            "privateForward": sum(item.get("channel") == "forwarded" for item in group["chat"]),
            "roomChat": sum(item.get("channel") == "room" for item in group["chat"]),
            "noteImages": sum(len(item["images"]) for item in group["notes"]),
        })
        for key, value in counts.items():
            totals[key] += value

        channels = [
            channel
            for channel in ("room", "shared", "private", "forwarded")
            if any(item.get("channel") == channel for item in group["chat"])
        ]
        payload = {
            "schemaVersion": 4,
            "datasetId": dataset_id,
            "datasetName": dataset_name,
            "groupId": group_id,
            "timelineStart": min(event_times),
            "timelineEnd": max(event_times),
            "members": members,
            "channels": channels,
            "counts": counts,
            "limitations": {
                "terminal": "未采集终端命令、stdout/stderr或报错。",
                "tests": "未采集测试用例及通过/失败结果；打开结果页不代表测试成功。",
                "mouse": "cursor事件记录编辑器文本光标和选区，不是鼠标屏幕坐标。",
                "visibility": "online/offline是连接状态，不能等同于离开或切回页面。",
                "chatRead": "未采集消息已读或AI回复查看记录。",
                "dataset": "该数据集独立回放；未确认四份数据属于同一实验，不进行条件效应推断。",
                "ownership": "行级归属由相邻完整快照差分恢复；AI粉色只表示先前AI回复中的足够长逐字匹配文本。",
            },
            "posthoc": {
                "windows": 0,
                "icap": {},
                "warning": "新数据只有原始事件和派生行为统计，没有ICAP或协作异常自动分析。",
            },
            **{field: group[field] for field in ("code", "notes", "cursor", "actions", "chat", "status", "completion")},
        }

        filename = group_filename(group_id)
        (groups_dir / filename).write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

        participation = []
        for person in members:
            actor = person["id"]
            member_counts = {
                "code": sum(item["actor"] == actor for item in group["code"]),
                "notes": sum(item["actor"] == actor for item in group["notes"]),
                "cursor": sum(item["actor"] == actor for item in group["cursor"]),
                "actions": sum(item["actor"] == actor for item in group["actions"]),
                "chat": sum((item["actor"] == actor or item.get("owner") == actor) and item["kind"] != "system" for item in group["chat"]),
            }
            participation.append({
                "id": actor,
                "color": person["color"],
                "counts": member_counts,
                "total": sum(member_counts.values()),
                "finalCodeLines": Counter(group["code"][-1].get("owners", [])).get(actor, 0) if group["code"] else 0,
                "finalNoteLines": Counter(group["notes"][-1].get("owners", [])).get(actor, 0) if group["notes"] else 0,
            })

        pending: dict[tuple[str, str], deque] = defaultdict(deque)
        ai_interactions = []
        for message in group["chat"]:
            if message["kind"] == "ai-question":
                owner = message.get("owner") or message["actor"]
                key = (message.get("channel", "shared"), owner)
                interaction = {
                    "questionT": message["t"],
                    "replyT": None,
                    "user": owner,
                    "question": message["message"],
                    "questionType": "未自动分析",
                    "bloom": "未自动分析",
                    "aiRole": "私有AI" if key[0] == "private" else "共享AI",
                    "directAnswer": None,
                    "triggerFactors": [],
                    "learningNeeds": "",
                    "groupImpact": "",
                    "learningOutcome": "",
                    "knowledgeBuilding": "",
                    "confidence": None,
                    "otherMemberReactions": 0,
                    "benefitedMembers": 0,
                    "eventSummary": "原始问答事件，尚未进行内容自动分析。",
                }
                ai_interactions.append(interaction)
                pending[key].append(interaction)
            elif message["kind"] == "ai-reply":
                owner = message.get("owner") or ""
                key = (message.get("channel", "shared"), owner)
                if pending[key]:
                    pending[key].popleft()["replyT"] = message["t"]
                elif key[0] == "shared":
                    shared_pending = next((queue for (channel, _), queue in pending.items() if channel == "shared" and queue), None)
                    if shared_pending:
                        shared_pending.popleft()["replyT"] = message["t"]

        analysis_payload = {
            "schemaVersion": 2,
            "datasetId": dataset_id,
            "datasetName": dataset_name,
            "groupId": group_id,
            "timelineStart": min(event_times),
            "timelineEnd": max(event_times),
            "members": members,
            "counts": counts,
            "participation": participation,
            "artifactAttribution": {
                "finalCode": dict(Counter(group["code"][-1].get("owners", []))) if group["code"] else {},
                "finalNote": dict(Counter(group["notes"][-1].get("owners", []))) if group["notes"] else {},
            },
            "completion": group["completion"],
            "icapWindows": [],
            "aiInteractions": ai_interactions,
            "noteWindows": [],
            "fullNoteAnalysis": None,
            "codeWindows": [],
            "anomalyCounts": {},
            "limitations": [
                "这里只汇总原始行为和问答配对，没有生成ICAP、异常、代码里程碑或笔记内容分析。",
                "行为记录数不等于认知投入，AI消息出现不表示成员已经阅读或理解。",
                "四份数据的实验关系未确认，不能把数据集差异解释为实验条件效应。",
            ],
        }
        analysis_file = f"analysis-{filename}"
        (analysis_dir / analysis_file).write_text(json.dumps(analysis_payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

        analysis_index.append({
            "id": group_id,
            "name": group_id,
            "file": f"data/datasets/{dataset_id}/analysis/{analysis_file}",
            "members": len(members),
            "events": sum(item["total"] for item in participation),
            "ai": len(ai_interactions),
            "noteInsights": 0,
            "anomalies": 0,
            "icap": {},
            "completed": bool(group["completion"]),
        })
        score = counts["code"] * 3 + counts["notes"] * 2 + counts["chat"] * 4 + counts["actions"]
        group_index.append({
            "id": group_id,
            "name": group_id,
            "file": f"data/datasets/{dataset_id}/groups/{filename}",
            "members": members,
            "counts": counts,
            "start": min(event_times),
            "end": max(event_times),
            "score": score,
            "channels": channels,
        })

    default_group = max(group_index, key=lambda item: item["score"], default={"id": ""})["id"]
    index = {
        "schemaVersion": 4,
        "datasetId": dataset_id,
        "datasetName": dataset_name,
        "generatedAt": datetime.now(LOCAL_TZ).isoformat(),
        "source": str(source),
        "defaultGroup": default_group,
        "totals": dict(totals),
        "assetCount": len(asset_cache),
        "groups": group_index,
    }
    (dataset_root / "index.json").write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")
    (analysis_dir / "index.json").write_text(
        json.dumps({
            "schemaVersion": 2,
            "datasetId": dataset_id,
            "datasetName": dataset_name,
            "defaultGroup": default_group,
            "groups": analysis_index,
        }, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return {
        "id": dataset_id,
        "name": dataset_name,
        "description": f"{len(group_index)} 个可回放小组；按原始日志独立展示，不预设实验关系。",
        "index": f"data/datasets/{dataset_id}/index.json",
        "analysisIndex": f"data/datasets/{dataset_id}/analysis/index.json",
        "groups": len(group_index),
        "totals": dict(totals),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source-dir",
        type=Path,
        default=DEFAULT_SOURCE_DIR,
        help="directory containing collaborative_cond_a/b/c/d_events.csv",
    )
    args = parser.parse_args()
    csv.field_size_limit(2_147_483_647)
    OUTPUT.mkdir(parents=True, exist_ok=True)
    ASSETS.mkdir(parents=True, exist_ok=True)
    asset_cache: dict[str, str] = {}
    catalog = {
        "schemaVersion": 1,
        "generatedAt": datetime.now(LOCAL_TZ).isoformat(),
        "defaultDataset": "cond-a",
        "datasets": [
            {
                "id": "legacy",
                "name": "旧数据集",
                "description": "prodai_local_20260924，保留原有回放与完整事后自动分析。",
                "index": "data/index.json",
                "analysisIndex": "data/analysis/index.json",
                "groups": 11,
                "hidden": False,
            }
        ],
    }
    for dataset_id, dataset_name, filename in DATASETS:
        source = args.source_dir / filename
        summary = build_dataset(dataset_id, dataset_name, source, asset_cache)
        catalog["datasets"].append(summary)
        print(f"Built {dataset_name}: {summary['groups']} groups")
    (OUTPUT / "index.json").write_text(json.dumps(catalog, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote dataset catalog with {len(catalog['datasets'])} datasets.")


if __name__ == "__main__":
    main()
