# Setup reference

## Install both agents

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
- Adds raw chat directories, state, and archives to `.gitignore`.

Existing JSON settings are backed up before mutation. Hook groups unrelated to Obsidian Memory Bridge are preserved.

## Hook contract

- `UserPromptSubmit`: save the visible prompt and inject bounded relevant context.
- `Stop`: save `last_assistant_message`; if the turn is a curation run, apply its allowlisted payload and commit only those files.
- `SessionEnd`: finalize the Markdown note from captured visible turns.

Codex includes `turn_id`; Claude Code does not. The bridge stores an active turn id per session so both event schemas remain idempotent.

## Opt-out markers

- `#no-archive`: do not write the current turn to the raw chat note.
- `#no-memory`: do not retrieve Obsidian context for this prompt.

## Daily curation

Schedule one local prompt containing `#obsidian-curate-daily`. The bridge supplies new chats from both `Codex Memory/Chats/` and `Claude Memory/Chats/`, applies only paths below `Memory/`, updates the curation watermark, and creates a local commit when files changed.

Do not run two daily curators against the same vault. Capture and retrieval may run concurrently; curation is the single-writer consolidation step.

## Troubleshooting

Run:

```bash
python3 scripts/install.py --doctor
```

Then inspect `/hooks` in Codex or Claude Code. Codex requires changed non-managed hooks to be reviewed and trusted. Claude Code normally reloads changes to `settings.json` automatically; restart it when the top-level skills directory was created after the session started.
