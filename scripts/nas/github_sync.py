#!/usr/bin/env python3
"""NAS side: convert a router bundle and update personal/rules.conf via the GitHub REST API.

No git needed. Flow: GET the file (content + sha) -> run the converter ->
PUT only when the text changed, commit message "Sync router rules (auto)".
If the sha is stale (someone else pushed meanwhile) re-fetch and retry once.
The token is read from a file (must be chmod 600) and is never printed.

All reads go through api.github.com (raw.githubusercontent.com resets connections
from the NAS). Every HTTP call is retried on network errors / timeouts / 5xx:
3 attempts, GITHUB_RETRY_DELAY seconds apart (default 30). 4xx is never retried.
"""

from __future__ import annotations

import argparse
import base64
import http.client
import json
import os
import stat
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Callable

SCRIPTS_DIR = Path(__file__).resolve().parent.parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import sync_router_rules as srr  # noqa: E402

COMMIT_MESSAGE = "Sync router rules (auto)"
DEFAULT_API = "https://api.github.com"
DEFAULT_ATTEMPTS = 3
DEFAULT_RETRY_DELAY = 30.0


def default_retry_delay() -> float:
    try:
        return max(0.0, float(os.environ.get("GITHUB_RETRY_DELAY", DEFAULT_RETRY_DELAY)))
    except ValueError:
        return DEFAULT_RETRY_DELAY


