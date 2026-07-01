#!/usr/bin/env python3
"""Build a public Shadowrocket config from a public-safe personal rule overlay."""

from __future__ import annotations

import argparse
import datetime as dt
import os
import ipaddress
import re
import sys
import urllib.request
from collections import OrderedDict
from pathlib import Path


UPSTREAM_URL = (
    "https://raw.githubusercontent.com/Johnshall/"
    "Shadowrocket-ADBlock-Rules-Forever/release/sr_top500_whitelist_ad.conf"
)
SAFE_DNS_SERVER_LINE = (
    "dns-server = https://1.1.1.1/dns-query, https://8.8.8.8/dns-query"
)
SAFE_FALLBACK_DNS_SERVER_LINE = (
    "fallback-dns-server = https://1.0.0.1/dns-query, https://8.8.4.4/dns-query"
)
SAFE_PROXY_DNS_SERVER_LINE = (
    "proxy-dns-server = https://1.1.1.1/dns-query, https://8.8.8.8/dns-query"
)
SAFE_GENERAL_LINES = [
    "ipv6 = false",
    "bypass-system = true",
    SAFE_DNS_SERVER_LINE,
    SAFE_FALLBACK_DNS_SERVER_LINE,
    SAFE_PROXY_DNS_SERVER_LINE,
    "prefer-ipv6 = false",
    "dns-fallback-system = false",
    "dns-direct-system = false",
    "private-ip-answer = true",
    "dns-direct-fallback-proxy = true",
]
SAFE_GENERAL_KEYS = {
    line.split("=", 1)[0].strip().lower()
    for line in SAFE_GENERAL_LINES
}

PROXY_POLICIES = {"AI", "YouTube", "TikTok", "Javday", "Proxy", "PROXY"}
DIRECT_POLICIES = {"DIRECT", "Direct", "Domestic"}
REJECT_POLICIES = {"REJECT", "Reject"}
PUBLIC_PROXY_POLICY = "PROXY"
TIKTOK_PROXY_DOMAINS = {
    ("DOMAIN-SUFFIX", "ibytedtos.com"),
    ("DOMAIN-SUFFIX", "isnssdk.com"),
}
PRIVACY_TEST_PROXY_RULES = [
    f"DOMAIN-SUFFIX,browserleaks.com,{PUBLIC_PROXY_POLICY}",
    f"DOMAIN-SUFFIX,dnsleaktest.com,{PUBLIC_PROXY_POLICY}",
    f"DOMAIN-SUFFIX,ipleak.net,{PUBLIC_PROXY_POLICY}",
    f"DOMAIN-SUFFIX,whoer.net,{PUBLIC_PROXY_POLICY}",
]
RULESET_FALLBACK_RULES = {
    "Netflix": [
        f"DOMAIN-SUFFIX,netflix.com,{PUBLIC_PROXY_POLICY}",
        f"DOMAIN-SUFFIX,netflix.net,{PUBLIC_PROXY_POLICY}",
        f"DOMAIN-SUFFIX,nflxvideo.net,{PUBLIC_PROXY_POLICY}",
        f"DOMAIN-SUFFIX,nflximg.net,{PUBLIC_PROXY_POLICY}",
        f"DOMAIN-SUFFIX,nflxso.net,{PUBLIC_PROXY_POLICY}",
        f"DOMAIN-SUFFIX,nflxext.com,{PUBLIC_PROXY_POLICY}",
    ],
    "Disney Plus": [
        f"DOMAIN-SUFFIX,disneyplus.com,{PUBLIC_PROXY_POLICY}",
        f"DOMAIN-SUFFIX,disney-plus.net,{PUBLIC_PROXY_POLICY}",
        f"DOMAIN-SUFFIX,dssott.com,{PUBLIC_PROXY_POLICY}",
        f"DOMAIN-SUFFIX,bamgrid.com,{PUBLIC_PROXY_POLICY}",
    ],
    "Telegram": [
        f"DOMAIN-SUFFIX,telegram.org,{PUBLIC_PROXY_POLICY}",
        f"DOMAIN-SUFFIX,t.me,{PUBLIC_PROXY_POLICY}",
        f"DOMAIN-SUFFIX,tdesktop.com,{PUBLIC_PROXY_POLICY}",
    ],
    "Discord": [
        f"DOMAIN-SUFFIX,discord.com,{PUBLIC_PROXY_POLICY}",
        f"DOMAIN-SUFFIX,discord.gg,{PUBLIC_PROXY_POLICY}",
        f"DOMAIN-SUFFIX,discordapp.com,{PUBLIC_PROXY_POLICY}",
        f"DOMAIN-SUFFIX,discordapp.net,{PUBLIC_PROXY_POLICY}",
    ],
    "Spotify": [
        f"DOMAIN-SUFFIX,spotify.com,{PUBLIC_PROXY_POLICY}",
        f"DOMAIN-SUFFIX,scdn.co,{PUBLIC_PROXY_POLICY}",
    ],
    "PayPal": [
        f"DOMAIN-SUFFIX,paypal.com,{PUBLIC_PROXY_POLICY}",
        f"DOMAIN-SUFFIX,paypalobjects.com,{PUBLIC_PROXY_POLICY}",
    ],
}
SENSITIVE_PATTERNS = [
    re.compile(r"^\s*(uuid|password|passwd|server|cipher)\s*[:=]", re.I | re.M),
    re.compile(r"\b(ss|ssr|vmess|vless|trojan)://", re.I),
    re.compile(r"\b192\.168\.1\.1\b"),
]
RULE_TYPES = {
    "DOMAIN",
    "DOMAIN-SUFFIX",
    "DOMAIN-KEYWORD",
    "IP-CIDR",
    "IP-CIDR6",
    "GEOIP",
    "RULE-SET",
}
STRIPPED_SECTIONS = {"[url rewrite]", "[mitm]"}


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def extract_rule_lines(text: str) -> list[str]:
    lines = text.splitlines()
    in_rule = False
    saw_section = False
    result: list[str] = []

    for line in lines:
        stripped = line.strip()
        if stripped == "rules:":
            saw_section = True
            in_rule = True
            continue
        if stripped.startswith("[") and stripped.endswith("]"):
            saw_section = True
            in_rule = stripped.lower() == "[rule]"
            continue
        if saw_section and not in_rule:
            continue
        if not saw_section or in_rule:
            result.append(line)

    return result


