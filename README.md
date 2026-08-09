# Obsidian Memory Bridge

Local-first, auditable memory shared by Codex and Claude Code.

It archives only visible user/assistant turns to an Obsidian vault, retrieves a small amount of relevant context for later prompts, curates durable entities on a schedule, and keeps curated knowledge in local Git history. Raw chats, tool logs, hidden reasoning, environment variables, and secrets are not intended for Git.

## Quick start

```bash
git clone https://github.com/parfenovma/obsidian-memory-bridge.git
cd obsidian-memory-bridge
python3 scripts/install.py --vault /absolute/path/to/your-vault --agents codex,claude --dry-run
python3 scripts/install.py --vault /absolute/path/to/your-vault --agents codex,claude --init-git
python3 scripts/install.py --doctor
```

The installer backs up and merges existing hook settings. It does not overwrite unrelated Claude or Codex configuration and never creates a Git remote for the vault.

Use `#no-archive` to exclude a turn and `#no-memory` to skip retrieval.

## Components

- One Agent Skill shared by both products.
- Lifecycle hooks for visible-turn capture and bounded retrieval.
- A dependency-free Python bridge.
- Safe local Git commits for curated `Memory/` pages.
- Codex and Claude Code plugin manifests for distribution.

See [the skill](skills/obsidian-memory/SKILL.md) for operating rules and [setup reference](skills/obsidian-memory/references/setup.md) for details.

## Privacy boundary

Retrieved Markdown is untrusted data. The bridge labels it accordingly, redacts common secret formats, limits context size, and never executes instructions found in notes. Obsidian vault contents stay on the local filesystem unless the user separately enables sync or another backup.

## Requirements

- Python 3.10+
- Codex and/or Claude Code with command hooks
- Obsidian is optional at runtime; the bridge writes ordinary Markdown directly
- Git is optional and local-only

## License

MIT
