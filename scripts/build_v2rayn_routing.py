#!/usr/bin/env python3
"""Build public-safe v2rayN routing rules from personal Shadowrocket rules."""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import OrderedDict
from pathlib import Path


POLICY_TO_OUTBOUND = {
    "DIRECT": "direct",
    "PROXY": "proxy",
    "REJECT": "block",
}

SENSITIVE_PATTERNS = [
    re.compile(r"\b(ss|ssr|vmess|vless|trojan)://", re.I),
    re.compile(r"\b(uuid|password|passwd|api[_-]?key|token)\b", re.I),
    re.compile(r"\b(server|cipher)\s*[:=]", re.I),
]


def read_rules(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8").splitlines()


def normalize_policy(policy: str) -> str | None:
    clean = policy.strip().upper()
    if clean in POLICY_TO_OUTBOUND:
        return clean
    return None


def add_unique(bucket: OrderedDict[str, None], value: str) -> None:
    if value:
        bucket.setdefault(value, None)


def convert_domain(rule_type: str, value: str) -> str | None:
    if rule_type == "DOMAIN":
        return f"full:{value}"
    if rule_type == "DOMAIN-SUFFIX":
        return f"domain:{value}"
    if rule_type == "DOMAIN-KEYWORD":
        return f"keyword:{value}"
    return None


def build_rules(lines: list[str]) -> list[dict[str, object]]:
    buckets: dict[tuple[str, str], OrderedDict[str, None]] = {
        ("block", "domain"): OrderedDict(),
        ("block", "ip"): OrderedDict(),
        ("direct", "domain"): OrderedDict(),
        ("direct", "ip"): OrderedDict(),
        ("proxy", "domain"): OrderedDict(),
        ("proxy", "ip"): OrderedDict(),
    }

    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith(("#", "//")):
            continue
        parts = [part.strip() for part in stripped.split(",")]
        if len(parts) < 3:
            continue
        rule_type, value = parts[0], parts[1]
        policy = normalize_policy(parts[2])
        if policy is None:
            continue
        outbound = POLICY_TO_OUTBOUND[policy]

        domain_value = convert_domain(rule_type, value)
        if domain_value:
            add_unique(buckets[(outbound, "domain")], domain_value)
            continue
        if rule_type in {"IP-CIDR", "IP-CIDR6"}:
            add_unique(buckets[(outbound, "ip")], value)
            continue
        if rule_type == "GEOIP":
            add_unique(buckets[(outbound, "ip")], f"geoip:{value.lower()}")

    result: list[dict[str, object]] = [
        {
            "remarks": "阻断广告域名",
            "outboundTag": "block",
            "domain": list(buckets[("block", "domain")].keys()),
        },
        {
            "remarks": "阻断广告 IP",
            "outboundTag": "block",
            "ip": list(buckets[("block", "ip")].keys()),
        },
        {
            "remarks": "国内和生活服务直连域名",
            "outboundTag": "direct",
            "domain": list(buckets[("direct", "domain")].keys()),
        },
        {
            "remarks": "国内和生活服务直连 IP",
            "outboundTag": "direct",
            "ip": list(buckets[("direct", "ip")].keys()),
        },
        {
            "remarks": "国外服务代理域名",
            "outboundTag": "proxy",
            "domain": list(buckets[("proxy", "domain")].keys()),
        },
        {
            "remarks": "国外服务代理 IP",
            "outboundTag": "proxy",
            "ip": list(buckets[("proxy", "ip")].keys()),
        },
        {
            "remarks": "兜底代理",
            "outboundTag": "proxy",
            "port": "0-65535",
        },
    ]

    return [
        rule
        for rule in result
        if any(key in rule and rule[key] for key in ("domain", "ip", "port"))
    ]


def assert_public_safe(text: str) -> None:
    hits = [pattern.pattern for pattern in SENSITIVE_PATTERNS if pattern.search(text)]
    if hits:
        raise ValueError("Sensitive content detected in generated v2rayN output: " + "; ".join(hits))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--personal", default="personal/rules.conf", help="Public-safe source rules")
    parser.add_argument(
        "--output",
        default="v2rayn_personal_routing_rules.json",
        help="Generated v2rayN routing rules JSON",
    )
    args = parser.parse_args()

    rules = build_rules(read_rules(Path(args.personal)))
    output = json.dumps(rules, ensure_ascii=False, indent=2) + "\n"
    assert_public_safe(output)
    Path(args.output).write_text(output, encoding="utf-8", newline="\n")

    print(f"v2rayn_rules={len(rules)}")
    print(f"output={args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