def collect_rule_provider_urls(text: str) -> dict[str, str]:
    providers: dict[str, str] = {}
    in_providers = False
    current_name: str | None = None

    for line in text.splitlines():
        stripped = line.strip()
        if stripped == "rule-providers:":
            in_providers = True
            current_name = None
            continue
        if stripped == "rules:":
            break
        if not in_providers:
            continue
        provider_match = re.match(r"^\s{2}([^:#]+):\s*$", line)
        if provider_match:
            current_name = provider_match.group(1).strip().strip('"').strip("'")
            continue
        url_match = re.match(r"^\s+url:\s*(.+?)\s*$", line)
        if current_name and url_match:
            url = url_match.group(1).strip().strip('"').strip("'")
            if url.startswith(("http://", "https://")):
                providers[current_name] = url

    return providers


def normalize_policy(policy: str) -> str | None:
    clean = policy.strip()
    if clean in DIRECT_POLICIES:
        return "DIRECT"
    if clean in REJECT_POLICIES:
        return "REJECT"
    if clean in PROXY_POLICIES:
        return PUBLIC_PROXY_POLICY
    if clean and clean.lower() != "no-resolve":
        return PUBLIC_PROXY_POLICY
    return None


def load_drop_ips(extra_values: list[str] | None = None) -> set[str]:
    values: set[str] = set()
    for raw in (os.environ.get("PRIVATE_DROP_IPS") or "").split(","):
        if raw.strip():
            values.add(raw.strip())
    private_file = Path(".private/drop_ips.txt")
    if private_file.exists():
        for line in private_file.read_text(encoding="utf-8").splitlines():
            clean = line.split("#", 1)[0].strip()
            if clean:
                values.add(clean)
    for raw in extra_values or []:
        if raw.strip():
            values.add(raw.strip())
    return values


def is_dropped_ip_rule(rule_type: str, value: str, drop_ips: set[str]) -> bool:
    if rule_type not in {"IP-CIDR", "IP-CIDR6"}:
        return False
    try:
        network = ipaddress.ip_network(value, strict=False)
    except ValueError:
        return False
    return str(network.network_address) in drop_ips


