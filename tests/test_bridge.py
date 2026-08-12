from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BRIDGE_PATH = ROOT / "scripts" / "obsidian_memory.py"
INSTALL_PATH = ROOT / "scripts" / "install.py"

spec = importlib.util.spec_from_file_location("obsidian_memory_bridge", BRIDGE_PATH)
assert spec and spec.loader
bridge = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = bridge
spec.loader.exec_module(bridge)


def write_config(root: Path, agent: str = "claude") -> Path:
    config = root / f"{agent}.json"
    config.write_text(
        json.dumps(
            {
                "vault": str(root / "vault"),
                "agent_id": agent,
                "agent_label": "Claude" if agent == "claude" else "Codex",
                "chat_dir": f"{'Claude' if agent == 'claude' else 'Codex'} Memory/Chats",
                "curation_chat_dirs": ["Codex Memory/Chats", "Claude Memory/Chats"],
                "search_dirs": ["Memory", "Codex Memory", "Claude Memory"],
                "state_dir": str(root / f"{agent}-state"),
                "entity_rules": "Memory/entity-rules.json",
                "project_bindings": "Memory/project-bindings.json",
            }
        ),
        encoding="utf-8",
    )
    return config


def run_hook(config: Path, host: str, event: dict[str, object]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(BRIDGE_PATH), "--config", str(config), "--host", host, "hook"],
        input=json.dumps(event),
        text=True,
        capture_output=True,
        check=True,
    )


