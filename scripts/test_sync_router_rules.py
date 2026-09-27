#!/usr/bin/env python3
"""Offline tests for the router (sing-box) -> rules.conf sync. Stdlib only."""

import contextlib
import io
import json
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path

import build_personal_shadowrocket as sr
import sync_router_rules as srr

sys.path.insert(0, str(Path(__file__).resolve().parent / "nas"))
import github_sync  # noqa: E402

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "router_bundle"
OUTBOUND_MAP = Path(__file__).resolve().parent / "router_outbound_map.json"

HAND_KEPT = """// Public-safe OpenBox routing sync: priority AI domains.
DOMAIN-SUFFIX,chatgpt.com,PROXY,force-remote-dns
DOMAIN-SUFFIX,openai.com,PROXY,force-remote-dns
// Home NAS must stay DIRECT
DOMAIN,chenxuning.cc,DIRECT
DOMAIN-SUFFIX,chenxuning.cc,DIRECT
DOMAIN-SUFFIX,browserleaks.com,PROXY,force-remote-dns
DOMAIN-SUFFIX,futunn.com,PROXY,force-remote-dns
DOMAIN-SUFFIX,doubleclick.net,REJECT
DOMAIN-SUFFIX,qq.com,DIRECT
IP-CIDR,8.149.128.52/32,DIRECT
GEOIP,CN,DIRECT
"""


def load_route(path=FIXTURE / "route.json"):
    return srr.load_route_document(Path(path).read_text(encoding="utf-8"))


def run_sync(text, route=None, rulesets_dir=FIXTURE / "rulesets", **kwargs):
    route = route if route is not None else load_route()
    report = srr.Report()
    resolver = srr.build_ruleset_resolver(route, rulesets_dir, report)
    kwargs.setdefault("drop_hashes", srr.load_drop_hashes(FIXTURE / "drop_hashes.txt"))
    new_text = srr.sync_text(text, route, resolver, srr.load_outbound_map(OUTBOUND_MAP), report, **kwargs)
    return new_text, report


def block_of(text):
    _, block, _ = sr.split_router_sync_block(text)
    return block


def outside_of(text):
    before, _, after = sr.split_router_sync_block(text)
    return before + after


class OutboundMapTests(unittest.TestCase):
    def test_committed_map_policies(self):
        mapping = srr.load_outbound_map(OUTBOUND_MAP)
        for tag in ("DIRECT", "direct", "dnsmasq", "Domestic"):
            self.assertEqual(mapping[tag], "DIRECT")
        for tag in ("REJECT", "block"):
            self.assertEqual(mapping[tag], "REJECT")
        for tag in ("Webshare-US-Residential", "AI-Residential"):
            self.assertEqual(mapping[tag], "DROP")
        for tag in ("Proxy", "OpenAI", "迁移兜底", "Auto - UrlTest", "Google FCM"):
            self.assertEqual(mapping[tag], "PROXY")
        self.assertFalse(any("Reality" in tag or "DediOne" in tag for tag in mapping))
        self.assertFalse(any(srr.IPV4_RE.search(tag) for tag in mapping))

    def test_override_layer(self):
        with tempfile.TemporaryDirectory() as tmp:
            override = Path(tmp) / "o.json"
            override.write_text(json.dumps({"DROP": ["OpenAI"], "PROXY": ["Local-Only"]}), encoding="utf-8")
            mapping = srr.load_outbound_map(OUTBOUND_MAP, override)
        self.assertEqual(mapping["OpenAI"], "DROP")
        self.assertEqual(mapping["Local-Only"], "PROXY")
        self.assertEqual(mapping["direct"], "DIRECT")


