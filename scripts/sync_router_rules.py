#!/usr/bin/env python3
"""Convert OpenBox / sing-box route rules into public-safe Shadowrocket rules.

Input is a *bundle* produced on the router (see scripts/nas/sync_router_rules.sh):

* a route-only JSON document: ``{"route": {...}}`` (never the full config.json)
* a directory of rule-set JSON files in sing-box SOURCE format, one per local
  ``route.rule_set`` entry, named ``<basename of path without extension>.json``
  (binary ``.srs`` files are decompiled on the router with
  ``sing-box rule-set decompile``)
* optionally a file of sha256 hashes of outbound server addresses, so rules
  that point at node addresses are dropped without the addresses ever leaving
  the router.

Only the block between the router-sync markers in personal/rules.conf is
rewritten. Everything outside the markers is left untouched.
"""

from __future__ import annotations

import argparse
import difflib
import hashlib
import ipaddress
import json
import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import build_personal_shadowrocket as sr  # noqa: E402
import build_v2rayn_routing as v2  # noqa: E402

DEFAULT_OUTBOUND_MAP = SCRIPT_DIR / "router_outbound_map.json"
DEFAULT_RULES_PATH = Path("personal/rules.conf")
POLICIES = ("DIRECT", "PROXY", "REJECT", "DROP")
DEFAULT_MAX_DELETE_RATIO = 0.10
DEFAULT_GUARD_MIN_RULES = 20
DEFAULT_MAX_LINES = 20000

# Fields that make a rule home-device specific: never published.
DEVICE_SPECIFIC_FIELDS = {
    "inbound",
    "ip_version",
    "auth_user",
    "source_ip_cidr",
    "source_ip_is_private",
    "source_port",
    "source_port_range",
    "process_name",
    "process_path",
    "process_path_regex",
    "package_name",
    "user",
    "user_id",
    "clash_mode",
    "wifi_ssid",
    "wifi_bssid",
    "network_type",
    "network_is_expensive",
    "network_is_constrained",
    "interface_address",
    "network_interface_address",
    "default_interface_address",
    "preferred_by",
    "client",
    "source_mac_address",
    "source_hostname",
}
# AND-ed restrictions Shadowrocket rule lines cannot express: skip whole rule.
UNREPRESENTABLE_FIELDS = {
    "network",
    "protocol",
    "port",
    "port_range",
    "query_type",
    "ip_accept_any",
    "domain_regex_invert",
}
# OR-ed matchers we cannot express: dropped from the rule, the rest is kept
# (publishing a subset of a rule is safe; traffic just falls through).
PARTIAL_FIELDS = {"domain_regex", "geosite", "geoip", "ip_is_private", "rule_set_ip_cidr_accept_empty"}
REPRESENTABLE_FIELDS = {"domain", "domain_suffix", "domain_keyword", "ip_cidr"}
# Route-rule options that are not matchers.
NON_MATCHER_FIELDS = {
    "action",
    "outbound",
    "method",
    "no_drop",
    "override_address",
    "override_port",
    "network_strategy",
    "fallback_network_type",
    "fallback_delay",
    "udp_disable_domain_unmapping",
    "udp_connect",
    "udp_timeout",
    "tls_fragment",
    "tls_fragment_fallback_delay",
    "tls_record_fragment",
    "sniffer",
    "timeout",
    "server",
    "strategy",
    "disable_cache",
    "rewrite_ttl",
    "client_subnet",
}
IGNORED_ACTIONS = {"sniff", "hijack-dns", "resolve", "route-options", "bypass"}
# Never publish single hosts / tiny ranges: they are likely home or own-server addresses.
HOST_IPV4_MIN_PREFIX = 29
HOST_IPV6_MIN_PREFIX = 120
# Internal marker for IP matchers that came from an expanded rule_set.
RULESET_IP = "IP-CIDR@rule_set"