def parse_rule(
    line: str,
    drop_ips: set[str],
    provider_urls: dict[str, str] | None = None,
) -> tuple[tuple[str, str], str] | None:
    stripped = line.strip().strip('"').strip("'")
    if stripped.startswith("- "):
        stripped = stripped[2:].strip().strip('"').strip("'")
    if not stripped or stripped.startswith("#"):
        return None
    parts = [part.strip() for part in stripped.split(",")]
    if len(parts) < 3:
        return None
    rule_type = parts[0]
    if rule_type == "FINAL":
        return None
    if rule_type not in RULE_TYPES:
        return None
    policy = normalize_policy(parts[2])
    if policy is None:
        return None
    value = parts[1]
    if is_dropped_ip_rule(rule_type, value, drop_ips):
        return None
    if rule_type == "RULE-SET":
        if not value.startswith(("http://", "https://")):
            return None
    if rule_type == "GEOIP":
        return ((rule_type, value.upper()), f"{rule_type},{value.upper()},{policy}")
    if policy == PUBLIC_PROXY_POLICY and rule_type in {"DOMAIN", "DOMAIN-SUFFIX", "DOMAIN-KEYWORD"}:
        return ((rule_type, value.lower()), f"{rule_type},{value},{policy},force-remote-dns")
    return ((rule_type, value.lower()), f"{rule_type},{value},{policy}")


def fallback_rules_for_line(line: str) -> list[str]:
    stripped = line.strip().strip('"').strip("'")
    if stripped.startswith("- "):
        stripped = stripped[2:].strip().strip('"').strip("'")
    parts = [part.strip() for part in stripped.split(",")]
    if len(parts) < 3 or parts[0] != "RULE-SET":
        return []
    policy = normalize_policy(parts[2])
    if policy != PUBLIC_PROXY_POLICY:
        return []
    return RULESET_FALLBACK_RULES.get(parts[1], [])


def sanitize_rules(source_text: str, drop_ips: set[str] | None = None) -> list[str]:
    rules: OrderedDict[tuple[str, str], str] = OrderedDict()
    drop_ips = drop_ips or set()
    provider_urls = collect_rule_provider_urls(source_text)
    for privacy_test_rule in PRIVACY_TEST_PROXY_RULES:
        parsed_privacy_test_rule = parse_rule(privacy_test_rule, drop_ips, provider_urls)
        if parsed_privacy_test_rule is not None:
            key, rule = parsed_privacy_test_rule
            rules[key] = rule
    for line in extract_rule_lines(source_text):
        parsed = parse_rule(line, drop_ips, provider_urls)
        if parsed is None:
            for fallback_line in fallback_rules_for_line(line):
                fallback_parsed = parse_rule(fallback_line, drop_ips, provider_urls)
                if fallback_parsed is None:
                    continue
                fallback_key, fallback_rule = fallback_parsed
                rules.setdefault(fallback_key, fallback_rule)
            continue
        key, rule = parsed
        if key in rules:
            if key in TIKTOK_PROXY_DOMAINS and rule.endswith(f",{PUBLIC_PROXY_POLICY}"):
                rules[key] = rule
            continue
        rules[key] = rule
    return list(rules.values())


def fetch_upstream(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "shadowrocket-personal-rules"})
    with urllib.request.urlopen(req, timeout=60) as response:
        return response.read().decode("utf-8")


def insert_overlay(upstream: str, overlay_rules: list[str]) -> str:
    marker = "[Rule]"
    if marker not in upstream:
        raise ValueError("Upstream config does not contain a [Rule] section")
    header = [
        "# Personal public-safe rules generated from soft-router rules",
        f"# Generated: {dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC",
        *overlay_rules,
        "",
    ]
    return upstream.replace(marker, marker + "\n" + "\n".join(header), 1)


def force_safe_general_settings(config: str) -> str:
    lines = config.splitlines()
    result: list[str] = []
    in_general = False
    saw_general = False
    inserted_safe_settings = False

    def insert_safe_settings_once() -> None:
        nonlocal inserted_safe_settings
        if not inserted_safe_settings:
            result.extend(SAFE_GENERAL_LINES)
            inserted_safe_settings = True

    for line in lines:
        stripped = line.strip()
        is_section = stripped.startswith("[") and stripped.endswith("]")
        if is_section:
            if in_general:
                insert_safe_settings_once()
            in_general = stripped.lower() == "[general]"
            saw_general = saw_general or in_general
            result.append(line)
            continue

        if in_general and "=" in stripped:
            key = stripped.split("=", 1)[0].strip().lower()
            if key in SAFE_GENERAL_KEYS:
                continue

        result.append(line)

    if in_general:
        insert_safe_settings_once()

    if not saw_general:
        raise ValueError("Generated config must contain a [General] section")

    return "\n".join(result) + "\n"


def strip_unused_sections(config: str) -> str:
    """Remove upstream rewrite/MITM sections from the public outbound config."""

    result: list[str] = []
    skip_section = False

    for line in config.splitlines():
        stripped = line.strip()
        is_section = stripped.startswith("[") and stripped.endswith("]")
        if is_section:
            skip_section = stripped.lower() in STRIPPED_SECTIONS
        if not skip_section:
            result.append(line)

    return "\n".join(result) + "\n"


