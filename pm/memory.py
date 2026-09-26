import json
import os
from pathlib import Path

SNAPSHOT_NAME = "last-snapshot.json"
CHANGE_KEYS = ("new", "closed", "gone", "newly_stuck", "status_flips")


def snapshot_path(state_dir: Path) -> Path:
    return Path(state_dir) / SNAPSHOT_NAME


def load(state_dir: Path) -> tuple[dict | None, str | None]:
    path = snapshot_path(state_dir)
    if not path.exists():
        return None, None
    try:
        previous = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as problem:
        return None, f"previous run at {path} is unreadable: {problem}"
    if not isinstance(previous, dict) or not isinstance(previous.get("items"), list):
        return None, f"previous run at {path} is not a pm snapshot"
    return previous, None


def save(state_dir: Path, snapshot: dict) -> Path:
    state_dir = Path(state_dir)
    state_dir.mkdir(parents=True, exist_ok=True)
    state_dir.chmod(0o700)
    path = snapshot_path(state_dir)
    staging = path.with_suffix(".tmp")
    descriptor = os.open(staging, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        json.dump(snapshot, handle, ensure_ascii=False)
    os.replace(staging, path)
    return path


def statuses(snapshot: dict) -> dict[str, str]:
    return {item["id"]: item.get("status") for item in snapshot.get("items", [])}


def stuck_ids(snapshot: dict) -> set[str]:
    return {finding["id"] for finding in snapshot.get("findings", {}).get("stuck", [])}


def diff(previous: dict | None, current: dict) -> dict:
    changes = {"previous_generated_on": None, **{key: [] for key in CHANGE_KEYS}, "titles": {}}
    if previous is None:
        return changes
    before, after = statuses(previous), statuses(current)
    changes["previous_generated_on"] = previous.get("generated_on")
    changes["new"] = sorted(set(after) - set(before))
    changes["closed"] = sorted(key for key in set(after) & set(before) if after[key] == "done" and before[key] != "done")
    changes["gone"] = sorted(key for key in set(before) - set(after) if before[key] != "done")
    changes["newly_stuck"] = sorted(stuck_ids(current) - stuck_ids(previous))
    changes["status_flips"] = [{"id": key, "from": before[key], "to": after[key]} for key in sorted(set(after) & set(before))
                               if before[key] != after[key] and after[key] != "done"]
    titles = {item["id"]: item.get("title", "") for item in previous.get("items", [])}
    changes["titles"] = {key: titles[key] for key in changes["gone"] if key in titles}
    return changes
