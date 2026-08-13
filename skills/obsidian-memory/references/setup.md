# Setup reference

## Installation boundary

Installing this skill alone provides operating instructions but does not enable
automatic memory. Automatic capture and retrieval additionally require the
bridge runtime, per-agent config with an explicit vault path, and lifecycle
hooks. Run the repository installer once on every machine that should access
the vault.

## Interactive setup

From the repository root, run:

```bash
python3 scripts/install.py
```

The wizard asks for a local vault, connected agents, and local Git history. It
prints a dry-run plan and requires confirmation before writing. It warns before
using a path that looks cloud-synced.

## Unattended setup

From the repository root:

```bash
python3 scripts/install.py --vault /absolute/path/to/Vault --agents codex,claude --dry-run
python3 scripts/install.py --vault /absolute/path/to/Vault --agents codex,claude
python3 scripts/install.py --doctor
```

Add `--init-git` only when the user requests local Git history. The installer never configures a remote.

## What the installer changes

- Copies the dependency-free bridge to `~/.local/share/obsidian-memory-bridge/`.
- Installs the shared skill in `~/.agents/skills/obsidian-memory/` for Codex and `~/.claude/skills/obsidian-memory/` for Claude Code.
- Merges three command hooks into `~/.codex/hooks.json` and/or `~/.claude/settings.json`.
- Writes a per-agent config containing only vault paths and limits.
- Creates missing vault directories and minimal schema files without overwriting existing notes.
- Initializes new `Memory/` directories as OKF v0.2 bundles; existing memories
  require the explicit, backed-up `okf-migrate` command.
- Adds raw chat directories, state, and archives to `.gitignore`.

Existing JSON settings are backed up before mutation. Hook groups unrelated to Obsidian Memory Bridge are preserved.

After installation, start a new task so the skill and hooks are loaded. Codex
may require the user to review and trust the new command hooks. Installing the
bridge does not create a cloud sync connection or expose the vault to another
machine.

## Hook contract

- `UserPromptSubmit`: save the visible prompt and inject bounded relevant context.
- `Stop`: save `last_assistant_message`; if the turn is a curation run, apply its allowlisted payload and commit only those files.
- `SessionEnd`: finalize the Markdown note from captured visible turns.

Codex includes `turn_id`; Claude Code does not. The bridge stores an active turn id per session so both event schemas remain idempotent.

## Opt-out markers

- `#no-archive`: do not write the current turn to the raw chat note.
- `#no-memory`: do not retrieve Obsidian context for this prompt.

## Daily curation

Schedule one local prompt containing `#obsidian-curate-daily`. Before building
the curation bundle, the Codex bridge synchronizes visible local desktop JSONL
sessions from `~/.codex/sessions/` and `~/.codex/archived_sessions/` into
`Codex Memory/Chats/`. It then supplies new chats from both `Codex
Memory/Chats/` and `Claude Memory/Chats/`, applies only paths below `Memory/`,
updates the curation watermark, and creates a local commit when files changed.

During curation, retain durable projects, people, tools, concepts, decisions,
preferences, and workflows as linked Markdown entities under `Memory/`. A raw
chat remains the source note; do not manufacture entities for a one-off
question or unfinished task. The JSONL fallback treats `#no-archive`
conservatively as a session-wide opt-out because the desktop format does not
reliably identify every turn.

Links follow a split rule: code and non-Markdown local files open through
`vscode://file/...`; explicitly linked local `.md` documents are copied to
`Imported/Local Markdown/` and rewritten as ordinary Obsidian links. Run
`python3 scripts/obsidian_memory.py --host codex normalize-links` once after
upgrading to migrate existing chat links.

The curator writes OKF v0.2 concepts, never invents `verified`, records source
provenance, and appends an entry to the hook-managed `Memory/log.md`.

Do not run two daily curators against the same vault. Capture and retrieval may run concurrently; curation is the single-writer consolidation step.

The installer prints this scheduler instruction but does not silently create a
product-specific automation. Configure it in the local agent or operating
system that will remain able to access the vault.

## Troubleshooting

Run:

```bash
python3 scripts/install.py --doctor
python3 scripts/obsidian_memory.py --host codex okf-validate --strict
```

Then inspect `/hooks` in Codex or Claude Code. Codex requires changed non-managed hooks to be reviewed and trusted. Claude Code normally reloads changes to `settings.json` automatically; restart it when the top-level skills directory was created after the session started.
