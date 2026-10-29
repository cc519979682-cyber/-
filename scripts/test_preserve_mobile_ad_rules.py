"""Offline, stdlib-only tests for the one-time mobile exception migration."""
import contextlib
import io
import re
import tempfile
import unittest
from pathlib import Path

import build_personal_shadowrocket as sr
import preserve_mobile_ad_rules as keep
import sync_router_rules as sync


def published_rows():
    text = (Path(__file__).resolve().parents[1] / "personal/rules.conf").read_bytes().decode("utf-8")
    lines = text.splitlines(keepends=True)
    mobile = keep.marker_span(lines, keep.MOBILE_BEGIN, keep.MOBILE_END, "mobile", False)
    span = mobile or keep.marker_span(lines, keep.AUTO_BEGIN, keep.AUTO_END, "auto", True)
    rows = keep.reject_lines(lines[span[0] + 1:span[1]])
    keep.validate_published(rows)
    return [line.strip() for line, _ in rows]


def fixture(newline="\n"):
    nonreject = [f"DOMAIN,direct{i}.example,DIRECT" for i in range(323)]
    return newline.join(["// existing public header", "DOMAIN,hand.example,PROXY",
                         keep.AUTO_BEGIN, *published_rows(), *nonreject,
                         "DOMAIN-KEYWORD,ouyi,DIRECT", keep.AUTO_END,
                         "GEOIP,CN,DIRECT", ""])


def auto_bytes(text):
    lines = text.splitlines(keepends=True)
    a, b = keep.marker_span(lines, keep.AUTO_BEGIN, keep.AUTO_END, "auto", True)
    return "".join(lines[a:b + 1]).encode("utf-8")


def route(count=323):
    return {"rules": [{"domain": [f"direct{i}.example"], "outbound": "DIRECT"}
                      for i in range(count)]}


def normal_sync(text, count=323):
    report = sync.Report()
    result = sync.sync_text(text, route(count), lambda tag: None,
                            {"DIRECT": "DIRECT"}, report, strict=True)
    return result, report


