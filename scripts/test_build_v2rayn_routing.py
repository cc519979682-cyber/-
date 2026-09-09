#!/usr/bin/env python3
"""Offline regression tests for first-match routing conversion."""

import ipaddress
import itertools
import unittest

from build_v2rayn_routing import build_rules


def match_domain(pattern: str, domain: str) -> bool:
    kind, value = pattern.split(":", 1)
    if kind == "full":
        return domain == value
    if kind == "domain":
        return domain == value or domain.endswith("." + value)
    if kind == "keyword":
        return value in domain
    raise AssertionError(f"Unexpected domain pattern: {pattern}")


def first_outbound(rules, domain="", address=None, in_cn=False):
    """Evaluate the emitted subset; GeoIP membership is supplied by each test."""
    for rule in rules:
        if "domain" in rule and not any(match_domain(p, domain) for p in rule["domain"]):
            continue
        if "ip" in rule:
            matches = any(
                in_cn if p == "geoip:cn" else (
                    address is not None and ipaddress.ip_address(address) in ipaddress.ip_network(p)
                )
                for p in rule["ip"]
            )
            if not matches:
                continue
        return rule["outboundTag"]
    raise AssertionError("Missing final fallback")


class RoutingOrderTests(unittest.TestCase):
    def test_okx_exact_proxy_precedes_direct_suffix_and_keyword(self):
        rules = build_rules([
            "DOMAIN,www.okx.com,PROXY,force-remote-dns",
            "DOMAIN-SUFFIX,okx.com,DIRECT",
            "DOMAIN-KEYWORD,okx,DIRECT",
        ])
        self.assertEqual(first_outbound(rules, "www.okx.com"), "proxy")
        self.assertEqual(first_outbound(rules, "api.okx.com"), "direct")

    def test_futu_proxy_precedes_geoip_cn(self):
        rules = build_rules([
            "DOMAIN-SUFFIX,futunn.com,PROXY,force-remote-dns",
            "DOMAIN-SUFFIX,moomoo.com,PROXY,force-remote-dns",
            "GEOIP,CN,DIRECT",
        ])
        for domain in ("quote.futunn.com", "api.moomoo.com"):
            self.assertEqual(first_outbound(rules, domain, in_cn=True), "proxy")
        self.assertEqual(first_outbound(rules, "other.example", in_cn=True), "direct")
        self.assertEqual(rules[-2]["ip"], ["geoip:cn"])

    def test_ad_exception_priority_is_not_reordered(self):
        allow = "DOMAIN,login.example.com,DIRECT"
        block = "DOMAIN-SUFFIX,example.com,REJECT"
        self.assertEqual(first_outbound(build_rules([allow, block]), "login.example.com"), "direct")
        self.assertEqual(first_outbound(build_rules([block, allow]), "login.example.com"), "block")
        self.assertEqual(first_outbound(build_rules([allow, block]), "ads.example.com"), "block")

    def test_all_policy_orders_keep_first_match(self):
        tags = {"DIRECT": "direct", "PROXY": "proxy", "REJECT": "block"}
        for order in itertools.permutations(tags):
            with self.subTest(order=order):
                rules = build_rules([f"DOMAIN,example.com,{policy}" for policy in order])
                self.assertEqual([r["outboundTag"] for r in rules[:-1]], [tags[p] for p in order])
                self.assertEqual(first_outbound(rules, "example.com"), tags[order[0]])

    def test_same_outbound_domain_and_ip_remain_separate(self):
        rules = build_rules([
            "DOMAIN,first.example,DIRECT",
            "IP-CIDR,203.0.113.0/24,DIRECT",
            "IP-CIDR6,2001:db8::/32,DIRECT",
            "DOMAIN,last.example,DIRECT",
        ])
        self.assertEqual(len(rules), 4)
        self.assertTrue(all(not ("domain" in r and "ip" in r) for r in rules))
        self.assertEqual(first_outbound(rules, "first.example", "198.51.100.1"), "direct")
        self.assertEqual(first_outbound(rules, "other.example", "203.0.113.7"), "direct")
        self.assertEqual(first_outbound(rules, "other.example", "2001:db8::1"), "direct")
        self.assertEqual(first_outbound(rules, "last.example", "198.51.100.1"), "direct")

    def test_only_adjacent_equivalent_segments_merge(self):
        rules = build_rules([
            "DOMAIN,a.example,PROXY",
            "DOMAIN-SUFFIX,b.example,PROXY",
            "DOMAIN,c.example,DIRECT",
            "DOMAIN,a.example,PROXY",
        ])
        self.assertEqual(len(rules), 4)
        self.assertEqual(rules[0]["domain"], ["full:a.example", "domain:b.example"])
        self.assertEqual(rules[1]["domain"], ["full:c.example"])
        self.assertEqual(rules[2]["domain"], ["full:a.example"])

    def test_duplicate_keys_are_not_overwritten_or_globally_deduplicated(self):
        rules = build_rules([
            "DOMAIN,duplicate.example,DIRECT",
            "DOMAIN,duplicate.example,DIRECT",
            "DOMAIN,duplicate.example,PROXY",
            "DOMAIN,duplicate.example,REJECT",
        ])
        self.assertEqual(rules[0]["domain"], ["full:duplicate.example", "full:duplicate.example"])
        self.assertEqual([r["outboundTag"] for r in rules[:-1]], ["direct", "proxy", "block"])
        self.assertEqual(first_outbound(rules, "duplicate.example"), "direct")

    def test_geoip_keeps_its_source_position(self):
        rules = build_rules([
            "DOMAIN,before.example,PROXY",
            "GEOIP,CN,DIRECT",
            "DOMAIN,after.example,PROXY",
        ])
        self.assertEqual(first_outbound(rules, "before.example", in_cn=True), "proxy")
        self.assertEqual(first_outbound(rules, "after.example", in_cn=True), "direct")

    def test_fallback_is_once_and_last(self):
        for source in ([], ["# comment", "// comment"], ["DOMAIN,example.com,PROXY"]):
            with self.subTest(source=source):
                rules = build_rules(source)
                self.assertEqual(rules[-1], {
                    "remarks": "兜底代理", "outboundTag": "proxy", "port": "0-65535",
                })
                self.assertEqual(sum("port" in r for r in rules), 1)
                self.assertEqual(first_outbound(rules, "unmatched.test"), "proxy")


if __name__ == "__main__":
    unittest.main()