class ConversionTests(unittest.TestCase):
    def setUp(self):
        self.text, self.report = run_sync(HAND_KEPT)
        self.block = block_of(self.text)

    def test_field_mapping_and_conventions(self):
        block = self.block
        self.assertIn("DOMAIN,login.example-bank.com,DIRECT", block)
        self.assertIn("DOMAIN-SUFFIX,example-bank.cn,DIRECT", block)
        self.assertIn("DOMAIN-KEYWORD,examplecdn,DIRECT", block)
        self.assertIn("DOMAIN-SUFFIX,sora-example.ai,PROXY,force-remote-dns", block)
        self.assertIn("DOMAIN-KEYWORD,openai,PROXY,force-remote-dns", block)
        self.assertIn("IP-CIDR,8.8.4.0/24,PROXY,no-resolve", block)
        self.assertIn("IP-CIDR6,2001:4860::/32,PROXY,no-resolve", block)
        self.assertIn("IP-CIDR,114.114.114.0/24,DIRECT,no-resolve", block)
        # leading dot of a sing-box suffix is dropped
        self.assertIn("DOMAIN-SUFFIX,proxy-site.example,PROXY,force-remote-dns", block)
        for line in block:
            policy = line.split(",")[2]
            self.assertIn(policy, {"DIRECT", "PROXY", "REJECT"})
            if policy == "PROXY" and line.startswith("DOMAIN"):
                self.assertTrue(line.endswith(",force-remote-dns"), line)

    def test_actions(self):
        # action reject -> REJECT (via inline rule_set)
        self.assertIn("DOMAIN-SUFFIX,ads.example-tracker.com,REJECT", self.block)
        self.assertEqual(self.report.counts["ignored_action_sniff"], 1)
        self.assertEqual(self.report.counts["ignored_action_hijack-dns"], 1)
        self.assertEqual(self.report.counts["ignored_action_resolve"], 1)

    def test_rule_set_expansion(self):
        self.assertIn("DOMAIN-SUFFIX,example.cn,DIRECT", self.block)
        self.assertIn("DOMAIN-SUFFIX,fallback-direct.example", "\n".join(self.block))  # source-format file
        self.assertNotIn("not-this.example", "\n".join(self.block))  # invert in rule-set
        self.assertEqual(self.report.counts["skipped_remote_rule_set"], 1)
        self.assertGreaterEqual(self.report.counts["dropped_domain_regex"], 2)

    def test_device_specific_private_and_drop_tags_never_published(self):
        joined = "\n".join(self.block)
        for needle in (
            "192.168.",
            "10.0.0.0",
            "kid-games.example",
            "device.example",
            "tun-only.example",
            "residential-only.example",
            "Steam",
            "198.51.100.7",
            "xmpp.example",
            "a.example,",
            "inverted.example",
        ):
            self.assertNotIn(needle, joined)
        self.assertGreaterEqual(self.report.counts["skipped_device_specific"], 4)
        self.assertEqual(self.report.counts["skipped_drop_outbound"], 2)
        self.assertNotIn("迁移兜底", self.text)  # route.final is not a rule

    def test_logical_or_expanded_and_skipped(self):
        self.assertIn("DOMAIN-SUFFIX,or-one.example,PROXY,force-remote-dns", self.block)
        self.assertIn("DOMAIN,or-two.example,PROXY,force-remote-dns", self.block)
        self.assertEqual(self.report.counts["skipped_logical"], 1)

    def test_node_addresses_dropped_by_hash(self):
        joined = "\n".join(self.block)
        self.assertNotIn("9.9.9.9", joined)
        self.assertNotIn("node.example-vps.net", joined)
        self.assertEqual(self.report.counts["skipped_node_address"], 2)

    def test_router_first_match_wins_within_block(self):
        # example-bank.cn appears DIRECT first, then PROXY later: keep DIRECT only.
        matches = [line for line in self.block if ",example-bank.cn," in line]
        self.assertEqual(matches, ["DOMAIN-SUFFIX,example-bank.cn,DIRECT"])


class UnknownTagTests(unittest.TestCase):
    def test_unknown_tag_skipped_and_masked(self):
        text, report = run_sync(HAND_KEPT)
        self.assertNotIn("mystery.example", text)
        self.assertIn("Some-Node-203.0.113.9-SS", report.unknown_tags)
        rendered = "\n".join(report.lines())
        self.assertIn("unknown outbound tag", rendered)
        self.assertNotIn("203.0.113.9", rendered)

    def test_strict_fails(self):
        with self.assertRaises(srr.UnknownTagError) as ctx:
            run_sync(HAND_KEPT, strict=True)
        self.assertNotIn("203.0.113.9", str(ctx.exception))

    def test_cli_strict_exit_code(self):
        with tempfile.TemporaryDirectory() as tmp:
            rules = Path(tmp) / "rules.conf"
            rules.write_text(HAND_KEPT, encoding="utf-8")
            with contextlib.redirect_stderr(io.StringIO()):
                code = srr.main([str(FIXTURE / "route.json"), "--rulesets-dir", str(FIXTURE / "rulesets"),
                                 "--rules", str(rules), "--strict"])
            self.assertEqual(code, 3)
            self.assertEqual(rules.read_text(encoding="utf-8"), HAND_KEPT)


