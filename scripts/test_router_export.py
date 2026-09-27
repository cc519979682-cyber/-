#!/usr/bin/env python3
"""Tests for scripts/nas/router_export.sh (runs on the router).

The jq and ucode JSON paths must produce the same bundle. Each path is
executed when its tool is installed; the ucode program is also checked
structurally so the test still means something where ucode is absent (CI).
"""

import hashlib
import io
import json
import os
import re
import shutil
import stat
import subprocess
import tarfile
import tempfile
import unittest
from pathlib import Path

EXPORT = Path(__file__).resolve().parent / "nas" / "router_export.sh"
SH = shutil.which("sh")
BASE_TOOLS = ["mktemp", "tr", "sha256sum", "cut", "basename", "cp", "tar", "rm", "mkdir", "cat", "dirname"]


def fake_config(root: Path) -> Path:
    rulesets = root / "data" / "rulesets"
    rulesets.mkdir(parents=True)
    (rulesets / "geosite-cn.srs").write_text('{"version":3,"rules":[{"domain_suffix":["cn"]}]}', encoding="utf-8")
    (root / "data" / "flip").mkdir()
    (root / "data" / "flip" / "obflip-fallback.json").write_text(
        '{"version":2,"rules":[{"domain":["fallback.example"]}]}', encoding="utf-8"
    )
    config = {
        "log": {"level": "warn"},
        "experimental": {"clash_api": {"secret": "clash-secret-value"}},
        "outbounds": [
            {"tag": "Node-A", "type": "vless", "server": "Node.Example.NET", "uuid": "0f8fad5b-d9cb-469f-a165-70867728950e"},
            {"tag": "Node-B", "type": "shadowsocks", "server": "9.9.9.9", "password": "hunter2"},
            {"tag": "Dup", "type": "trojan", "server": "9.9.9.9", "password": "x"},
            {"tag": "direct", "type": "direct"},
            {"tag": "迁移兜底", "type": "selector", "outbounds": ["Node-A"]},
            "not-an-object",
        ],
        "endpoints": [
            {"type": "wireguard", "tag": "wg", "private_key": "k", "peers": [{"address": "wg.example.org", "public_key": "p"}, 5]}
        ],
        "route": {
            "final": "迁移兜底",
            "rule_set": [
                {"tag": "geosite-cn", "type": "local", "format": "binary", "path": str(rulesets / "geosite-cn.srs")},
                {"tag": "obflip-fallback", "path": str(root / "data" / "flip" / "obflip-fallback.json")},
                {"tag": "remote", "type": "remote", "url": "https://example.com/x.srs"},
                {"tag": "inline", "type": "inline", "rules": [{"domain": ["i.example"]}]},
            ],
            "rules": [
                {"action": "sniff"},
                {"domain_suffix": ["中文.example", "a/b"], "outbound": "迁移兜底", "n": 1.5, "b": True, "z": None},
                {"rule_set": ["geosite-cn"], "outbound": "direct"},
            ],
        },
    }
    path = root / "config.json"
    path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def fake_singbox(root: Path) -> Path:
    path = root / "fake-sing-box"
    # sing-box rule-set decompile --output OUT IN  (fixture .srs files are plain JSON)
    path.write_text('#!/bin/sh\n[ "$1 $2 $3" = "rule-set decompile --output" ] || exit 9\ncp "$5" "$4"\n', encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IEXEC)
    return path


def restricted_path(root: Path, extra: list[str]) -> str:
    bin_dir = root / "bin"
    bin_dir.mkdir(exist_ok=True)
    for tool in BASE_TOOLS + extra:
        found = shutil.which(tool)
        if found and not (bin_dir / tool).exists():
            os.symlink(found, bin_dir / tool)
    return str(bin_dir)


def run_export(root: Path, config: Path, tool: str | None, extra_tools: list[str]):
    env = {"PATH": restricted_path(root, extra_tools), "HOME": str(root)}
    if tool:
        env["ROUTER_EXPORT_JSON_TOOL"] = tool
    return subprocess.run(
        [SH, str(EXPORT), str(config), str(fake_singbox(root))],
        env=env,
        capture_output=True,
        timeout=60,
    )


def read_bundle(data: bytes) -> dict:
    files = {}
    with tarfile.open(fileobj=io.BytesIO(data)) as tar:
        for member in tar.getmembers():
            if member.isfile():
                files[member.name.lstrip("./")] = tar.extractfile(member).read().decode("utf-8")
    return files


def canonical(text: str) -> str:
    # Same canonicalisation as scripts/nas/sync_router_rules.sh applies on the NAS.
    return json.dumps(json.loads(text), ensure_ascii=False, separators=(",", ":")) + "\n"


