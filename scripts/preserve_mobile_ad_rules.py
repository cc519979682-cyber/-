#!/usr/bin/env python3
"""One-time copy of the 39 already-published mobile REJECT rules.

The router-sync block stays byte-for-byte intact. A later normal router sync
owns its replacement. No network access, new lists, or guard overrides here.
Default is a dry run; --write explicitly applies the copy to personal/rules.conf.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import re
import stat
import sys
import tempfile
from pathlib import Path

AUTO_BEGIN = "// BEGIN router-sync (auto-generated, do not edit by hand)"
AUTO_END = "// END router-sync"
MOBILE_BEGIN = "// BEGIN mobile-ad-keep (already-published phone rules)"
MOBILE_END = "// END mobile-ad-keep"
DIGEST_PREFIX = "// mobile-ad-source-sha256: "
EXPECTED_COUNT = 39
# Canonical ordered REJECT lines in the existing public source, not a new list.
EXPECTED_DIGEST = "1e5ab509404b488bc5ac209fc128982b3c9330a2b09b663983b8ad520cc334ea"
DOMAIN_TYPES = {"DOMAIN", "DOMAIN-SUFFIX", "DOMAIN-KEYWORD"}


class PreserveError(ValueError):
    """Refuse uncertain provenance, malformed markers, or policy conflicts."""


def marker_span(lines: list[str], begin: str, end: str, label: str, required: bool):
    begin_prefix = begin.split(" (", 1)[0]
    starts = [i for i, line in enumerate(lines) if line.strip().startswith(begin_prefix)]
    ends = [i for i, line in enumerate(lines) if line.strip().startswith(end)]
    if not starts and not ends and not required:
        return None
    if len(starts) != 1 or len(ends) != 1 or starts[0] >= ends[0]:
        raise PreserveError(f"malformed {label} markers")
    a, b = starts[0], ends[0]
    if lines[a].strip() != begin or lines[b].strip() != end:
        raise PreserveError(f"unexpected {label} marker text")
    return a, b


def rule_parts(line: str):
    clean = line.strip()
    if not clean or clean.startswith(("//", "#", ";")):
        return None
    parts = tuple(p.strip() for p in clean.split(","))
    return parts if len(parts) >= 3 else None


def reject_lines(lines: list[str], *, only_rejects: bool = False):
    result = []
    for line in lines:
        parts = rule_parts(line)
        if parts is None:
            if only_rejects and line.strip() and not line.strip().startswith(("//", "#", ";")):
                raise PreserveError("unexpected mobile section content")
            continue
        if parts[2] != "REJECT":
            if only_rejects:
                raise PreserveError("non-REJECT rule in mobile section")
            continue
        if len(parts) != 3 or parts[0] not in DOMAIN_TYPES:
            raise PreserveError("unsupported published REJECT syntax")
        if not re.fullmatch(r"[A-Za-z0-9_.-]{1,253}", parts[1]):
            raise PreserveError("unsafe published domain matcher")
        result.append((line, (parts[0], parts[1].lower(), "REJECT")))
    return result


def canonical_digest(rows) -> str:
    content = "\n".join(",".join(parts) for _, parts in rows) + "\n"
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def validate_published(rows):
    if len(rows) != EXPECTED_COUNT or len({p[:2] for _, p in rows}) != EXPECTED_COUNT:
        raise PreserveError("expected exactly 39 unique published REJECT rules")
    if canonical_digest(rows) != EXPECTED_DIGEST:
        raise PreserveError("published REJECT source fingerprint differs; review required")


def shadows(earlier, later) -> bool:
    """Conservative domain overlap for a rule moved earlier within auto block."""
    t, value = earlier[:2]
    rt, rv = later[:2]
    value, rv = value.lower(), rv.lower()
    if t == "DOMAIN":
        return (rt == "DOMAIN" and value == rv) or (
            rt == "DOMAIN-SUFFIX" and (value == rv or value.endswith("." + rv)))
    if t == "DOMAIN-SUFFIX":
        if rt == "DOMAIN":
            return rv == value or rv.endswith("." + value)
        if rt == "DOMAIN-SUFFIX":
            return rv == value or rv.endswith("." + value) or value.endswith("." + rv)
        return rt == "DOMAIN-KEYWORD" and value == rv
    if t == "DOMAIN-KEYWORD":
        return value in rv
    return False


def validate_conflicts(lines: list[str], auto, mobile, rows):
    wanted = {parts[:2] for _, parts in rows}
    auto_a, auto_b = auto
    for i, line in enumerate(lines):
        if mobile and mobile[0] <= i <= mobile[1]:
            continue
        parts = rule_parts(line)
        if not parts or parts[0] not in DOMAIN_TYPES:
            continue
        normalized = (parts[0], parts[1].lower())
        if normalized in wanted and parts[2] != "REJECT":
            raise PreserveError("existing matcher has a conflicting policy")
    # Copying before auto must not overtake an earlier non-REJECT auto matcher.
    preceding = []
    for line in lines[auto_a + 1:auto_b]:
        parts = rule_parts(line)
        if not parts:
            continue
        if parts[2] == "REJECT":
            if any(shadows(p, parts) for p in preceding):
                raise PreserveError("moving REJECT would overtake an earlier auto policy")
        elif parts[0] in DOMAIN_TYPES:
            preceding.append(parts)


def preserve_text(text: str) -> str:
    lines = text.splitlines(keepends=True)
    auto = marker_span(lines, AUTO_BEGIN, AUTO_END, "router-sync", True)
    mobile = marker_span(lines, MOBILE_BEGIN, MOBILE_END, "mobile-ad-keep", False)
    if mobile and mobile[1] >= auto[0]:
        raise PreserveError("mobile section must be entirely before router-sync")
    source = reject_lines(lines[auto[0] + 1:auto[1]])
    if mobile:
        kept = reject_lines(lines[mobile[0] + 1:mobile[1]], only_rejects=True)
        validate_published(kept)
        digest_comments = [line.strip() for line in lines[mobile[0] + 1:mobile[1]]
                           if line.strip().startswith(DIGEST_PREFIX)]
        if digest_comments != [DIGEST_PREFIX + EXPECTED_DIGEST]:
            raise PreserveError("mobile source fingerprint marker missing or duplicated")
        if source:
            validate_published(source)
            if [p for _, p in source] != [p for _, p in kept]:
                raise PreserveError("auto and mobile REJECT rules conflict")
        validate_conflicts(lines, auto, mobile, kept)
        return text
    validate_published(source)
    validate_conflicts(lines, auto, None, source)
    newline = "\r\n" if lines[auto[0]].endswith("\r\n") else "\n"
    block = [MOBILE_BEGIN + newline,
             "// Mobile-only exception: retain the published policy while home ad blocking is disabled." + newline,
             DIGEST_PREFIX + EXPECTED_DIGEST + newline]
    block.extend(line if line.endswith(("\n", "\r")) else line + newline for line, _ in source)
    block.extend([MOBILE_END + newline, newline])
    # Only insert here: the original auto block and every original byte survive.
    return "".join(lines[:auto[0]] + block + lines[auto[0]:])


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rules", type=Path, default=Path("personal/rules.conf"))
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--write", action="store_true", help="Explicitly write the insertion")
    mode.add_argument("--dry-run", action="store_true", help="Validate only (the default)")
    args = parser.parse_args(argv)
    try:
        path = args.rules
        if path.is_symlink() or not path.is_file():
            raise PreserveError("rules must be a regular non-symlink file")
        before = path.read_bytes()
        after = preserve_text(before.decode("utf-8")).encode("utf-8")
        changed = after != before
        if args.write and changed:
            if path.is_symlink() or path.read_bytes() != before:
                raise PreserveError("rules changed during preparation")
            handle, name = tempfile.mkstemp(prefix=path.name + ".mobile-", dir=path.parent)
            try:
                with os.fdopen(handle, "wb") as stream:
                    stream.write(after)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.chmod(name, stat.S_IMODE(path.stat().st_mode))
                if path.is_symlink() or path.read_bytes() != before:
                    raise PreserveError("rules changed before replacement")
                os.replace(name, path)
            finally:
                if os.path.exists(name):
                    os.unlink(name)
        print(f"result={'written' if args.write and changed else 'validated'} "
              f"changed={int(changed)} preserved={EXPECTED_COUNT} "
              f"source_sha256={EXPECTED_DIGEST}")
        return 0
    except (OSError, UnicodeError, PreserveError) as exc:
        print(f"Refused: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
