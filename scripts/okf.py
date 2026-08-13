#!/usr/bin/env python3
"""Dependency-free OKF v0.2 validation and migration helpers.

The bridge deliberately supports the conservative YAML subset it emits.  It
does not pretend to be a general-purpose YAML parser; unknown producer fields
are preserved and structurally tolerated as required by OKF.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import shutil
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable
from urllib.parse import quote


OKF_VERSION = "0.2"
ALLOWED_STATUS = {"draft", "stable", "deprecated"}
TOP_LEVEL_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_-]*):(?:\s*(.*))?$")
H1_RE = re.compile(r"^#\s+(.+?)\s*$", re.M)
WIKILINK_RE = re.compile(r"(!?)\[\[([^\]|#]+)(?:#[^\]|]+)?(?:\|([^\]]+))?\]\]")
SOURCE_HEADING_RE = re.compile(
    r"^(#{2,6})\s+(?:источник|источники|sources?|provenance)\s*$",
    re.I | re.M,
)
DATE_HEADING_RE = re.compile(r"^##\s+(\d{4}-\d{2}-\d{2})\s*$")


@dataclass(frozen=True)
class Issue:
    level: str
    code: str
    path: str
    message: str


@dataclass
class MigrationResult:
    bundle: str
    backup: str | None
    changed: list[str]
    removed: list[str]


def split_frontmatter(text: str) -> tuple[str | None, str]:
    if not text.startswith("---\n"):
        return None, text
    end = text.find("\n---\n", 4)
    if end < 0:
        return None, text
    return text[4:end], text[end + 5 :]


def frontmatter_blocks(raw: str) -> tuple[dict[str, list[str]], list[str]]:
    blocks: dict[str, list[str]] = {}
    errors: list[str] = []
    current: str | None = None
    for number, line in enumerate(raw.splitlines(), start=1):
        match = TOP_LEVEL_RE.match(line) if line and not line[0].isspace() else None
        if match:
            current = match.group(1)
            if current in blocks:
                errors.append(f"duplicate top-level key {current!r} on line {number}")
            blocks.setdefault(current, []).append(line)
        elif current is not None and (not line or line[0].isspace()):
            blocks[current].append(line)
        elif line.strip():
            errors.append(f"unsupported top-level YAML syntax on line {number}")
    return blocks, errors


def scalar_value(block: list[str] | None) -> str | None:
    if not block:
        return None
    match = TOP_LEVEL_RE.match(block[0])
    if not match:
        return None
    value = (match.group(2) or "").strip()
    if not value:
        return None
    if value[0:1] in {'"', "'"}:
        try:
            if value.startswith('"'):
                parsed = json.loads(value)
                return str(parsed)
            if value.endswith("'"):
                return value[1:-1].replace("''", "'")
        except (ValueError, json.JSONDecodeError):
            return value
    return value


def has_nested_key(block: list[str] | None, key: str) -> bool:
    if not block:
        return False
    text = "\n".join(block)
    return bool(
        re.search(rf"(?:\{{|,)\s*{re.escape(key)}\s*:", text)
        or re.search(rf"^\s+(?:-\s*)?{re.escape(key)}\s*:", text, re.M)
    )


def source_entries_have_resource(block: list[str] | None) -> bool:
    if not block:
        return True
    text = "\n".join(block[1:])
    starts = list(re.finditer(r"^\s*-\s+", text, re.M))
    if not starts:
        return False
    for index, start in enumerate(starts):
        end = starts[index + 1].start() if index + 1 < len(starts) else len(text)
        if not re.search(r"(?:^|[,{]\s*|\s)resource\s*:", text[start.start() : end]):
            return False
    return True


def validate_document(path: Path, bundle_root: Path, text: str, strict: bool = False) -> list[Issue]:
    relative = path.relative_to(bundle_root)
    display = str(relative)
    issues: list[Issue] = []
    raw, body = split_frontmatter(text)
    reserved = path.name in {"index.md", "log.md"}

    if path.name == "index.md":
        if path == bundle_root / "index.md":
            if raw is None:
                issues.append(Issue("warning", "missing-version", display, "root index.md should declare okf_version"))
            else:
                blocks, errors = frontmatter_blocks(raw)
                for error in errors:
                    issues.append(Issue("error", "yaml-structure", display, error))
                version = scalar_value(blocks.get("okf_version"))
                if version != OKF_VERSION:
                    issues.append(Issue("error", "version", display, f"okf_version must be {OKF_VERSION}"))
                extra = sorted(set(blocks) - {"okf_version"})
                if extra:
                    issues.append(Issue("error", "reserved-frontmatter", display, f"root index.md may only contain okf_version, found {extra}"))
        elif raw is not None:
            issues.append(Issue("error", "reserved-frontmatter", display, "nested index.md must not have frontmatter"))
        return issues

    if path.name == "log.md":
        if raw is not None:
            issues.append(Issue("error", "reserved-frontmatter", display, "log.md must not have concept frontmatter"))
        for line in body.splitlines():
            if line.startswith("## ") and not DATE_HEADING_RE.match(line):
                issues.append(Issue("error", "log-date", display, f"date heading must be exactly YYYY-MM-DD: {line}"))
        return issues

    if not reserved and raw is None:
        return [Issue("error", "frontmatter", display, "concept document lacks YAML frontmatter")]
    if raw is None:
        return issues

    blocks, errors = frontmatter_blocks(raw)
    for error in errors:
        issues.append(Issue("error", "yaml-structure", display, error))
    concept_type = scalar_value(blocks.get("type"))
    if not concept_type:
        issues.append(Issue("error", "type", display, "concept document requires a non-empty type"))
    status = scalar_value(blocks.get("status"))
    if status and status not in ALLOWED_STATUS:
        issues.append(Issue("error", "status", display, "status must be draft, stable, or deprecated"))
    stale_after = scalar_value(blocks.get("stale_after"))
    if stale_after:
        try:
            dt.date.fromisoformat(stale_after)
        except ValueError:
            issues.append(Issue("error", "stale-after", display, "stale_after must be YYYY-MM-DD"))
    generated = blocks.get("generated")
    if generated:
        if not has_nested_key(generated, "by"):
            issues.append(Issue("error", "generated-by", display, "generated requires by"))
        if not has_nested_key(generated, "at"):
            issues.append(Issue("warning", "generated-at", display, "generated should include at"))
    else:
        issues.append(Issue("error" if strict else "warning", "generated", display, "generated provenance is required by the bridge profile"))
    verified = blocks.get("verified")
    if verified:
        if not has_nested_key(verified, "by"):
            issues.append(Issue("error", "verified-by", display, "every verification requires by"))
        if not has_nested_key(verified, "at"):
            issues.append(Issue("warning", "verified-at", display, "verification should include at"))
    if blocks.get("sources") and not source_entries_have_resource(blocks.get("sources")):
        issues.append(Issue("error", "source-resource", display, "every sources entry requires resource"))
    if WIKILINK_RE.search(body) or (raw and WIKILINK_RE.search(raw)):
        issues.append(Issue("error" if strict else "warning", "wikilink", display, "use standard Markdown links for portable OKF relationships"))
    if not scalar_value(blocks.get("title")):
        issues.append(Issue("warning", "title", display, "title is recommended"))
    if not scalar_value(blocks.get("description")):
        issues.append(Issue("warning", "description", display, "description is recommended"))
    return issues


def validate_bundle(bundle_root: Path, strict: bool = False) -> list[Issue]:
    bundle_root = bundle_root.resolve()
    issues: list[Issue] = []
    if not bundle_root.is_dir():
        return [Issue("error", "bundle", str(bundle_root), "bundle directory does not exist")]
    for path in sorted(bundle_root.rglob("*.md")):
        if any(part.startswith(".") for part in path.relative_to(bundle_root).parts):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            issues.append(Issue("error", "read", str(path.relative_to(bundle_root)), str(exc)))
            continue
        issues.extend(validate_document(path, bundle_root, text, strict=strict))
    return issues


def _yaml_line(key: str, value: str) -> str:
    return f"{key}: {json.dumps(value, ensure_ascii=False)}"


def _description(body: str, title: str) -> str:
    paragraphs = re.split(r"\n\s*\n", body)
    for paragraph in paragraphs:
        plain = re.sub(r"^#{1,6}\s+.*$", "", paragraph, flags=re.M)
        plain = WIKILINK_RE.sub(lambda m: m.group(3) or Path(m.group(2)).name, plain)
        plain = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", plain)
        plain = re.sub(r"[`*_>#]", "", plain)
        plain = re.sub(r"\s+", " ", plain).strip(" -")
        if plain and plain != title and len(plain) >= 24:
            return plain[:220].rsplit(" ", 1)[0] if len(plain) > 220 else plain
    return f"Curated knowledge about {title}."


def _source_section(text: str) -> str:
    chunks: list[str] = []
    for match in SOURCE_HEADING_RE.finditer(text):
        level = len(match.group(1))
        following = text[match.end() :]
        stop = re.search(rf"^#{{1,{level}}}\s+", following, re.M)
        chunks.append(following[: stop.start() if stop else len(following)])
    return "\n".join(chunks)


def _link_target_path(vault: Path, target: str) -> Path:
    clean = target.strip().lstrip("/")
    candidate = vault / clean
    if not clean.casefold().endswith(".md"):
        candidate = Path(str(candidate) + ".md")
    return candidate


def _markdown_target(document: Path, vault: Path, target: str) -> str:
    candidate = _link_target_path(vault, target)
    relative = os.path.relpath(candidate, document.parent).replace(os.sep, "/")
    return quote(relative, safe="/:#@-._~")


def convert_wikilinks(text: str, document: Path, vault: Path) -> tuple[str, int]:
    changed = 0

    def replace(match: re.Match[str]) -> str:
        nonlocal changed
        changed += 1
        label = (match.group(3) or Path(match.group(2)).name).strip()
        target = _markdown_target(document, vault, match.group(2))
        prefix = "!" if match.group(1) else ""
        return f"{prefix}[{label}]({target})"

    return WIKILINK_RE.sub(replace, text), changed


def _source_resource(document: Path, bundle: Path, vault: Path, target: str) -> str:
    candidate = _link_target_path(vault, target)
    try:
        inside = candidate.relative_to(bundle)
        return "/" + quote(str(inside).replace(os.sep, "/"), safe="/#@-._~")
    except ValueError:
        return _markdown_target(document, vault, target)


def _migrate_concept(path: Path, bundle: Path, vault: Path, actor: str, timestamp: str) -> str:
    text = path.read_text(encoding="utf-8", errors="replace")
    raw, body = split_frontmatter(text)
    blocks, _ = frontmatter_blocks(raw or "")
    title_match = H1_RE.search(body)
    title = scalar_value(blocks.get("title")) or (title_match.group(1).strip() if title_match else path.stem)
    description = scalar_value(blocks.get("description")) or _description(body, title)
    old_status = scalar_value(blocks.get("status"))
    modern_body = body
    modern_body = modern_body.replace("[[Memory/Curation/Log|", "[[Memory/log|")
    modern_body = modern_body.replace("[[Memory/Curation/Log]]", "[[Memory/log]]")
    if path == bundle / "Schema.md":
        modern_body = modern_body.replace("`Memory/Curation/Log.md`", "`Memory/log.md`")
        modern_body = modern_body.replace(
            "Wiki-ссылки между чатами и страницами `Memory/` остаются обычными рёбрами графа.",
            "Стандартные Markdown-ссылки между evidence и `Memory/` остаются рёбрами графа и переносятся между OKF-consumers.",
        )
    if path == bundle / "Curation/README.md":
        modern_body = modern_body.replace(
            "[журнале курации](History.md)",
            "[OKF-журнале](../log.md)",
        )
    if (
        "generated" in blocks
        and "updated" not in blocks
        and scalar_value(blocks.get("title"))
        and scalar_value(blocks.get("description"))
        and old_status in ALLOWED_STATUS
        and not WIKILINK_RE.search(text)
        and modern_body == body
    ):
        return text
    status_map = {
        None: "stable",
        "active": "stable",
        "accepted": "stable",
        "imported": "stable",
        "idea": "draft",
    }
    status = status_map.get(old_status, old_status or "stable")
    if status not in ALLOWED_STATUS:
        status = "draft"

    source_links: list[tuple[str, str]] = []
    source_targets: set[str] = set()
    for match in WIKILINK_RE.finditer(_source_section(body)):
        item = (match.group(2).strip(), (match.group(3) or Path(match.group(2)).name).strip())
        if item[0] not in source_targets:
            source_links.append(item)
            source_targets.add(item[0])

    converted_body, _ = convert_wikilinks(modern_body, path, vault)

    skip = {"type", "title", "description", "status", "updated", "generated", "sources"}
    rendered = [
        _yaml_line("type", scalar_value(blocks.get("type")) or "Concept"),
        _yaml_line("title", title),
        _yaml_line("description", description),
        f"status: {status}",
    ]
    if old_status and old_status not in ALLOWED_STATUS:
        rendered.append(_yaml_line("memory_status", old_status))
    for key, block in blocks.items():
        if key in skip or key == "verified":
            continue
        converted, _ = convert_wikilinks("\n".join(block), path, vault)
        rendered.extend(converted.splitlines())
    rendered.extend(
        [
            "generated:",
            f"  by: {actor}",
            f"  at: {timestamp}",
        ]
    )
    if "verified" in blocks:
        rendered.extend(blocks["verified"])
    if "sources" in blocks:
        converted, _ = convert_wikilinks("\n".join(blocks["sources"]), path, vault)
        rendered.extend(converted.splitlines())
    elif source_links:
        rendered.append("sources:")
        for target, label in source_links:
            source_id = "source-" + hashlib.sha256(target.encode("utf-8")).hexdigest()[:10]
            rendered.extend(
                [
                    f"  - id: {source_id}",
                    f"    resource: {json.dumps(_source_resource(path, bundle, vault, target), ensure_ascii=False)}",
                    f"    title: {json.dumps(label, ensure_ascii=False)}",
                ]
            )
    return "---\n" + "\n".join(rendered) + "\n---\n" + converted_body.lstrip("\n")


def _case_rename(source: Path, target: Path, dry_run: bool) -> None:
    if source.name == target.name or not source.exists():
        return
    if dry_run:
        return
    temporary = source.with_name(f".{source.name}.okf-rename-{os.getpid()}")
    source.replace(temporary)
    temporary.replace(target)


def _exists_with_exact_name(path: Path) -> bool:
    try:
        return any(item.name == path.name for item in path.parent.iterdir())
    except OSError:
        return False


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + f".tmp-{os.getpid()}")
    temporary.write_text(content.rstrip() + "\n", encoding="utf-8")
    temporary.replace(path)


def migrate_bundle(vault: Path, bundle_name: str = "Memory", dry_run: bool = False) -> MigrationResult:
    vault = vault.expanduser().resolve()
    bundle = (vault / bundle_name).resolve()
    bundle.relative_to(vault)
    if not bundle.is_dir():
        raise ValueError(f"missing bundle: {bundle}")
    stamp = dt.datetime.now().astimezone()
    timestamp = stamp.isoformat(timespec="seconds")
    actor = "process:obsidian-memory-okf-migration"
    backup = vault / ".archive" / f"okf-before-{stamp.strftime('%Y%m%d-%H%M%S-%f')}" / bundle_name
    if not dry_run:
        backup.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(bundle, backup)

    changed: list[str] = []
    removed: list[str] = []
    legacy_index = bundle / "Index.md"
    root_index = bundle / "index.md"
    index_renamed = _exists_with_exact_name(legacy_index) and legacy_index.name != root_index.name
    if index_renamed:
        _case_rename(legacy_index, root_index, dry_run)
        changed.append(str(root_index.relative_to(vault)))
        removed.append(str(legacy_index.relative_to(vault)))
    legacy_history = bundle / "Curation/Log.md"
    history = bundle / "Curation/History.md"
    history_renamed = legacy_history.exists() and not history.exists()
    if history_renamed:
        if not dry_run:
            legacy_history.replace(history)
        changed.append(str(history.relative_to(vault)))
        removed.append(str(legacy_history.relative_to(vault)))

    paths = list(bundle.rglob("*.md"))
    if dry_run:
        paths = [
            history if history_renamed and path == legacy_history
            else root_index if index_renamed and path == legacy_index
            else path
            for path in paths
        ]
    for path in sorted(set(paths)):
        if path == root_index or path.name == "log.md":
            continue
        source = legacy_history if dry_run and history_renamed and path == history else path
        migrated = _migrate_concept(source, bundle, vault, actor, timestamp)
        old = source.read_text(encoding="utf-8", errors="replace")
        if migrated != old:
            relative = str(path.relative_to(vault))
            if relative not in changed:
                changed.append(relative)
            if not dry_run:
                _atomic_write(path, migrated)

    index_source = legacy_index if dry_run and index_renamed else root_index
    if index_source.exists():
        _, body = split_frontmatter(index_source.read_text(encoding="utf-8", errors="replace"))
        body = body.replace("[[Memory/Curation/Log|", "[[Memory/log|")
        body = body.replace("[[Memory/Curation/Log]]", "[[Memory/log]]")
        converted, _ = convert_wikilinks(body, root_index, vault)
        converted = converted.replace(
            "- [Журнал курации](Curation/History.md)",
            "- [OKF update log](log.md)\n- [История курации до OKF](Curation/History.md)",
        )
        converted = converted.replace(
            "- [Журнал курации](log.md)",
            "- [OKF update log](log.md)\n- [История курации до OKF](Curation/History.md)",
        )
        index_text = f'---\nokf_version: "{OKF_VERSION}"\n---\n' + converted.lstrip("\n")
        old_index = index_source.read_text(encoding="utf-8", errors="replace")
        if index_text.rstrip() + "\n" != old_index.rstrip() + "\n":
            if not dry_run:
                _atomic_write(root_index, index_text)
            if str(root_index.relative_to(vault)) not in changed:
                changed.append(str(root_index.relative_to(vault)))
    else:
        index_text = f'---\nokf_version: "{OKF_VERSION}"\n---\n\n# Knowledge Bundle\n'
        if not dry_run:
            _atomic_write(root_index, index_text)
        changed.append(str(root_index.relative_to(vault)))

    log_path = bundle / "log.md"
    log_text = (
        "# Knowledge Bundle Update Log\n\n"
        f"## {stamp.date().isoformat()}\n\n"
        "* **Migration**: Adopted Open Knowledge Format v0.2 for curated memory.\n"
    )
    if not log_path.exists():
        if not dry_run:
            _atomic_write(log_path, log_text)
        changed.append(str(log_path.relative_to(vault)))
    return MigrationResult(
        bundle=str(bundle),
        backup=None if dry_run else str(backup),
        changed=sorted(set(changed)),
        removed=sorted(set(removed)),
    )


def report_json(issues: Iterable[Issue]) -> str:
    values = list(issues)
    return json.dumps(
        {
            "ok": not any(item.level == "error" for item in values),
            "errors": sum(item.level == "error" for item in values),
            "warnings": sum(item.level == "warning" for item in values),
            "issues": [asdict(item) for item in values],
        },
        ensure_ascii=False,
        indent=2,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    validate = subparsers.add_parser("validate")
    validate.add_argument("bundle", type=Path)
    validate.add_argument("--strict", action="store_true")
    migrate = subparsers.add_parser("migrate")
    migrate.add_argument("vault", type=Path)
    migrate.add_argument("--bundle", default="Memory")
    migrate.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if args.command == "validate":
        issues = validate_bundle(args.bundle, strict=args.strict)
        print(report_json(issues))
        return 1 if any(item.level == "error" for item in issues) else 0
    result = migrate_bundle(args.vault, args.bundle, dry_run=args.dry_run)
    print(json.dumps(asdict(result), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