def normalize_generated_rule_line(line: str) -> str:
    stripped = line.strip()
    if not stripped or stripped.startswith(("#", "//")):
        return line

    parts = [part.strip() for part in line.split(",")]
    rule_type = parts[0].strip()

    if rule_type == "FINAL" and len(parts) >= 2:
        policy = normalize_policy(parts[1]) or parts[1]
        parts[1] = policy
        return ",".join(parts)

    if rule_type not in RULE_TYPES or len(parts) < 3:
        return line

    policy = normalize_policy(parts[2])
    if policy is None:
        return line

    parts[2] = policy
    if (
        policy == PUBLIC_PROXY_POLICY
        and rule_type in {"DOMAIN", "DOMAIN-SUFFIX", "DOMAIN-KEYWORD"}
        and "force-remote-dns" not in {part.lower() for part in parts[3:]}
    ):
        parts.append("force-remote-dns")

    return ",".join(parts)


def normalize_generated_rules(config: str) -> str:
    lines = config.splitlines()
    result: list[str] = []
    in_rule = False

    for line in lines:
        stripped = line.strip()
        is_section = stripped.startswith("[") and stripped.endswith("]")
        if is_section:
            in_rule = stripped.lower() == "[rule]"
            result.append(line)
            continue

        if in_rule:
            result.append(normalize_generated_rule_line(line))
        else:
            result.append(line)

    return "\n".join(result) + "\n"


def assert_public_safe(text: str) -> None:
    hits = []
    for pattern in SENSITIVE_PATTERNS:
        if pattern.search(text):
            hits.append(pattern.pattern)
    if hits:
        raise ValueError("Sensitive content detected in generated output: " + "; ".join(hits))


def count_occurrences(text: str, needle: str) -> int:
    return sum(1 for line in text.splitlines() if line.strip() == needle)


def validate_output(text: str) -> None:
    if count_occurrences(text, "[Rule]") != 1:
        raise ValueError("Generated config must contain exactly one [Rule] section")
    final_count = sum(1 for line in text.splitlines() if line.strip().upper().startswith("FINAL,"))
    if final_count != 1:
        raise ValueError(f"Generated config must contain exactly one FINAL rule, found {final_count}")
    dns_lines = [
        line.strip()
        for line in text.splitlines()
        if line.strip().lower().startswith("dns-server")
    ]
    if dns_lines != [SAFE_DNS_SERVER_LINE]:
        raise ValueError("Generated config must use the safe outdoor DoH DNS server line")
    for required_line in SAFE_GENERAL_LINES:
        if count_occurrences(text, required_line) != 1:
            raise ValueError(f"Generated config must contain exactly one {required_line!r}")
    for stripped_section in STRIPPED_SECTIONS:
        if any(line.strip().lower() == stripped_section for line in text.splitlines()):
            raise ValueError(f"Generated config must not contain {stripped_section}")
    mixed_case_policy = re.compile(r",(Proxy|Direct|Reject)(,|$)")
    if mixed_case_policy.search(text):
        raise ValueError("Generated config must normalize policies to uppercase")
    assert_public_safe(text)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--personal", default="personal/rules.conf", help="Public-safe source rules")
    parser.add_argument("--output", default="sr_personal_whitelist_ad.conf", help="Generated Shadowrocket config")
    parser.add_argument("--upstream-url", default=UPSTREAM_URL, help="Johnshall upstream config URL")
    parser.add_argument(
        "--refresh-from",
        help="Optional local full Shadowrocket config to sanitize into --personal before building",
    )
    parser.add_argument(
        "--drop-ip",
        action="append",
        default=[],
        help="Private IP address to omit during --refresh-from. Can be repeated.",
    )
    args = parser.parse_args()

    personal_path = Path(args.personal)
    drop_ips = load_drop_ips(args.drop_ip)
    if args.refresh_from:
        source = read_text(Path(args.refresh_from))
        rules = sanitize_rules(source, drop_ips)
        assert_public_safe("\n".join(rules))
        write_text(personal_path, "\n".join(rules) + "\n")
    else:
        rules = sanitize_rules(read_text(personal_path))

    upstream = fetch_upstream(args.upstream_url)
    generated = normalize_generated_rules(
        strip_unused_sections(force_safe_general_settings(insert_overlay(upstream, rules)))
    )
    generated = generated.rstrip() + "\n"
    validate_output(generated)
    write_text(Path(args.output), generated)

    print(f"personal_rules={len(rules)}")
    print(f"output={args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