class PreserveTests(unittest.TestCase):
    def test_copies_only_the_published_39_and_retains_original_auto_bytes(self):
        original = fixture()
        migrated = keep.preserve_text(original)
        self.assertEqual(auto_bytes(original), auto_bytes(migrated))
        self.assertEqual(migrated.replace(migrated[migrated.index(keep.MOBILE_BEGIN):
                         migrated.index(keep.AUTO_BEGIN)], "", 1), original)
        self.assertLess(migrated.index(keep.MOBILE_END), migrated.index(keep.AUTO_BEGIN))
        self.assertEqual(migrated.count(keep.MOBILE_BEGIN), 1)
        self.assertEqual(len(keep.reject_lines(migrated.splitlines())), 78)

    def test_crlf_auto_block_is_byte_preserved(self):
        original = fixture("\r\n")
        result = keep.preserve_text(original)
        self.assertEqual(auto_bytes(original), auto_bytes(result))
        self.assertNotIn("\n", result.replace("\r\n", ""))

    def test_second_run_before_sync_is_byte_identical(self):
        once = keep.preserve_text(fixture())
        self.assertEqual(keep.preserve_text(once), once)

    def test_second_run_after_normal_sync_is_byte_identical(self):
        once = keep.preserve_text(fixture())
        synced, _ = normal_sync(once)
        self.assertEqual(keep.preserve_text(synced), synced)
        self.assertEqual(len(keep.reject_lines(synced.splitlines())), 39)

    def test_two_stage_guard_only_ouyi_leaves_and_rejects_count_as_outside(self):
        original = fixture()
        with self.assertRaisesRegex(sync.GuardError, "40 of 363"):
            normal_sync(original)
        migrated = keep.preserve_text(original)
        synced, _ = normal_sync(migrated)
        before, old, after = sr.split_router_sync_block(original)
        outside, new, ending = sr.split_router_sync_block(synced)
        old_keys = {sync.line_key(line) for line in old}
        new_keys = {sync.line_key(line) for line in new}
        outside_keys = {sync.line_key(line) for line in outside + ending}
        self.assertEqual(old_keys - new_keys - outside_keys,
                         {sync.line_key("DOMAIN-KEYWORD,ouyi,DIRECT")})
        self.assertEqual(len(keep.reject_lines(outside)), 39)
        self.assertEqual(len(keep.reject_lines(new)), 0)
        self.assertNotIn("DOMAIN-KEYWORD,ouyi,DIRECT", synced)

    def test_real_large_deletions_still_hit_original_ten_percent_guard(self):
        with self.assertRaisesRegex(sync.GuardError, "Deletion guard"):
            normal_sync(keep.preserve_text(fixture()), 260)

    def test_minimum_keep_guard_is_not_disabled(self):
        with self.assertRaisesRegex(sync.GuardError, "fewer than"):
            normal_sync(keep.preserve_text(fixture()), 2)

    def test_count_38_or_40_is_refused(self):
        text = fixture()
        one = published_rows()[0] + "\n"
        for changed in [text.replace(one, "", 1),
                        text.replace(keep.AUTO_END, "DOMAIN,extra-ad.example,REJECT\n" + keep.AUTO_END)]:
            with self.subTest(changed=changed[:20]), self.assertRaises(keep.PreserveError):
                keep.preserve_text(changed)

    def test_changed_same_count_source_is_refused_not_a_new_ad_list(self):
        text = fixture().replace(published_rows()[0], "DOMAIN,new-ad.example,REJECT", 1)
        with self.assertRaisesRegex(keep.PreserveError, "fingerprint"):
            keep.preserve_text(text)

    def test_duplicate_reject_is_refused(self):
        rows = published_rows()
        text = fixture().replace(rows[1], rows[0], 1)
        with self.assertRaisesRegex(keep.PreserveError, "unique"):
            keep.preserve_text(text)

    def test_malformed_or_duplicate_markers_refused(self):
        original = fixture()
        cases = [original.replace(keep.AUTO_END, ""),
                 original.replace(keep.AUTO_BEGIN, keep.AUTO_BEGIN + "\n" + keep.AUTO_BEGIN),
                 original.replace(keep.AUTO_BEGIN, keep.AUTO_BEGIN + " extra"),
                 keep.MOBILE_BEGIN + "\n" + original,
                 keep.MOBILE_END + "\n" + original,
                 original + keep.MOBILE_BEGIN + "\n" + keep.MOBILE_END + "\n"]
        for text in cases:
            with self.subTest(text=text[:20]), self.assertRaises(keep.PreserveError):
                keep.preserve_text(text)

    def test_exact_policy_conflict_before_or_after_auto_refused(self):
        kind, value, _ = published_rows()[0].split(",")
        conflict = f"{kind},{value},DIRECT\n"
        for text in [conflict + fixture(), fixture() + conflict]:
            with self.assertRaisesRegex(keep.PreserveError, "conflicting policy"):
                keep.preserve_text(text)

    def test_reordering_over_broader_earlier_auto_policy_refused(self):
        text = fixture().replace(keep.AUTO_BEGIN + "\n",
                                 keep.AUTO_BEGIN + "\nDOMAIN-SUFFIX,com,DIRECT\n")
        with self.assertRaisesRegex(keep.PreserveError, "overtake"):
            keep.preserve_text(text)

    def test_existing_mobile_block_tamper_refused(self):
        once = keep.preserve_text(fixture())
        for text in [once.replace(keep.EXPECTED_DIGEST, "0" * 64, 1),
                     once.replace(keep.MOBILE_END, keep.MOBILE_END + "\n" + keep.MOBILE_END)]:
            with self.assertRaises(keep.PreserveError):
                keep.preserve_text(text)

    def test_reordering_over_earlier_narrow_exception_is_refused(self):
        for kind in ["DOMAIN", "DOMAIN-SUFFIX"]:
            text = fixture().replace(keep.AUTO_BEGIN + "\n", keep.AUTO_BEGIN +
                                     f"\n{kind},allowed.doubleclick.net,DIRECT\n")
            with self.subTest(kind=kind), self.assertRaisesRegex(keep.PreserveError, "overtake"):
                keep.preserve_text(text)

    def test_unsafe_or_extended_reject_syntax_refused(self):
        for line in ["DOMAIN,https://example.invalid/private,REJECT",
                     "DOMAIN,account@example.invalid,REJECT",
                     "DOMAIN,ads.example,REJECT,unexpected-option"]:
            text = fixture().replace(published_rows()[0], line, 1)
            with self.assertRaises(keep.PreserveError):
                keep.preserve_text(text)

    def test_cli_defaults_to_dry_run_then_explicit_write_is_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "rules.conf"
            original = fixture("\r\n").encode("utf-8")
            path.write_bytes(original)
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(keep.main(["--rules", str(path)]), 0)
                self.assertEqual(path.read_bytes(), original)
                self.assertEqual(keep.main(["--rules", str(path), "--write"]), 0)
                after = path.read_bytes()
                self.assertEqual(keep.main(["--rules", str(path), "--write"]), 0)
            self.assertEqual(path.read_bytes(), after)
            self.assertEqual(auto_bytes(original.decode()), auto_bytes(after.decode()))

    def test_migration_source_has_no_private_auth_or_network_client(self):
        source = Path(keep.__file__).read_text(encoding="utf-8")
        self.assertNotRegex(source, r"(?:vless|vmess|trojan|hysteria2)://|github_pat_[A-Za-z0-9_]+|ghp_[A-Za-z0-9]+")
        self.assertNotIn("urllib", source)
        self.assertNotIn("requests", source)
        self.assertNotIn("allow_large_deletion", source)


if __name__ == "__main__":
    unittest.main()