def expected_hashes() -> str:
    addrs = sorted({"Node.Example.NET", "9.9.9.9", "wg.example.org"})
    return "".join(hashlib.sha256(a.lower().encode()).hexdigest() + "\n" for a in addrs)


@unittest.skipIf(SH is None or shutil.which("tar") is None, "needs sh and tar")
class RouterExportTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.config = fake_config(self.root)

    def tearDown(self):
        self._tmp.cleanup()

    def export_with(self, tool: str) -> dict:
        if shutil.which(tool) is None:
            self.skipTest(f"{tool} not installed")
        before = set(Path("/tmp").glob("router-sync.*"))
        result = run_export(self.root, self.config, tool, [tool])
        self.assertEqual(result.returncode, 0, result.stderr.decode())
        self.assertEqual(set(Path("/tmp").glob("router-sync.*")) - before, set(), "temp dir not cleaned up")
        return read_bundle(result.stdout)

    def check_bundle(self, files: dict) -> None:
        self.assertEqual(sorted(files), ["drop_hashes.txt", "route.json", "rulesets/geosite-cn.json", "rulesets/obflip-fallback.json"])
        route = json.loads(files["route.json"])
        self.assertEqual(list(route), ["route"])
        self.assertEqual(route["route"]["final"], "迁移兜底")
        self.assertEqual(files["drop_hashes.txt"], expected_hashes())
        joined = "\n".join(files.values())
        for secret in ("hunter2", "clash-secret-value", "0f8fad5b", "Node.Example.NET", "9.9.9.9", "wg.example.org", "private_key"):
            self.assertNotIn(secret, joined)
        self.assertEqual(json.loads(files["rulesets/obflip-fallback.json"])["rules"][0]["domain"], ["fallback.example"])

    def test_jq_path(self):
        self.check_bundle(self.export_with("jq"))

    def test_ucode_path(self):
        self.check_bundle(self.export_with("ucode"))

    def test_jq_and_ucode_identical(self):
        jq_files = self.export_with("jq")
        uc_files = self.export_with("ucode")
        self.assertEqual(canonical(jq_files.pop("route.json")), canonical(uc_files.pop("route.json")))
        self.assertEqual(jq_files, uc_files)

    def test_autodetect_prefers_jq_then_ucode_and_fails_without_either(self):
        if shutil.which("ucode"):
            result = run_export(self.root, self.config, None, ["ucode"])  # no jq on PATH -> ucode
            self.assertEqual(result.returncode, 0, result.stderr.decode())
            self.assertEqual(read_bundle(result.stdout)["drop_hashes.txt"], expected_hashes())
        with tempfile.TemporaryDirectory() as tmp:  # fresh bin dir without jq/ucode
            result = run_export(Path(tmp), self.config, None, [])
        self.assertEqual(result.returncode, 3)
        self.assertIn(b"neither jq nor ucode", result.stderr)
        self.assertEqual(result.stdout, b"")  # nothing (certainly not the config) is emitted


class UcodeProgramStructureTests(unittest.TestCase):
    """Static checks that hold even where ucode is not installed."""

    def setUp(self):
        text = EXPORT.read_text(encoding="utf-8")
        self.script = text
        self.program = re.search(r"UC_PROG='(.*?)'\n", text, re.S).group(1)

    def test_program_has_no_single_quote_and_balanced_braces(self):
        self.assertNotIn("'", self.program)
        for opening, closing in ("{}", "()", "[]"):
            self.assertEqual(self.program.count(opening), self.program.count(closing))

    def test_program_reads_config_and_implements_three_modes(self):
        self.assertIn('import { readfile } from "fs";', self.program)
        self.assertIn("json(readfile(ARGV[0]))", self.program)
        for mode in ('"route"', '"servers"', '"rulesets"'):
            self.assertIn(f"mode == {mode}", self.program)
        self.assertIn('printf("%J\\n", { route: obj(cfg).route });', self.program)
        self.assertIn("sort(out)", self.program)
        self.assertIn("p.address", self.program)
        self.assertIn("o.server", self.program)

    def test_script_order_and_no_config_copy(self):
        self.assertLess(self.script.index("command -v jq"), self.script.index("command -v ucode"))
        candidates = re.search(r"for c in ([^;]+); do", self.script).group(1).split()
        self.assertEqual(candidates[0], "/opt/open-box/bin/sing-box")
        self.assertIn('ucode -S -e "$UC_PROG" "$CFG" "$1"', self.script)
        self.assertNotIn('cat "$CFG"', self.script)
        self.assertNotIn('cp "$CFG"', self.script)
        self.assertIn("tar -C \"$T/out\" -cf - route.json drop_hashes.txt rulesets", self.script)


if __name__ == "__main__":
    unittest.main()
