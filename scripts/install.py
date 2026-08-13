#!/usr/bin/env python3
"""Install or diagnose Obsidian Memory Bridge without third-party packages."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
BRIDGE_SOURCE = ROOT / "scripts" / "obsidian_memory.py"
OKF_SOURCE = ROOT / "scripts" / "okf.py"
SKILL_SOURCE = ROOT / "skills" / "obsidian-memory"
EVENTS = ("UserPromptSubmit", "Stop", "SessionEnd")
AGENT_META = {
    "codex": {
        "label": "Codex",
        "config": Path(".codex/obsidian-memory.json"),
        "settings": Path(".codex/hooks.json"),
        "skill": Path(".agents/skills/obsidian-memory"),
        "state": Path(".codex/obsidian-memory-state"),
        "chat_dir": "Codex Memory/Chats",
    },
    "claude": {
        "label": "Claude",
        "config": Path(".claude/obsidian-memory.json"),
        "settings": Path(".claude/settings.json"),
        "skill": Path(".claude/skills/obsidian-memory"),
        "state": Path(".claude/obsidian-memory-state"),
        "chat_dir": "Claude Memory/Chats",
    },
}


def timestamp() -> str:
    return dt.datetime.now().strftime("%Y%m%d-%H%M%S")


def parse_agents(value: str) -> list[str]:
    agents = list(dict.fromkeys(item.strip().casefold() for item in value.split(",")))
    invalid = [item for item in agents if item not in AGENT_META]
    if invalid or not agents:
        raise argparse.ArgumentTypeError("agents must be codex, claude, or codex,claude")
    return agents


def read_json(path: Path, default: dict[str, Any]) -> dict[str, Any]:
    if not path.is_file():
        return dict(default)
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def backup_file(path: Path, dry_run: bool) -> Path | None:
    if not path.exists():
        return None
    backup = path.with_name(f"{path.name}.obsidian-memory-backup-{timestamp()}")
    if not dry_run:
        if path.is_dir() and not path.is_symlink():
            shutil.copytree(path, backup)
        else:
            shutil.copy2(path, backup, follow_symlinks=False)
    return backup


def atomic_write(path: Path, content: str, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        mode = path.stat().st_mode & 0o777
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    temporary.write_text(content, encoding="utf-8")
    temporary.chmod(mode)
    temporary.replace(path)


def write_json(path: Path, value: dict[str, Any], dry_run: bool) -> Path | None:
    rendered = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    if path.is_file() and path.read_text(encoding="utf-8") == rendered:
        return None
    backup = backup_file(path, dry_run)
    if not dry_run:
        atomic_write(path, rendered)
    return backup


def is_bridge_handler(handler: Any) -> bool:
    if not isinstance(handler, dict):
        return False
    command = str(handler.get("command") or "")
    return "obsidian_memory.py" in command or "obsidian-memory-bridge" in command


def hook_group(agent: str, event: str, installed_bridge: Path) -> dict[str, Any]:
    command = (
        f"python3 {shlex.quote(str(installed_bridge))} --host {agent} hook"
    )
    handler: dict[str, Any] = {
        "type": "command",
        "command": command,
        "timeout": 3 if event == "SessionEnd" else 5,
    }
    if event == "UserPromptSubmit":
        handler["statusMessage"] = "Searching local Obsidian memory"
        if agent == "codex":
            handler["additionalContextLimit"] = 3500
    elif event == "Stop":
        handler["statusMessage"] = "Saving visible chat to Obsidian"
    return {"hooks": [handler]}


def merge_hooks(
    document: dict[str, Any], agent: str, installed_bridge: Path
) -> dict[str, Any]:
    hooks = document.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        raise ValueError("existing hooks field is not an object")
    for event in EVENTS:
        groups = hooks.get(event, [])
        if not isinstance(groups, list):
            raise ValueError(f"existing hooks.{event} field is not an array")
        preserved: list[Any] = []
        for group in groups:
            if not isinstance(group, dict):
                preserved.append(group)
                continue
            handlers = group.get("hooks")
            if not isinstance(handlers, list):
                preserved.append(group)
                continue
            remaining = [handler for handler in handlers if not is_bridge_handler(handler)]
            if remaining:
                copied = dict(group)
                copied["hooks"] = remaining
                preserved.append(copied)
        preserved.append(hook_group(agent, event, installed_bridge))
        hooks[event] = preserved
    return document


def agent_config(home: Path, vault: Path, agent: str) -> dict[str, Any]:
    meta = AGENT_META[agent]
    result = {
        "vault": str(vault),
        "agent_id": agent,
        "agent_label": meta["label"],
        "chat_dir": meta["chat_dir"],
        "curation_chat_dirs": [
            AGENT_META["codex"]["chat_dir"],
            AGENT_META["claude"]["chat_dir"],
        ],
        "search_dirs": ["Memory", "Codex Memory", "Claude Memory", "Imported"],
        "state_dir": str(home / meta["state"]),
        "entity_rules": "Memory/entity-rules.json",
        "project_bindings": "Memory/project-bindings.json",
        "max_results": 5,
        "max_context_chars": 9000,
        "max_file_chars": 300000,
        "redact_secrets": True,
        "git_author_name": "Obsidian Memory Curator",
        "git_author_email": "obsidian-memory@local",
    }
    if agent == "codex":
        result["codex_transcript_dirs"] = [
            str(home / ".codex/sessions"),
            str(home / ".codex/archived_sessions"),
        ]
    return result


def merge_config(existing: dict[str, Any], generated: dict[str, Any]) -> dict[str, Any]:
    result = dict(existing)
    result.update(
        {
            key: value
            for key, value in generated.items()
            if key
            in {
                "vault",
                "agent_id",
                "agent_label",
                "chat_dir",
                "curation_chat_dirs",
                "state_dir",
            }
        }
    )
    for key, value in generated.items():
        result.setdefault(key, value)
    search_dirs = [str(item) for item in result.get("search_dirs", [])]
    for item in generated["search_dirs"]:
        if item not in search_dirs:
            search_dirs.append(item)
    result["search_dirs"] = search_dirs
    return result


def install_runtime(home: Path, dry_run: bool) -> Path:
    target = home / ".local/share/obsidian-memory-bridge/obsidian_memory.py"
    if not dry_run:
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(BRIDGE_SOURCE, target)
        shutil.copy2(OKF_SOURCE, target.parent / "okf.py")
        target.chmod(0o755)
        (target.parent / "okf.py").chmod(0o755)
    return target


def install_skill(home: Path, agent: str, dry_run: bool) -> Path | None:
    target = home / AGENT_META[agent]["skill"]
    backup = backup_file(target, dry_run)
    if dry_run:
        return backup
    if target.is_symlink() or target.is_file():
        target.unlink()
    elif target.is_dir():
        shutil.rmtree(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(SKILL_SOURCE, target)
    return backup


def ensure_vault(vault: Path, dry_run: bool) -> None:
    directories = [
        "Memory/Curation",
        "Memory/Entities/Concepts",
        "Memory/Entities/People",
        "Memory/Entities/Projects",
        "Memory/Entities/Tools",
        "Memory/Decisions",
        "Memory/Preferences",
        "Memory/Workflows",
        "Codex Memory/Chats",
        "Claude Memory/Chats",
        "Imported",
        ".archive",
        ".obsidian",
    ]
    if not dry_run:
        vault.mkdir(parents=True, exist_ok=True)
        for relative in directories:
            (vault / relative).mkdir(parents=True, exist_ok=True)

    initial_files: dict[str, str] = {
        "Memory/index.md": (
            '---\nokf_version: "0.2"\n---\n\n# Memory\n\n'
            "Durable, curated memory shared by local agents.\n"
        ),
        "Memory/Schema.md": (
            "---\ntype: Schema\ntitle: Memory schema\n"
            "description: OKF schema for durable agent memory.\nstatus: stable\n"
            "generated:\n  by: process:obsidian-memory-installer\n"
            f"  at: {dt.datetime.now(dt.timezone.utc).isoformat()}\n---\n\n"
            "# Memory schema\n\nGenerated durable pages live below `Memory/` as OKF v0.2 concepts. "
            "Raw visible chats remain in agent-specific chat directories.\n"
        ),
        "Memory/entity-rules.json": '{\n  "version": 1,\n  "entities": []\n}\n',
        "Memory/project-bindings.json": '{\n  "version": 1,\n  "bindings": []\n}\n',
        "Memory/Curation/README.md": (
            "---\ntype: Workflow\ntitle: Daily memory curation\n"
            "description: Consolidate visible chats into durable OKF concepts.\n"
            "status: stable\ngenerated:\n  by: process:obsidian-memory-installer\n"
            f"  at: {dt.datetime.now(dt.timezone.utc).isoformat()}\n---\n\n"
            "# Curation\n\nState for the single daily curator.\n"
        ),
        "Memory/log.md": "# Knowledge Bundle Update Log\n",
        ".obsidian/graph.json": '{\n  "hideUnresolved": true\n}\n',
    }
    if not dry_run:
        for relative, content in initial_files.items():
            path = vault / relative
            if not path.exists():
                atomic_write(path, content, mode=0o644)

    ignore_path = vault / ".gitignore"
    ignore_lines = [
        ".DS_Store",
        ".trash/",
        ".archive/",
        "Codex Memory/Chats/",
        "Claude Memory/Chats/",
        "Memory/Curation/state.json",
        "*.tmp",
        "__pycache__/",
    ]
    existing = ignore_path.read_text(encoding="utf-8") if ignore_path.is_file() else ""
    missing = [line for line in ignore_lines if line not in existing.splitlines()]
    if missing and not dry_run:
        prefix = "" if not existing or existing.endswith("\n") else "\n"
        block = prefix + "\n# Obsidian Memory Bridge\n" + "\n".join(missing) + "\n"
        atomic_write(ignore_path, existing + block, mode=0o644)


def init_git(vault: Path, dry_run: bool) -> None:
    if (vault / ".git").exists() or dry_run:
        return
    subprocess.run(
        ["git", "-C", str(vault), "init", "-b", "main"],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )


def install(
    home: Path,
    vault: Path,
    agents: list[str],
    dry_run: bool,
    use_git: bool,
) -> int:
    home = home.expanduser().resolve()
    vault = vault.expanduser().resolve()
    print(f"vault: {vault}")
    print(f"agents: {', '.join(agents)}")
    print(f"mode: {'dry-run' if dry_run else 'install'}")
    ensure_vault(vault, dry_run)
    installed_bridge = install_runtime(home, dry_run)
    print(f"bridge: {installed_bridge}")
    for agent in agents:
        meta = AGENT_META[agent]
        config_path = home / meta["config"]
        settings_path = home / meta["settings"]
        existing_config = read_json(config_path, {})
        config = merge_config(existing_config, agent_config(home, vault, agent))
        config_backup = write_json(config_path, config, dry_run)

        settings_default = {"description": "User lifecycle hooks."} if agent == "codex" else {}
        settings = read_json(settings_path, settings_default)
        settings = merge_hooks(settings, agent, installed_bridge)
        settings_backup = write_json(settings_path, settings, dry_run)
        skill_backup = install_skill(home, agent, dry_run)

        print(f"{agent}: config={config_path}")
        print(f"{agent}: hooks={settings_path}")
        print(f"{agent}: skill={home / meta['skill']}")
        for backup in (config_backup, settings_backup, skill_backup):
            if backup:
                print(f"{agent}: backup={backup}")
    if use_git:
        init_git(vault, dry_run)
        print(f"git: {'planned' if dry_run else 'initialized or already present'}")
    return 0


def doctor(home: Path, agents: list[str]) -> int:
    home = home.expanduser().resolve()
    installed_bridge = home / ".local/share/obsidian-memory-bridge/obsidian_memory.py"
    failures = 0
    installed_okf = installed_bridge.parent / "okf.py"
    runtime_ok = installed_bridge.is_file() and installed_okf.is_file()
    print(f"bridge: {'ok' if runtime_ok else 'missing'}")
    failures += not runtime_ok
    vaults: set[Path] = set()
    for agent in agents:
        meta = AGENT_META[agent]
        config_path = home / meta["config"]
        settings_path = home / meta["settings"]
        skill_path = home / meta["skill"] / "SKILL.md"
        config_ok = settings_ok = False
        try:
            config = read_json(config_path, {})
            vault_value = config.get("vault")
            config_ok = bool(vault_value and Path(str(vault_value)).expanduser().is_dir())
            if vault_value:
                vaults.add(Path(str(vault_value)).expanduser().resolve())
        except (OSError, ValueError, json.JSONDecodeError):
            config_ok = False
        try:
            settings = read_json(settings_path, {})
            hooks = settings.get("hooks", {})
            settings_ok = all(
                any(
                    is_bridge_handler(handler)
                    for group in hooks.get(event, [])
                    if isinstance(group, dict)
                    for handler in group.get("hooks", [])
                )
                for event in EVENTS
            )
        except (OSError, ValueError, json.JSONDecodeError):
            settings_ok = False
        checks = {
            "config": config_ok,
            "hooks": settings_ok,
            "skill": skill_path.is_file(),
        }
        failures += sum(not value for value in checks.values())
        print(f"{agent}: " + ", ".join(f"{key}={'ok' if value else 'missing'}" for key, value in checks.items()))
    for vault in sorted(vaults):
        git_state = "git" if (vault / ".git").is_dir() else "no-git"
        print(f"vault: {vault} ({git_state})")
    return 1 if failures else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vault", type=Path)
    parser.add_argument("--home", type=Path, default=Path.home())
    parser.add_argument("--agents", type=parse_agents, default=parse_agents("codex,claude"))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--init-git", action="store_true")
    parser.add_argument("--doctor", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.doctor:
        return doctor(args.home, args.agents)
    if args.vault is None:
        print("--vault is required unless --doctor is used", file=sys.stderr)
        return 2
    return install(args.home, args.vault, args.agents, args.dry_run, args.init_git)


if __name__ == "__main__":
    raise SystemExit(main())
