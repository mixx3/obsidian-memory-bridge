# OKF v0.2 profile

Treat `Memory/` as the distributable Knowledge Bundle. Raw chats and imported
documents are evidence outside that bundle and may be referenced with relative
paths; do not copy them into Git solely for conformance.

## Required profile

- Every concept is UTF-8 Markdown with YAML frontmatter and a non-empty `type`.
- Use `Memory/index.md` with only `okf_version: "0.2"` in its frontmatter.
- Use `Memory/log.md` without frontmatter and group updates under exact
  `## YYYY-MM-DD` headings, newest first.
- Use standard Markdown links. Do not create new `[[wikilinks]]`.
- Use only `draft`, `stable`, or `deprecated` for OKF `status`. Preserve a
  product-specific project state in a separate field such as `project_status`.
- Set `generated.by` to `<producer>/<version>`, `human:<id>`, or `process:<id>`;
  set `generated.at` when content changes meaningfully.
- Add `verified` only after a real human or deterministic process checks the
  concept against its sources. Remove obsolete verification when changing the
  assertions it covered.
- Put document-level provenance in `sources`. Every entry requires `resource`;
  use a stable `id` and a matching Markdown footnote for claim-level attribution.
- Add an absolute `stale_after: YYYY-MM-DD` only when the knowledge is genuinely
  time-sensitive. Absence is better than an invented expiry date.
- Preserve unknown producer fields when round-tripping.

The upstream specification is
<https://github.com/GoogleCloudPlatform/knowledge-catalog/blob/main/okf/SPEC.md>.

## Commands

```bash
python3 scripts/obsidian_memory.py --host codex okf-migrate --dry-run
python3 scripts/obsidian_memory.py --host codex okf-migrate
python3 scripts/obsidian_memory.py --host codex okf-validate --strict
```

Migration creates `.archive/okf-before-<timestamp>/Memory/`. Inspect the Git
working tree before committing. Never include pre-existing user edits merely
because migration touched the same path.
