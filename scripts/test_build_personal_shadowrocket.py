#!/usr/bin/env python3
"""Offline regression tests for the Shadowrocket Tailscale exception."""

import ipaddress
import unittest

from build_personal_shadowrocket import (
    HOME_ACCESS_DOMAINS,
    MELCO_REAL_IP_DOMAINS,
    TAILSCALE_CIDR,
    TAILSCALE_DIRECT_RULE,
    add_home_access_exceptions,
    enforce_melco_priority,
    keep_tailnet_in_tun,
)


class TailnetRoutingTests(unittest.TestCase):
    def test_tailnet_is_not_excluded_from_tun_or_sent_to_proxy(self):
        source = (
            "[General]\n"
            "skip-proxy = localhost, 192.168.0.0/16\n"
            "bypass-tun = 10.0.0.0/8,100.64.0.0/10,192.168.0.0/16\n"
            "tun-excluded-routes = 100.64.0.0/10,127.0.0.0/8\n"
            "[Rule]\n"
            "GEOIP,CN,DIRECT\n"
            "FINAL,PROXY\n"
        )
        result = keep_tailnet_in_tun(source)
        self.assertIn("skip-proxy = localhost, 192.168.0.0/16, 100.64.0.0/10", result)
        self.assertIn("bypass-tun = 10.0.0.0/8,192.168.0.0/16", result)
        self.assertIn("tun-excluded-routes = 127.0.0.0/8", result)
        self.assertEqual(result.split("[Rule]\n", 1)[1].splitlines()[1], TAILSCALE_DIRECT_RULE)
        self.assertLess(result.index(TAILSCALE_DIRECT_RULE), result.index("GEOIP,CN,DIRECT"))
        self.assertLess(result.index(TAILSCALE_DIRECT_RULE), result.index("FINAL,PROXY"))
        self.assertIn(ipaddress.ip_address("100.64.1.2"), ipaddress.ip_network(TAILSCALE_CIDR))
        self.assertEqual(keep_tailnet_in_tun(result), result)

    def test_missing_general_proxy_exception_fails_closed(self):
        with self.assertRaises(ValueError):
            keep_tailnet_in_tun("[General]\nbypass-tun = 100.64.0.0/10\n[Rule]\nFINAL,PROXY\n")



class MelcoRealIpTests(unittest.TestCase):
    def test_always_real_ip_includes_melco_without_skip_proxy(self):
        source = (
            "[General]\n"
            "skip-proxy = localhost\n"
            "always-real-ip = example.com\n"
            "[Rule]\n"
            "FINAL,PROXY\n"
        )
        result = add_home_access_exceptions(source)
        general = result.split("[Rule]", 1)[0]
        skip_line = next(
            line for line in general.splitlines() if line.strip().lower().startswith("skip-proxy")
        )
        always_line = next(
            line for line in general.splitlines() if line.strip().lower().startswith("always-real-ip")
        )
        for domain in HOME_ACCESS_DOMAINS:
            self.assertIn(domain, skip_line)
            self.assertIn(domain, always_line)
        for domain in MELCO_REAL_IP_DOMAINS:
            self.assertNotIn(domain, skip_line)
            self.assertIn(domain, always_line)
        self.assertIn("melco-dxmobprod.com", always_line)
        self.assertIn("*.melcoclub.com", always_line)

if __name__ == "__main__":
    unittest.main()

class MelcoPriorityTests(unittest.TestCase):
    def test_melco_hoisted_before_cn_direct_and_apm_reject(self):
        source = (
            "[General]\n"
            "dns-server = https://223.5.5.5/dns-query\n"
            "[Rule]\n"
            "DOMAIN-SUFFIX,example.com,PROXY,force-remote-dns\n"
            "DOMAIN-SUFFIX,melcoclub.cn,PROXY,force-remote-dns\n"
            "DOMAIN-SUFFIX,heapanalytics.com,REJECT\n"
            "DOMAIN-SUFFIX,cn,DIRECT\n"
            "FINAL,PROXY\n"
        )
        result = enforce_melco_priority(source)
        rule = result.split("[Rule]\n", 1)[1]
        melco_cn = "DOMAIN-SUFFIX,melcoclub.cn,PROXY,force-remote-dns"
        mcp = "DOMAIN,mcp-blue.melcoclub.cn,PROXY,force-remote-dns"
        heap = "DOMAIN-SUFFIX,heapanalytics.com,PROXY,force-remote-dns"
        cn = "DOMAIN-SUFFIX,cn,DIRECT"
        self.assertIn(mcp, rule)
        self.assertIn(melco_cn, rule)
        self.assertIn(heap, rule)
        self.assertLess(rule.index(mcp), rule.index(cn))
        self.assertLess(rule.index(melco_cn), rule.index(cn))
        self.assertLess(rule.index(heap), rule.index(cn))
        self.assertEqual(rule.count(melco_cn), 1)
        self.assertNotIn("DOMAIN-SUFFIX,heapanalytics.com,REJECT", rule)
