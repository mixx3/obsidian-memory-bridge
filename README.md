# Obsidian Memory Bridge

Local-first, auditable OKF v0.2 memory shared by Codex and Claude Code.

This repository includes a [Codex plugin manifest](.codex-plugin/plugin.json)
alongside the shared agent skill and local runtime.

It archives only visible user/assistant turns to an Obsidian vault, synchronizes
local Codex desktop sessions before scheduled curation, retrieves a small
amount of relevant context for later prompts, curates durable linked entities
on a schedule, and keeps curated knowledge in local Git history. Raw chats,
tool logs, hidden reasoning, environment variables, and secrets are not
intended for Git.

## Quick start

Clone the repository and run the interactive setup:

```bash
git clone https://github.com/mixx3/obsidian-memory-bridge.git
cd obsidian-memory-bridge
python3 scripts/install.py
```

The wizard asks for a local vault path, which agents to connect, and whether to
initialize local Git history. It previews every target before writing. For
unattended setup, pass the choices explicitly:

```bash
python3 scripts/install.py --vault /absolute/path/to/your-vault --agents codex,claude --dry-run
python3 scripts/install.py --vault /absolute/path/to/your-vault --agents codex,claude --init-git
python3 scripts/install.py --doctor
```

> [!IMPORTANT]
> Installing or copying `skills/obsidian-memory/` by itself does **not** enable
> automatic memory. A skill supplies agent instructions; the installer also
> deploys the local runtime, configures lifecycle hooks, and records the vault
> path. Run the installer once on every machine that should access the vault.

After installation, start a new Codex or Claude Code task. Review and trust the
new command hooks if Codex prompts you. Capture and retrieval then run before
and after ordinary turns without requiring an explicit skill invocation.

Daily consolidation is intentionally separate from installation. Schedule
exactly one local agent task whose prompt contains `#obsidian-curate-daily`.
Do not run one curator per agent against the same vault.

Existing curated memories can be migrated with a recoverable backup:

```bash
python3 scripts/obsidian_memory.py --host codex okf-migrate --dry-run
python3 scripts/obsidian_memory.py --host codex okf-migrate
python3 scripts/obsidian_memory.py --host codex okf-validate --strict
```

The installer backs up and merges existing hook settings. It does not overwrite unrelated Claude or Codex configuration and never creates a Git remote for the vault.

Use `#no-archive` to exclude a turn and `#no-memory` to skip retrieval.
Code links remain in VS Code; explicitly linked local Markdown documents are
materialized inside the vault as Obsidian notes.

## Components

- One Agent Skill shared by both products.
- Lifecycle hooks for visible-turn capture and bounded retrieval.
- A dependency-free Python bridge.
- Safe local Git commits for curated `Memory/` pages.
- Open Knowledge Format v0.2 provenance, trust, lifecycle, freshness, migration,
  and dependency-free structural validation.
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