class GitHubError(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(f"GitHub API error {status}: {message}")
        self.status = status


def read_token(path: Path) -> str:
    info = path.stat()
    if info.st_mode & (stat.S_IRWXG | stat.S_IRWXO):
        raise SystemExit(f"ERROR token file {path} must not be readable by others: run chmod 600 {path}")
    token = path.read_text(encoding="utf-8").strip()
    if not token:
        raise SystemExit(f"ERROR token file {path} is empty")
    return token


class GitHubClient:
    def __init__(
        self,
        repo: str,
        branch: str,
        path: str,
        token: str,
        api: str = DEFAULT_API,
        attempts: int = DEFAULT_ATTEMPTS,
        retry_delay: float | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.repo = repo
        self.branch = branch
        self.path = path
        self._token = token
        self.api = api.rstrip("/")
        self.attempts = max(1, attempts)
        self.retry_delay = default_retry_delay() if retry_delay is None else retry_delay
        self._sleep = sleep

    def __repr__(self) -> str:  # never leak the token via repr/logging
        return f"GitHubClient(repo={self.repo!r}, branch={self.branch!r}, path={self.path!r})"

    def _request_once(self, method: str, url: str, data: bytes | None) -> dict:
        request = urllib.request.Request(url, data=data, method=method)
        if self._token:
            request.add_header("Authorization", f"Bearer {self._token}")
        request.add_header("Accept", "application/vnd.github+json")
        request.add_header("X-GitHub-Api-Version", "2022-11-28")
        request.add_header("User-Agent", "router-rule-sync")
        if data is not None:
            request.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                return json.loads(response.read().decode("utf-8") or "{}")
        except urllib.error.HTTPError as exc:
            try:
                message = json.loads(exc.read().decode("utf-8")).get("message", "")
            except Exception:  # noqa: BLE001
                message = exc.reason or ""
            raise GitHubError(exc.code, str(message)) from None

    def _request(self, method: str, url: str, body: dict | None = None) -> dict:
        """One API call with retries on transient failures (network, timeout, 5xx).

        4xx responses (including 409/422 on PUT, handled by sync_once) are raised at once.
        A PUT whose response was lost may already have been applied; its retry then gets a
        409/422 for the stale sha and sync_once re-fetches, which yields 'unchanged'.
        """

        data = json.dumps(body).encode("utf-8") if body is not None else None
        where = method + " " + url.split("/repos/", 1)[-1].split("?", 1)[0]
        for attempt in range(1, self.attempts + 1):
            try:
                return self._request_once(method, url, data)
            except GitHubError as exc:
                if exc.status < 500:
                    raise
                reason = f"HTTP {exc.status}"
                failure: Exception = exc
            except (OSError, http.client.HTTPException) as exc:  # URLError, resets, timeouts, TLS errors
                reason = str(getattr(exc, "reason", "") or exc) or type(exc).__name__
                failure = GitHubError(0, f"network error: {reason}")
            if attempt == self.attempts:
                print(f"ERROR GitHub {where} failed after {self.attempts} attempts: {reason}", file=sys.stderr)
                raise failure
            print(
                f"WARNING GitHub {where} failed ({reason}); retry {attempt}/{self.attempts - 1} "
                f"in {self.retry_delay:g}s",
                file=sys.stderr,
            )
            self._sleep(self.retry_delay)
        raise AssertionError("unreachable")

    def _repo_url(self, suffix: str) -> str:
        owner, name = self.repo.split("/", 1)
        return f"{self.api}/repos/{urllib.parse.quote(owner)}/{urllib.parse.quote(name)}/{suffix}"

    def get_file(self) -> tuple[str, str]:
        # Contents API works without a token for this public repo (dry run); the token,
        # when present, is sent for a higher rate limit.
        url = self._repo_url(
            "contents/" + urllib.parse.quote(self.path) + "?ref=" + urllib.parse.quote(self.branch)
        )
        meta = self._request("GET", url)
        sha = meta["sha"]
        if meta.get("encoding") == "base64" and meta.get("content"):
            raw = base64.b64decode(meta["content"])
        else:  # files > 1 MB: fetch the blob
            blob = self._request("GET", self._repo_url(f"git/blobs/{sha}"))
            raw = base64.b64decode(blob["content"])
        return raw.decode("utf-8"), sha

    def put_file(self, text: str, sha: str, message: str) -> str:
        if not self._token:
            raise GitHubError(401, "no token: refusing to write (dry run only)")
        url = self._repo_url("contents/" + urllib.parse.quote(self.path))
        body = {
            "message": message,
            "content": base64.b64encode(text.encode("utf-8")).decode("ascii"),
            "sha": sha,
            "branch": self.branch,
        }
        result = self._request("PUT", url, body)
        return str(result.get("commit", {}).get("sha", ""))


def sync_once(client, convert: Callable[[str], str], dry_run: bool = False, message: str = COMMIT_MESSAGE) -> str:
    """Return 'unchanged', 'dry-run' or the new commit sha."""

    for attempt in range(2):
        text, sha = client.get_file()
        new_text = convert(text)
        if new_text == text:
            return "unchanged"
        if dry_run:
            sys.stdout.write(srr.unified_diff(text, new_text, client.path))
            return "dry-run"
        try:
            return client.put_file(new_text, sha, message) or "pushed"
        except GitHubError as exc:
            # 409: sha conflict; 422 is also returned for a stale sha.
            if exc.status in (409, 422) and attempt == 0:
                print("WARNING file changed on GitHub meanwhile, re-fetching and retrying once", file=sys.stderr)
                continue
            raise
    raise GitHubError(409, "conflict persisted after retry")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Sync router rules into GitHub (no git needed)")
    parser.add_argument("--bundle", type=Path, required=True, help="Dir with route.json, rulesets/, drop_hashes.txt")
    parser.add_argument("--repo", default=os.environ.get("GITHUB_REPO", "cc519979682-cyber/-"))
    parser.add_argument("--branch", default=os.environ.get("GITHUB_BRANCH", "main"))
    parser.add_argument("--path", default="personal/rules.conf")
    parser.add_argument("--token-file", type=Path, help="Required unless --dry-run (public repo is read anonymously)")
    parser.add_argument("--api", default=DEFAULT_API)
    parser.add_argument("--outbound-map", type=Path, default=srr.DEFAULT_OUTBOUND_MAP)
    parser.add_argument("--outbound-map-override", type=Path)
    parser.add_argument("--strict", action="store_true")
    parser.add_argument("--allow-missing-rulesets", action="store_true")
    parser.add_argument("--allow-large-deletion", action="store_true")
    parser.add_argument("--max-delete-ratio", type=float, default=srr.DEFAULT_MAX_DELETE_RATIO)
    parser.add_argument("--include-rule-sets", action="store_true", help="Expand rule_set references (opt-in)")
    parser.add_argument("--hand-rules-win", action="store_true", help="Old mode: hand-kept duplicates win")
    parser.add_argument("--include-ruleset-ip-direct", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    report = srr.Report()
    try:
        route = srr.load_route_document((args.bundle / "route.json").read_text(encoding="utf-8"))
        resolver = srr.build_ruleset_resolver(route, args.bundle / "rulesets", report)
        outbound_map = srr.load_outbound_map(args.outbound_map, args.outbound_map_override)
        drop_hashes = srr.load_drop_hashes(args.bundle / "drop_hashes.txt")

        def convert(text: str) -> str:
            report.__init__()
            return srr.sync_text(
                text,
                route,
                resolver,
                outbound_map,
                report,
                drop_hashes=drop_hashes,
                strict=args.strict,
                allow_missing_rulesets=args.allow_missing_rulesets,
                max_delete_ratio=args.max_delete_ratio,
                allow_large_deletion=args.allow_large_deletion,
                skip_ruleset_ip_direct=not args.include_ruleset_ip_direct,
                include_rule_sets=args.include_rule_sets,
                hand_rules_win=args.hand_rules_win,
            )

        if args.token_file is not None:
            token = read_token(args.token_file)
        elif args.dry_run:
            token = ""
        else:
            raise SystemExit("ERROR --token-file is required unless --dry-run")
        client = GitHubClient(args.repo, args.branch, args.path, token, args.api)
        result = sync_once(client, convert, dry_run=args.dry_run)
    except srr.GuardError as exc:
        print("\n".join(report.lines()), file=sys.stderr)
        print(f"ERROR {exc}", file=sys.stderr)
        return 2
    except (srr.SyncError, GitHubError, ValueError, OSError, KeyError) as exc:
        print("\n".join(report.lines()), file=sys.stderr)
        print(f"ERROR {exc}", file=sys.stderr)
        return 1
    print("\n".join(report.lines()), file=sys.stderr)
    print(f"result={result}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