class InputSafetyTests(unittest.TestCase):
    def assert_rejected(self, document):
        with self.assertRaises(srr.SyncError):
            srr.load_route_document(json.dumps(document))

    def test_rejects_full_config_and_secret_keys(self):
        route = json.loads((FIXTURE / "route.json").read_text(encoding="utf-8"))
        self.assert_rejected({**route, "outbounds": [{"tag": "x", "type": "direct"}]})
        self.assert_rejected({**route, "inbounds": []})
        self.assert_rejected({**route, "dns": {}})
        for key in ("password", "uuid", "private_key", "secret"):
            bad = json.loads(json.dumps(route))
            bad["route"]["rules"][0][key] = "x"
            self.assert_rejected(bad)

    def test_rejects_secret_looking_strings(self):
        route = json.loads((FIXTURE / "route.json").read_text(encoding="utf-8"))
        bad = json.loads(json.dumps(route))
        bad["route"]["rules"].append({"domain": ["a.example"], "outbound": "vless://abc@1.2.3.4:443"})
        self.assert_rejected(bad)
        bad = json.loads(json.dumps(route))
        bad["route"]["rules"].append({"domain": ["a.example"], "outbound": "0f8fad5b-d9cb-469f-a165-70867728950e"})
        self.assert_rejected(bad)

    def test_rejects_empty_rules(self):
        self.assert_rejected({"route": {"rules": []}})

    def test_ruleset_file_with_extra_keys_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "x.json"
            path.write_text(json.dumps({"version": 2, "rules": [], "outbounds": []}), encoding="utf-8")
            with self.assertRaises(srr.SyncError):
                srr.load_ruleset_file(path)

    def test_missing_ruleset_fails_unless_allowed(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(srr.MissingRuleSetError):
                run_sync(HAND_KEPT, rulesets_dir=Path(tmp))
            text, report = run_sync(HAND_KEPT, rulesets_dir=Path(tmp), allow_missing_rulesets=True)
            self.assertIn("geosite-openai", report.missing_rulesets)
            self.assertIn("DOMAIN-KEYWORD,examplecdn,DIRECT", block_of(text))


class OutputSafetyTests(unittest.TestCase):
    def test_secret_in_block_refused(self):
        with self.assertRaises(ValueError):
            srr.assert_block_public_safe(["DOMAIN,0f8fad5b-d9cb-469f-a165-70867728950e.example,DIRECT"])
        with self.assertRaises(ValueError):
            srr.assert_block_public_safe(["DOMAIN,192.168.1.1,DIRECT"])
        with self.assertRaises(ValueError):
            srr.assert_block_public_safe(["DOMAIN,a.example,Some-Node"])

    def test_uuid_like_domain_from_router_refuses_whole_sync(self):
        route = {"rules": [{"domain_suffix": ["0f8fad5b-d9cb-469f-a165-70867728950e.example"], "outbound": "direct"}]}
        with self.assertRaises(srr.SyncError):
            run_sync(HAND_KEPT, route=route)

    def test_sensitive_word_domain_is_skipped_not_published(self):
        route = {"rules": [{"domain_suffix": ["token.example", "fine.example"], "outbound": "direct"}]}
        text, report = run_sync(HAND_KEPT, route=route)
        self.assertEqual(block_of(text), ["DOMAIN-SUFFIX,fine.example,DIRECT"])
        self.assertEqual(report.counts["skipped_sensitive_word"], 1)


class MarkerTests(unittest.TestCase):
    def test_insertion_before_trailing_geoip_and_outside_untouched(self):
        text, _ = run_sync(HAND_KEPT)
        lines = text.splitlines()
        self.assertEqual(lines[0], HAND_KEPT.splitlines()[0])  # AI priority rules stay first
        self.assertEqual(lines[-1], "GEOIP,CN,DIRECT")
        self.assertEqual(lines[-2], sr.ROUTER_SYNC_END)
        self.assertEqual(outside_of(text), HAND_KEPT.splitlines())

    def test_replacement_keeps_outside_bytes(self):
        seeded = sr.replace_router_sync_block(HAND_KEPT, ["DOMAIN-SUFFIX,old.example,DIRECT"])
        # hand edits placed after the block must survive too
        seeded = seeded.replace("GEOIP,CN,DIRECT", "DOMAIN-SUFFIX,added-later.example,DIRECT\nGEOIP,CN,DIRECT")
        text, _ = run_sync(seeded)
        self.assertEqual(outside_of(text), outside_of(seeded))
        self.assertNotIn("old.example", text)
        self.assertIn("added-later.example", text)

    def test_empty_markers_in_repo_rules(self):
        repo_rules = Path(__file__).resolve().parent.parent / "personal" / "rules.conf"
        before, block, after = sr.split_router_sync_block(repo_rules.read_text(encoding="utf-8"))
        self.assertIsNotNone(block)
        self.assertTrue(before[0].startswith("// Public-safe OpenBox routing sync"))

    def test_malformed_markers_rejected(self):
        with self.assertRaises(ValueError):
            sr.split_router_sync_block(f"{sr.ROUTER_SYNC_END}\n{sr.ROUTER_SYNC_BEGIN}\n")
        with self.assertRaises(ValueError):
            sr.split_router_sync_block(f"{sr.ROUTER_SYNC_BEGIN}\nDOMAIN,a,DIRECT\n")

    def test_dedupe_against_hand_kept_lines(self):
        text, report = run_sync(HAND_KEPT)
        block = "\n".join(block_of(text))
        # openai.com / chatgpt.com / qq.com are hand-kept already
        self.assertNotIn(",openai.com,", block)
        self.assertNotIn(",chatgpt.com,", block)
        self.assertNotIn(",qq.com,", block)
        self.assertGreaterEqual(report.counts["deduped_hand_kept"], 3)

    def test_idempotent(self):
        once, _ = run_sync(HAND_KEPT)
        twice, _ = run_sync(once)
        self.assertEqual(once, twice)
        self.assertIs(twice, once)  # no rewrite at all on a no-op run

    def test_markers_survive_build_parsing(self):
        text, _ = run_sync(HAND_KEPT)
        rules = sr.sanitize_rules(text)
        self.assertIn("DOMAIN-KEYWORD,examplecdn,DIRECT", rules)
        self.assertFalse(any("router-sync" in rule for rule in rules))

    def test_refresh_from_preserves_router_block(self):
        seeded, _ = run_sync(HAND_KEPT)
        refreshed = sr.refreshed_personal_text(
            ["DOMAIN-SUFFIX,new-hand.example,DIRECT", "DOMAIN-KEYWORD,examplecdn,DIRECT", "GEOIP,CN,DIRECT"], seeded
        )
        before, block, after = sr.split_router_sync_block(refreshed)
        self.assertEqual(before, ["DOMAIN-SUFFIX,new-hand.example,DIRECT", "DOMAIN-KEYWORD,examplecdn,DIRECT"])
        self.assertEqual(after, ["GEOIP,CN,DIRECT"])
        self.assertNotIn("DOMAIN-KEYWORD,examplecdn,DIRECT", block)  # now hand-kept, deduped
        self.assertIn("DOMAIN-SUFFIX,example.cn,DIRECT", block)


class DeletionGuardTests(unittest.TestCase):
    def seeded(self, count):
        old = [f"DOMAIN-SUFFIX,old{i}.example,DIRECT" for i in range(count)]
        return sr.replace_router_sync_block(HAND_KEPT, old)

    def route_keeping(self, count):
        return {"rules": [{"domain_suffix": [f"old{i}.example" for i in range(count)], "outbound": "direct"}]}

    def test_large_deletion_aborts_without_change(self):
        seeded = self.seeded(40)
        with self.assertRaises(srr.GuardError):
            run_sync(seeded, route=self.route_keeping(30))  # 25% removed

    def test_small_deletion_ok(self):
        text, _ = run_sync(self.seeded(40), route=self.route_keeping(37))  # 7.5% removed
        self.assertEqual(len(block_of(text)), 37)

    def test_threshold_configurable_and_override(self):
        run_sync(self.seeded(40), route=self.route_keeping(30), max_delete_ratio=0.5)
        run_sync(self.seeded(40), route=self.route_keeping(1), allow_large_deletion=True)

    def test_small_previous_block_not_guarded(self):
        text, _ = run_sync(self.seeded(19), route=self.route_keeping(1))
        self.assertEqual(len(block_of(text)), 1)

    def test_moving_rules_to_hand_kept_is_not_deletion(self):
        seeded = self.seeded(40)
        hand = "\n".join(f"DOMAIN-SUFFIX,old{i}.example,DIRECT" for i in range(30, 40))
        seeded = seeded.replace("GEOIP,CN,DIRECT", hand + "\nGEOIP,CN,DIRECT")
        text, _ = run_sync(seeded, route=self.route_keeping(40))
        self.assertEqual(len(block_of(text)), 30)

    def test_cli_guard_exit_code_and_no_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            rules = Path(tmp) / "rules.conf"
            seeded = self.seeded(40)
            rules.write_text(seeded, encoding="utf-8")
            route = Path(tmp) / "route.json"
            route.write_text(json.dumps({"route": self.route_keeping(10)}), encoding="utf-8")
            with contextlib.redirect_stderr(io.StringIO()):
                code = srr.main([str(route), "--rules", str(rules)])
            self.assertEqual(code, 2)
            self.assertEqual(rules.read_text(encoding="utf-8"), seeded)

    def test_cli_dry_run_prints_diff_and_writes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            rules = Path(tmp) / "rules.conf"
            rules.write_text(HAND_KEPT, encoding="utf-8")
            out = io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
                code = srr.main([str(FIXTURE / "route.json"), "--rulesets-dir", str(FIXTURE / "rulesets"),
                                 "--rules", str(rules), "--dry-run"])
            self.assertEqual(code, 0)
            self.assertIn("+DOMAIN-KEYWORD,examplecdn,DIRECT", out.getvalue())
            self.assertEqual(rules.read_text(encoding="utf-8"), HAND_KEPT)


class FakeClient:
    path = "personal/rules.conf"

    def __init__(self, texts, conflicts=0):
        self.texts = list(texts)
        self.conflicts = conflicts
        self.puts = []

    def get_file(self):
        text = self.texts.pop(0) if len(self.texts) > 1 else self.texts[0]
        return text, f"sha-{len(self.puts)}-{len(self.texts)}"

    def put_file(self, text, sha, message):
        if self.conflicts:
            self.conflicts -= 1
            raise github_sync.GitHubError(409, "sha mismatch")
        self.puts.append((text, sha, message))
        return "commit123"


class GitHubSyncTests(unittest.TestCase):
    def convert(self, text):
        return run_sync(text)[0]

    def test_unchanged_does_not_put(self):
        synced = self.convert(HAND_KEPT)
        client = FakeClient([synced])
        self.assertEqual(github_sync.sync_once(client, self.convert), "unchanged")
        self.assertEqual(client.puts, [])

    def test_put_with_message(self):
        client = FakeClient([HAND_KEPT])
        self.assertEqual(github_sync.sync_once(client, self.convert), "commit123")
        self.assertEqual(client.puts[0][2], "Sync router rules (auto)")

    def test_conflict_refetches_once(self):
        newer = HAND_KEPT.replace("GEOIP,CN,DIRECT", "DOMAIN-SUFFIX,codex.example,DIRECT\nGEOIP,CN,DIRECT")
        client = FakeClient([HAND_KEPT, newer], conflicts=1)
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(github_sync.sync_once(client, self.convert), "commit123")
        self.assertIn("codex.example", client.puts[0][0])  # someone else's change kept

    def test_second_conflict_raises(self):
        client = FakeClient([HAND_KEPT], conflicts=2)
        with self.assertRaises(github_sync.GitHubError), contextlib.redirect_stderr(io.StringIO()):
            github_sync.sync_once(client, self.convert)

    def test_token_file_permissions_and_repr(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "pat"
            path.write_text("github_pat_example\n", encoding="utf-8")
            os.chmod(path, 0o644)
            with self.assertRaises(SystemExit):
                github_sync.read_token(path)
            os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
            token = github_sync.read_token(path)
            client = github_sync.GitHubClient("o/r", "main", "personal/rules.conf", token)
            self.assertNotIn(token, repr(client))

    def test_tokenless_client_never_writes(self):
        client = github_sync.GitHubClient("o/r", "main", "personal/rules.conf", "")
        with self.assertRaises(github_sync.GitHubError):
            client.put_file("x", "sha", "msg")

    def test_token_required_unless_dry_run(self):
        with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
            github_sync.main(["--bundle", str(FIXTURE)])


if __name__ == "__main__":
    unittest.main()