# Defense in depth: the bundle must never contain secrets or outbound details.
FORBIDDEN_KEYS = {
    "outbounds",
    "inbounds",
    "endpoints",
    "experimental",
    "password",
    "passwd",
    "uuid",
    "private_key",
    "pre_shared_key",
    "secret",
    "token",
    "auth_str",
    "users",
    "server_port",
    "reality",
    "public_key",
    "short_id",
    "certificate",
    "key_path",
}
ALLOWED_ROUTE_DOC_KEYS = {"route"}
ALLOWED_RULESET_DOC_KEYS = {"version", "rules"}
UUID_RE = re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.I)
PROXY_URI_RE = re.compile(r"\b(ss|ssr|vmess|vless|trojan|hysteria2?|hy2|tuic|socks5?|wireguard)://", re.I)
SUBSCRIPTION_RE = re.compile(r"(sub(scribe)?\?|token=|/api/v1/client)", re.I)
IPV4_RE = re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}\b")
DOMAIN_VALUE_RE = re.compile(r"^[a-z0-9_*](?:[a-z0-9_*.-]*[a-z0-9_*])?$")
KEYWORD_VALUE_RE = re.compile(r"^[a-z0-9_.-]+$")
NON_GLOBAL_NETWORKS = [
    ipaddress.ip_network(value)
    for value in (
        "0.0.0.0/8",
        "10.0.0.0/8",
        "100.64.0.0/10",
        "127.0.0.0/8",
        "169.254.0.0/16",
        "172.16.0.0/12",
        "192.0.0.0/24",
        "192.0.2.0/24",
        "192.168.0.0/16",
        "198.18.0.0/15",
        "198.51.100.0/24",
        "203.0.113.0/24",
        "224.0.0.0/4",
        "240.0.0.0/4",
        "::/128",
        "::1/128",
        "::ffff:0:0/96",
        "64:ff9b::/96",
        "100::/64",
        "2001:db8::/32",
        "fc00::/7",
        "fe80::/10",
        "ff00::/8",
    )
]


class SyncError(ValueError):
    """Invalid input or unsafe output: nothing is written."""


class GuardError(SyncError):
    """The deletion guard tripped: nothing is written."""


class UnknownTagError(SyncError):
    """--strict and unknown outbound tags were found."""


class MissingRuleSetError(SyncError):
    """A referenced local rule-set has no decompiled JSON in the bundle."""


@dataclass
class Report:
    counts: Counter = field(default_factory=Counter)
    unknown_tags: Counter = field(default_factory=Counter)
    missing_rulesets: set = field(default_factory=set)
    warnings: list = field(default_factory=list)

    def lines(self) -> list[str]:
        out = [f"{key}={self.counts[key]}" for key in sorted(self.counts)]
        for tag in sorted(self.unknown_tags):
            out.append(f"WARNING unknown outbound tag skipped: {mask_tag(tag)!r} ({self.unknown_tags[tag]} rules)")
        for tag in sorted(self.missing_rulesets):
            out.append(f"WARNING rule_set without decompiled JSON: {tag!r}")
        out.extend(f"WARNING {warning}" for warning in self.warnings)
        return out


def mask_tag(tag: str) -> str:
    """Tags of real nodes may embed a server IP; never echo it, even to logs."""

    return IPV4_RE.sub("x.x.x.x", tag)


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.strip().lower().encode("utf-8")).hexdigest()


def as_list(value) -> list:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


# --------------------------------------------------------------------------- input

def assert_input_safe(document, where: str, allowed_top_keys: set[str]) -> None:
    if not isinstance(document, dict):
        raise SyncError(f"{where}: expected a JSON object")
    extra = set(document) - allowed_top_keys
    if extra:
        raise SyncError(f"{where}: unexpected top-level keys {sorted(extra)} (only {sorted(allowed_top_keys)} allowed)")

    def walk(node, path: str) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                if str(key).lower() in FORBIDDEN_KEYS:
                    raise SyncError(f"{where}: forbidden key {key!r} at {path} (secrets must stay on the router)")
                walk(value, f"{path}.{key}")
        elif isinstance(node, list):
            for index, value in enumerate(node):
                walk(value, f"{path}[{index}]")
        elif isinstance(node, str):
            if PROXY_URI_RE.search(node) or UUID_RE.search(node):
                raise SyncError(f"{where}: secret-looking string at {path}")

    walk(document, "$")