class BridgeTests(unittest.TestCase):
    def test_local_markdown_link_is_imported_into_vault(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "study.md"
            source.write_text("# Study\n\nExam outline.\n", encoding="utf-8")
            config = bridge.load_config(write_config(root, "codex"))
            text, changed = bridge.materialize_markdown_links(
                f"[Study notes]({source})", config
            )
            self.assertEqual(changed, 1)
            self.assertIn("[[Imported/Local Markdown/", text)
            imported = list((root / "vault/Imported/Local Markdown").glob("*.md"))
            self.assertEqual(len(imported), 1)
            self.assertIn("Exam outline.", imported[0].read_text(encoding="utf-8"))

    def test_curation_syncs_local_codex_transcript_once(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            sessions = root / "sessions"
            sessions.mkdir()
            transcript = sessions / "study.jsonl"
            transcript.write_text(
                "\n".join(
                    [
                        json.dumps(
                            {
                                "type": "session_meta",
                                "timestamp": "2026-08-12T10:00:00+00:00",
                                "payload": {"id": "study-session", "cwd": "/tmp/study"},
                            }
                        ),
                        json.dumps(
                            {
                                "type": "event_msg",
                                "timestamp": "2026-08-12T10:00:01+00:00",
                                "payload": {"type": "user_message", "message": "Prepare for philosophy exam."},
                            }
                        ),
                        json.dumps(
                            {
                                "type": "event_msg",
                                "timestamp": "2026-08-12T10:00:02+00:00",
                                "payload": {"type": "agent_message", "message": "I will make a study plan."},
                            }
                        ),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            config_path = write_config(root, "codex")
            raw = json.loads(config_path.read_text(encoding="utf-8"))
            raw["codex_transcript_dirs"] = [str(sessions)]
            config_path.write_text(json.dumps(raw), encoding="utf-8")
            config = bridge.load_config(config_path)

            bridge.build_curation_context(config)
            notes = list((root / "vault/Codex Memory/Chats").rglob("*.md"))
            self.assertEqual(len(notes), 1)
            first_mtime = notes[0].stat().st_mtime_ns
            bridge.build_curation_context(config)
            self.assertEqual(notes[0].stat().st_mtime_ns, first_mtime)

    def test_transcript_opt_out_is_not_exported(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            transcript = root / "private.jsonl"
            transcript.write_text(
                "\n".join(
                    [
                        json.dumps({"type": "session_meta", "payload": {"id": "private"}}),
                        json.dumps({"type": "event_msg", "payload": {"type": "user_message", "message": "#no-archive private request"}}),
                        json.dumps({"type": "event_msg", "payload": {"type": "agent_message", "message": "Private answer."}}),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            config = bridge.load_config(write_config(root, "codex"))
            self.assertIsNone(bridge.export_transcript(transcript, config))

    def test_claude_turn_without_turn_id_is_archived(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = write_config(root, "claude")
            (root / "vault/Memory").mkdir(parents=True)
            user = {
                "session_id": "claude-session-1",
                "cwd": "/tmp/project",
                "hook_event_name": "UserPromptSubmit",
                "prompt": "Remember the blue prototype.",
            }
            stop = {
                "session_id": "claude-session-1",
                "cwd": "/tmp/project",
                "hook_event_name": "Stop",
                "last_assistant_message": "The blue prototype is recorded.",
                "stop_hook_active": False,
            }
            run_hook(config, "claude", user)
            run_hook(config, "claude", stop)
            notes = list((root / "vault/Claude Memory/Chats").rglob("*.md"))
            self.assertEqual(len(notes), 1)
            text = notes[0].read_text(encoding="utf-8")
            self.assertIn('source: "claude"', text)
            self.assertIn("claude-chat", text)
            self.assertIn("Remember the blue prototype.", text)
            self.assertIn("The blue prototype is recorded.", text)

    def test_retrieval_returns_bounded_context(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = write_config(root, "codex")
            memory = root / "vault/Memory/Entities/Concepts"
            memory.mkdir(parents=True)
            (memory / "Blue Prototype.md").write_text(
                "# Blue Prototype\n\nThe blue prototype uses a titanium frame.\n",
                encoding="utf-8",
            )
            result = run_hook(
                config,
                "codex",
                {
                    "session_id": "codex-session-1",
                    "turn_id": "turn-1",
                    "cwd": "/tmp/project",
                    "hook_event_name": "UserPromptSubmit",
                    "prompt": "What frame does the blue prototype use?",
                },
            )
            output = json.loads(result.stdout)
            context = output["hookSpecificOutput"]["additionalContext"]
            self.assertIn("titanium frame", context)
            self.assertLessEqual(len(context), 9000)

    def test_installer_preserves_unrelated_claude_settings(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            home = root / "home"
            vault = root / "vault"
            settings = home / ".claude/settings.json"
            settings.parent.mkdir(parents=True)
            settings.write_text(
                json.dumps(
                    {
                        "env": {"EXAMPLE_TOKEN": "do-not-print-or-replace"},
                        "alwaysThinkingEnabled": True,
                    }
                ),
                encoding="utf-8",
            )
            subprocess.run(
                [
                    sys.executable,
                    str(INSTALL_PATH),
                    "--home",
                    str(home),
                    "--vault",
                    str(vault),
                    "--agents",
                    "codex,claude",
                    "--init-git",
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            updated = json.loads(settings.read_text(encoding="utf-8"))
            self.assertEqual(updated["env"]["EXAMPLE_TOKEN"], "do-not-print-or-replace")
            self.assertTrue(updated["alwaysThinkingEnabled"])
            for event in ("UserPromptSubmit", "Stop", "SessionEnd"):
                handlers = [
                    handler
                    for group in updated["hooks"][event]
                    for handler in group["hooks"]
                    if "obsidian_memory.py" in handler.get("command", "")
                ]
                self.assertEqual(len(handlers), 1)
            self.assertTrue((home / ".agents/skills/obsidian-memory/SKILL.md").is_file())
            self.assertTrue((home / ".claude/skills/obsidian-memory/SKILL.md").is_file())
            self.assertTrue((vault / ".git").is_dir())

    def test_curation_commit_leaves_unrelated_change_unstaged(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config_path = write_config(root, "codex")
            vault = root / "vault"
            curated = vault / "Memory/Preferences/Test.md"
            log = vault / "Memory/Curation/Log.md"
            curated.parent.mkdir(parents=True)
            log.parent.mkdir(parents=True)
            curated.write_text("before\n", encoding="utf-8")
            log.write_text("# Log\n", encoding="utf-8")
            readme = vault / "README.md"
            readme.write_text("before\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(vault), "init", "-b", "main"], check=True, capture_output=True)
            subprocess.run(["git", "-C", str(vault), "add", "."], check=True)
            subprocess.run(
                [
                    "git",
                    "-C",
                    str(vault),
                    "-c",
                    "user.name=Test",
                    "-c",
                    "user.email=test@example.invalid",
                    "commit",
                    "-m",
                    "initial",
                ],
                check=True,
                capture_output=True,
            )
            curated.write_text("after\n", encoding="utf-8")
            readme.write_text("manual change\n", encoding="utf-8")
            config = bridge.load_config(config_path)
            bridge.commit_curation_changes(config, [Path("Memory/Preferences/Test.md")])
            names = subprocess.run(
                ["git", "-C", str(vault), "show", "--pretty=format:", "--name-only", "HEAD"],
                check=True,
                capture_output=True,
                text=True,
            ).stdout
            status = subprocess.run(
                ["git", "-C", str(vault), "status", "--short"],
                check=True,
                capture_output=True,
                text=True,
            ).stdout
            self.assertIn("Memory/Preferences/Test.md", names)
            self.assertNotIn("README.md", names)
            self.assertIn("README.md", status)


if __name__ == "__main__":
    unittest.main()
