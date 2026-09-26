import json
import re
import subprocess
from pathlib import Path

from pm.model import WorkItem

TENANTS = ("rh", "bc", "personal")
DEFAULT_TENANT = "personal"
OWNER_MAP_PATH = Path(__file__).with_name("tenant-owners.json")
REMOTE_OWNER = re.compile(r"github\.com[:/]([\w.-]+)/")
CONNECTOR_TENANTS = {"tracker": "rh"}


def load_owner_map(path: Path = OWNER_MAP_PATH) -> dict[str, str]:
    table = {owner.lower(): tenant for owner, tenant in json.loads(Path(path).read_text(encoding="utf-8")).items()}
    unknown = sorted(set(table.values()) - set(TENANTS))
    if unknown:
        raise ValueError(f"tenant map names unknown tenants: {unknown}")
    return table


def tenant_of_owner(owner: str | None, owner_map: dict[str, str]) -> str | None:
    if not owner:
        return None
    return owner_map.get(owner.lower(), DEFAULT_TENANT)


def owner_from_remote_url(url: str) -> str | None:
    match = REMOTE_OWNER.search(url or "")
    return match.group(1) if match else None


def git_remote_owner(path: Path) -> str | None:
    try:
        completed = subprocess.run(["git", "-C", str(path), "remote", "get-url", "origin"],
                                   capture_output=True, text=True, timeout=20, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    return owner_from_remote_url(completed.stdout.strip()) if completed.returncode == 0 else None


def local_path(declared: str, home: Path) -> Path | None:
    candidates = [Path(declared.replace("~", str(home), 1)) if declared.startswith("~") else Path(declared)]
    if "/repos/" in declared:
        candidates.append(home / "repos" / declared.split("/repos/", 1)[1])
    return next((candidate for candidate in candidates if candidate.exists()), None)


def attribute(item: WorkItem, owner_map: dict[str, str], remote_owner=git_remote_owner, tasks_path: Path | None = None,
              home: Path = Path.home()) -> str | None:
    if item.source in CONNECTOR_TENANTS:
        return CONNECTOR_TENANTS[item.source]
    if item.source == "github":
        return tenant_of_owner(item.project.split("/", 1)[0] if "/" in item.project else None, owner_map)
    if item.source == "tasks":
        return tenant_of_owner(remote_owner(Path(tasks_path).parent), owner_map) if tasks_path else None
    if item.source == "portal":
        if not item.project.startswith(("/", "~")):
            return None
        path = local_path(item.project, home)
        return tenant_of_owner(remote_owner(path), owner_map) if path else None
    return None