def load_route_document(text: str, where: str = "route JSON") -> dict:
    try:
        document = json.loads(text)
    except json.JSONDecodeError as exc:
        raise SyncError(f"{where}: invalid JSON: {exc}") from exc
    assert_input_safe(document, where, ALLOWED_ROUTE_DOC_KEYS)
    route = document.get("route")
    if not isinstance(route, dict):
        raise SyncError(f"{where}: missing route object")
    if not isinstance(route.get("rules"), list) or not route["rules"]:
        raise SyncError(f"{where}: route.rules is empty; refusing to sync (would wipe the block)")
    return route


def load_ruleset_file(path: Path) -> list:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SyncError(f"rule-set {path.name}: cannot read: {exc}") from exc
    assert_input_safe(document, f"rule-set {path.name}", ALLOWED_RULESET_DOC_KEYS)
    rules = document.get("rules")
    if not isinstance(rules, list):
        raise SyncError(f"rule-set {path.name}: missing rules list")
    return rules


def ruleset_file_stem(path: str) -> str:
    name = path.replace("\\", "/").rsplit("/", 1)[-1]
    return name.rsplit(".", 1)[0] if "." in name else name


def build_ruleset_resolver(
    route: dict,
    rulesets_dir: Path | None,
    report: Report,
) -> Callable[[str], list | None]:
    """Return tag -> headless rules (or None when unavailable/remote)."""

    entries: dict[str, dict] = {}
    stems: dict[str, str] = {}
    for entry in as_list(route.get("rule_set")):
        if not isinstance(entry, dict) or not entry.get("tag"):
            continue
        tag = str(entry["tag"])
        entries[tag] = entry
        if entry.get("type", "local") == "local" and entry.get("path"):
            stem = ruleset_file_stem(str(entry["path"]))
            if stem in stems and stems[stem] != tag:
                raise SyncError(f"rule-set tags {stems[stem]!r} and {tag!r} share file name {stem!r}")
            stems[stem] = tag
    cache: dict[str, list | None] = {}

    def resolve(tag: str) -> list | None:
        if tag in cache:
            return cache[tag]
        entry = entries.get(tag)
        result: list | None = None
        if entry is None:
            report.missing_rulesets.add(tag)
        else:
            kind = entry.get("type", "local")
            if kind == "inline":
                result = as_list(entry.get("rules"))
            elif kind == "remote":
                report.counts["skipped_remote_rule_set"] += 1
            elif kind == "local" and entry.get("path") and rulesets_dir is not None:
                candidate = rulesets_dir / f"{ruleset_file_stem(str(entry['path']))}.json"
                if candidate.is_file():
                    result = load_ruleset_file(candidate)
                else:
                    report.missing_rulesets.add(tag)
            else:
                report.missing_rulesets.add(tag)
        cache[tag] = result
        return result

    return resolve


