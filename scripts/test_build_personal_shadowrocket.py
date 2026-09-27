#!/usr/bin/env python3
"""Offline regression tests for the Shadowrocket Tailscale exception."""

import ipaddress
import unittest

from build_personal_shadowrocket import (
    TAILSCALE_CIDR,
    TAILSCALE_DIRECT_RULE,
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


if __name__ == "__main__":
    unittest.main()