def load_outbound_map(path: Path, override: Path | None = None) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for source in [path, override]:
        if source is None:
            continue
        try:
            document = json.loads(Path(source).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise SyncError(f"outbound map {source}: {exc}") from exc
        layer: dict[str, str] = {}
        for policy in POLICIES:
            for tag in as_list(document.get(policy)):
                tag = str(tag)
                if tag in layer and layer[tag] != policy:
                    raise SyncError(f"outbound map {source}: tag {mask_tag(tag)!r} listed under two policies")
                layer[tag] = policy
        unknown_keys = {key for key in document if key not in POLICIES and not key.startswith("_")}
        if unknown_keys:
            raise SyncError(f"outbound map {source}: unknown keys {sorted(unknown_keys)}")
        mapping.update(layer)
    return mapping


def load_drop_hashes(path: Path | None) -> set[str]:
    if path is None or not Path(path).exists():
        return set()
    values = set()
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        clean = line.split("#", 1)[0].strip().lower()
        if re.fullmatch(r"[0-9a-f]{64}", clean):
            values.add(clean)
    return values


# ---------------------------------------------------------------------- conversion

def normalize_cidr(value: str):
    try:
        return ipaddress.ip_network(str(value).strip(), strict=False)
    except ValueError:
        return None


def is_non_global(network) -> bool:
    return any(network.version == other.version and network.overlaps(other) for other in NON_GLOBAL_NETWORKS)


class Converter:
    def __init__(
        self,
        outbound_map: dict[str, str],
        resolve_ruleset: Callable[[str], list | None],
        report: Report,
        drop_hashes: set[str] | None = None,
        skip_ruleset_ip_direct: bool = True,
    ) -> None:
        self.outbound_map = outbound_map
        self.resolve_ruleset = resolve_ruleset
        self.report = report
        self.drop_hashes = drop_hashes or set()
        # IP DIRECT ranges from rule-sets are (almost) all China ranges, already
        # covered by GEOIP,CN,DIRECT; publishing them would add ~10k lines.
        self.skip_ruleset_ip_direct = skip_ruleset_ip_direct

    # Matchers ------------------------------------------------------------
    def matchers(self, rule: dict, allow_rule_set: bool, depth: int = 0) -> list[tuple[str, str]] | None:
        """Representable (type, value) matchers of a rule, or None to skip it."""

        counts = self.report.counts
        if not isinstance(rule, dict):
            counts["skipped_invalid"] += 1
            return None
        if rule.get("invert"):
            counts["skipped_invert"] += 1
            return None
        if rule.get("type") == "logical":
            return self.logical_matchers(rule, allow_rule_set, depth)
        if rule.get("rule_set_ip_cidr_match_source") or rule.get("rule_set_ipcidr_match_source"):
            counts["skipped_device_specific"] += 1
            return None
        for key in rule:
            if key in NON_MATCHER_FIELDS or key in REPRESENTABLE_FIELDS or key in PARTIAL_FIELDS:
                continue
            if key in {"type", "rule_set", "rule_set_ip_cidr_match_source", "rule_set_ipcidr_match_source", "invert"}:
                continue
            if key in DEVICE_SPECIFIC_FIELDS:
                counts["skipped_device_specific"] += 1
                return None
            if key in UNREPRESENTABLE_FIELDS:
                counts["skipped_unrepresentable"] += 1
                return None
            counts["skipped_unknown_field"] += 1
            self.report.warnings.append(f"rule skipped, unsupported field {key!r}")
            return None

        found: list[tuple[str, str]] = []
        for key in PARTIAL_FIELDS:
            if rule.get(key) not in (None, False, [], ""):
                counts[f"dropped_{key}"] += len(as_list(rule.get(key)))
        for value in as_list(rule.get("domain")):
            found.append(("DOMAIN", str(value)))
        for value in as_list(rule.get("domain_suffix")):
            found.append(("DOMAIN-SUFFIX", str(value)))
        for value in as_list(rule.get("domain_keyword")):
            found.append(("DOMAIN-KEYWORD", str(value)))
        for value in as_list(rule.get("ip_cidr")):
            found.append(("IP-CIDR", str(value)))

        tags = as_list(rule.get("rule_set"))
        if tags and not allow_rule_set:
            counts["skipped_invalid"] += 1
            return None
        for tag in tags:
            headless_rules = self.resolve_ruleset(str(tag))
            if headless_rules is None:
                continue
            counts["expanded_rule_set_refs"] += 1
            for headless in headless_rules:
                sub = self.matchers(headless, allow_rule_set=False, depth=depth + 1)
                if sub:
                    found.extend((RULESET_IP if t == "IP-CIDR" else t, v) for t, v in sub)
        if not found:
            counts["skipped_no_representable_matcher"] += 1
            return None
        return found

    def logical_matchers(self, rule: dict, allow_rule_set: bool, depth: int) -> list[tuple[str, str]] | None:
        counts = self.report.counts
        subrules = as_list(rule.get("rules"))
        mode = str(rule.get("mode", "and")).lower()
        if mode == "and" and len(subrules) == 1:
            mode = "or"
        if mode != "or" or depth > 4:
            counts["skipped_logical"] += 1
            return None
        found: list[tuple[str, str]] = []
        for sub in subrules:
            sub_matchers = self.matchers(sub, allow_rule_set, depth + 1)
            if sub_matchers is None:
                # An OR branch we cannot express: the rest is still a safe subset.
                continue
            found.extend(sub_matchers)
        if not found:
            counts["skipped_logical"] += 1
            return None
        return found

    # Policy --------------------------------------------------------------
    def policy_for(self, rule: dict) -> str | None:
        counts = self.report.counts
        action = rule.get("action")
        if action in IGNORED_ACTIONS:
            counts[f"ignored_action_{action}"] += 1
            return None
        if action == "reject":
            return "REJECT"
        if action not in (None, "route"):
            counts["skipped_unknown_action"] += 1
            self.report.warnings.append(f"rule skipped, unsupported action {action!r}")
            return None
        outbound = rule.get("outbound")
        if not outbound:
            counts["skipped_no_outbound"] += 1
            return None
        policy = self.outbound_map.get(str(outbound))
        if policy is None:
            self.report.unknown_tags[str(outbound)] += 1
            counts["skipped_unknown_outbound"] += 1
            return None
        if policy == "DROP":
            counts["skipped_drop_outbound"] += 1
            return None
        return policy

    # Values --------------------------------------------------------------
    def clean_entry(self, rule_type: str, value: str) -> tuple[str, str] | None:
        counts = self.report.counts
        value = value.strip()
        if rule_type == "IP-CIDR":
            network = normalize_cidr(value)
            if network is None:
                counts["skipped_invalid_value"] += 1
                return None
            if is_non_global(network):
                counts["skipped_private_cidr"] += 1
                return None
            host_prefix = HOST_IPV4_MIN_PREFIX if network.version == 4 else HOST_IPV6_MIN_PREFIX
            if network.prefixlen >= host_prefix:
                counts["skipped_host_ip"] += 1
                return None
            candidates = {sha256_text(value), sha256_text(str(network)), sha256_text(str(network.network_address))}
            if candidates & self.drop_hashes:
                counts["skipped_node_address"] += 1
                return None
            return ("IP-CIDR6" if network.version == 6 else "IP-CIDR", str(network))
        clean = value.lower()
        if rule_type == "DOMAIN-SUFFIX":
            clean = clean.lstrip(".")
        pattern = KEYWORD_VALUE_RE if rule_type == "DOMAIN-KEYWORD" else DOMAIN_VALUE_RE
        if not clean or not pattern.match(clean):
            counts["skipped_invalid_value"] += 1
            return None
        if any(pattern.search(clean) for pattern in v2.SENSITIVE_PATTERNS):
            # e.g. a domain containing "token": the public builders would reject
            # the whole file, so leave this one rule out and report it.
            counts["skipped_sensitive_word"] += 1
            return None
        if sha256_text(clean) in self.drop_hashes:
            counts["skipped_node_address"] += 1
            return None
        if rule_type != "DOMAIN-KEYWORD" and normalize_cidr(clean) is not None:
            counts["skipped_invalid_value"] += 1
            return None
        return (rule_type, clean)

    def convert(self, route: dict) -> list[tuple[str, str, str]]:
        """Return ordered, de-duplicated (type, value, policy) entries.

        Router order is kept (first match wins); a later duplicate of the same
        (type, value) is dropped exactly like sing-box would never reach it.
        route.final is intentionally ignored.
        """

        entries: list[tuple[str, str, str]] = []
        seen: set[tuple[str, str]] = set()
        for rule in as_list(route.get("rules")):
            self.report.counts["route_rules_total"] += 1
            if not isinstance(rule, dict):
                self.report.counts["skipped_invalid"] += 1
                continue
            policy = self.policy_for(rule)
            if policy is None:
                continue
            found = self.matchers(rule, allow_rule_set=True)
            if not found:
                continue
            self.report.counts["route_rules_used"] += 1
            for rule_type, value in found:
                if rule_type == RULESET_IP:
                    if policy == "DIRECT" and self.skip_ruleset_ip_direct:
                        self.report.counts["skipped_ip_direct_ruleset"] += 1
                        continue
                    rule_type = "IP-CIDR"
                cleaned = self.clean_entry(rule_type, value)
                if cleaned is None:
                    continue
                key = rule_key(*cleaned)
                if key in seen:
                    self.report.counts["deduped_within_router"] += 1
                    continue
                seen.add(key)
                entries.append((cleaned[0], cleaned[1], policy))
        return entries


# ------------------------------------------------------------------------- output

def rule_key(rule_type: str, value: str) -> tuple[str, str]:
    rule_type = rule_type.upper()
    if rule_type in {"IP-CIDR", "IP-CIDR6"}:
        network = normalize_cidr(value)
        if network is not None:
            return ("IP-CIDR", str(network))
    return (rule_type, value.strip().lower().lstrip(".") if rule_type == "DOMAIN-SUFFIX" else value.strip().lower())


def line_key(line: str) -> tuple[str, str] | None:
    parsed = sr.parse_rule(line, set())
    if parsed is None:
        return None
    rule_type, value = parsed[0]
    return rule_key(rule_type, value)


def render_entry(rule_type: str, value: str, policy: str) -> str:
    if rule_type in {"IP-CIDR", "IP-CIDR6"}:
        return f"{rule_type},{value},{policy},no-resolve"
    if policy == "PROXY":
        return f"{rule_type},{value},{policy},force-remote-dns"
    return f"{rule_type},{value},{policy}"


def assert_block_public_safe(lines: list[str]) -> None:
    text = "\n".join(lines)
    sr.assert_public_safe(text)
    v2.assert_public_safe(text)
    hits = []
    if UUID_RE.search(text):
        hits.append("uuid")
    if "://" in text:
        hits.append("url")
    if SUBSCRIPTION_RE.search(text):
        hits.append("subscription")
    for line in lines:
        parts = line.split(",")
        if len(parts) < 3 or parts[0] not in sr.RULE_TYPES or parts[2] not in {"DIRECT", "PROXY", "REJECT"}:
            hits.append(f"malformed line {line!r}")
            break
    if hits:
        raise SyncError("Refusing to publish router rules, sensitive/unsafe content: " + ", ".join(hits))


def build_block(entries: list[tuple[str, str, str]], outside_lines: Iterable[str], report: Report) -> list[str]:
    outside_keys = {key for key in (line_key(line) for line in outside_lines) if key is not None}
    lines = []
    for rule_type, value, policy in entries:
        if rule_key(rule_type, value) in outside_keys:
            report.counts["deduped_hand_kept"] += 1
            continue
        lines.append(render_entry(rule_type, value, policy))
    report.counts["block_rules"] = len(lines)
    assert_block_public_safe(lines)
    return lines


def check_deletion_guard(
    old_block: list[str] | None,
    new_block: list[str],
    outside_lines: Iterable[str],
    max_delete_ratio: float,
    guard_min_rules: int,
) -> None:
    if not old_block:
        return
    old_keys = {key for key in (line_key(line) for line in old_block) if key is not None}
    if len(old_keys) < guard_min_rules:
        return
    new_keys = {key for key in (line_key(line) for line in new_block) if key is not None}
    outside_keys = {key for key in (line_key(line) for line in outside_lines) if key is not None}
    removed = old_keys - new_keys - outside_keys
    ratio = len(removed) / len(old_keys)
    if ratio > max_delete_ratio:
        raise GuardError(
            f"Deletion guard: new router block would remove {len(removed)} of {len(old_keys)} "
            f"rules ({ratio:.1%} > {max_delete_ratio:.0%}). Nothing written. If this is intended "
            "(router rules really shrank), rerun once with --allow-large-deletion."
        )


def sync_text(
    rules_text: str,
    route: dict,
    resolve_ruleset: Callable[[str], list | None],
    outbound_map: dict[str, str],
    report: Report,
    drop_hashes: set[str] | None = None,
    strict: bool = False,
    allow_missing_rulesets: bool = False,
    max_delete_ratio: float = DEFAULT_MAX_DELETE_RATIO,
    guard_min_rules: int = DEFAULT_GUARD_MIN_RULES,
    allow_large_deletion: bool = False,
    max_lines: int = DEFAULT_MAX_LINES,
    skip_ruleset_ip_direct: bool = True,
) -> str:
    """Return the new rules.conf text (may equal the input). Raises SyncError."""

    before, old_block, after = sr.split_router_sync_block(rules_text)
    outside = [*before, *after]
    entries = Converter(
        outbound_map, resolve_ruleset, report, drop_hashes, skip_ruleset_ip_direct=skip_ruleset_ip_direct
    ).convert(route)
    if report.missing_rulesets and not allow_missing_rulesets:
        raise MissingRuleSetError(
            "Referenced rule_set(s) missing from bundle: " + ", ".join(sorted(report.missing_rulesets))
        )
    if report.unknown_tags and strict:
        raise UnknownTagError(
            "Unknown outbound tags (--strict): " + ", ".join(sorted(mask_tag(tag) for tag in report.unknown_tags))
        )
    block = build_block(entries, outside, report)
    if len(block) > max_lines:
        report.warnings.append(
            f"router block has {len(block)} lines (> {max_lines}); the generated Shadowrocket config grows accordingly"
        )
    if not allow_large_deletion:
        check_deletion_guard(old_block, block, outside, max_delete_ratio, guard_min_rules)
    if old_block is not None and old_block == block:
        return rules_text
    return sr.replace_router_sync_block(rules_text, block)


def unified_diff(old: str, new: str, path: str) -> str:
    return "".join(
        difflib.unified_diff(
            old.splitlines(keepends=True), new.splitlines(keepends=True), f"a/{path}", f"b/{path}"
        )
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    parser.add_argument("route_json", nargs="?", default="-", help="route-only JSON ({\"route\": ...}) or - for stdin")
    parser.add_argument("--rulesets-dir", type=Path, help="Directory of decompiled rule-set source JSON files")
    parser.add_argument("--rules", type=Path, default=DEFAULT_RULES_PATH, help="personal/rules.conf to update")
    parser.add_argument("--outbound-map", type=Path, default=DEFAULT_OUTBOUND_MAP)
    parser.add_argument("--outbound-map-override", type=Path, help="NAS-local map layered on top")
    parser.add_argument("--drop-hash-file", type=Path, help="sha256 hashes of node addresses (from the router)")
    parser.add_argument("--strict", action="store_true", help="Fail on unknown outbound tags")
    parser.add_argument("--allow-missing-rulesets", action="store_true")
    parser.add_argument("--max-delete-ratio", type=float, default=DEFAULT_MAX_DELETE_RATIO)
    parser.add_argument("--guard-min-rules", type=int, default=DEFAULT_GUARD_MIN_RULES)
    parser.add_argument("--allow-large-deletion", action="store_true")
    parser.add_argument("--max-lines", type=int, default=DEFAULT_MAX_LINES)
    parser.add_argument(
        "--include-ruleset-ip-direct",
        action="store_true",
        help="Also publish IP-CIDR DIRECT rules expanded from rule-sets (default: skipped, GEOIP,CN covers them)",
    )
    parser.add_argument("--dry-run", action="store_true", help="Print the diff, write nothing")
    args = parser.parse_args(argv)

    report = Report()
    try:
        route_text = sys.stdin.read() if args.route_json == "-" else Path(args.route_json).read_text(encoding="utf-8")
        route = load_route_document(route_text)
        resolver = build_ruleset_resolver(route, args.rulesets_dir, report)
        outbound_map = load_outbound_map(args.outbound_map, args.outbound_map_override)
        old_text = args.rules.read_text(encoding="utf-8")
        new_text = sync_text(
            old_text,
            route,
            resolver,
            outbound_map,
            report,
            drop_hashes=load_drop_hashes(args.drop_hash_file),
            strict=args.strict,
            allow_missing_rulesets=args.allow_missing_rulesets,
            max_delete_ratio=args.max_delete_ratio,
            guard_min_rules=args.guard_min_rules,
            allow_large_deletion=args.allow_large_deletion,
            max_lines=args.max_lines,
            skip_ruleset_ip_direct=not args.include_ruleset_ip_direct,
        )
    except GuardError as exc:
        print("\n".join(report.lines()), file=sys.stderr)
        print(f"ERROR {exc}", file=sys.stderr)
        return 2
    except UnknownTagError as exc:
        print("\n".join(report.lines()), file=sys.stderr)
        print(f"ERROR {exc}", file=sys.stderr)
        return 3
    except (SyncError, ValueError, OSError) as exc:
        print("\n".join(report.lines()), file=sys.stderr)
        print(f"ERROR {exc}", file=sys.stderr)
        return 1

    print("\n".join(report.lines()), file=sys.stderr)
    changed = new_text != old_text
    if args.dry_run:
        sys.stdout.write(unified_diff(old_text, new_text, str(args.rules)))
    elif changed:
        sr.write_text(args.rules, new_text)
    print(f"changed={int(changed)}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
