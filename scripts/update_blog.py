#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from collections.abc import Iterable
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SITE_DIR = ROOT / "site"
DEFAULT_MESSAGE = "update blog"
MAX_FILE_BYTES = 20 * 1024 * 1024
SAFE_ENV_EXAMPLES = {".env.example", ".env.sample", ".env.template"}
SENSITIVE_FILENAMES = {
    ".netrc",
    ".npmrc",
    ".pypirc",
    "credentials.json",
    "github_token.txt",
    "secret.json",
    "secrets.json",
    "service-account.json",
    "service_account.json",
}
SENSITIVE_SUFFIXES = {".kdbx", ".key", ".p12", ".pfx", ".pem"}


def configure_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure:
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass


configure_stdio()


def run(cmd: list[str], check: bool = True) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    return subprocess.run(
        cmd,
        cwd=str(ROOT),
        check=check,
        text=True,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        env=env,
    )


def print_output(result: subprocess.CompletedProcess[str]) -> None:
    if result.stdout.strip():
        print(result.stdout.strip())
    if result.stderr.strip():
        print(result.stderr.strip())


def npm_command() -> str:
    return "npm.cmd" if sys.platform.startswith("win") else "npm"


def normalize_git_path(path: str) -> str:
    normalized = path.replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    return normalized.strip("/")


def parse_nul_paths(output: str) -> list[str]:
    return [normalize_git_path(path) for path in output.split("\0") if path]


def unique_paths(paths: Iterable[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for path in paths:
        normalized = normalize_git_path(path)
        if normalized and normalized not in seen:
            result.append(normalized)
            seen.add(normalized)
    return result


def dangerous_path_reason(path: str) -> str | None:
    normalized = normalize_git_path(path).casefold()
    parts = normalized.split("/")
    name = parts[-1]

    if any(part.startswith(".tmp-") for part in parts):
        return "temporary path matching .tmp-*"

    for directory in ("site/design-previews", "site/image-candidates"):
        if normalized == directory or normalized.startswith(directory + "/"):
            return f"generated review directory {directory}"

    if name == ".env" or (name.startswith(".env.") and name not in SAFE_ENV_EXAMPLES):
        return "environment file that may contain secrets"
    if name in SENSITIVE_FILENAMES:
        return "file name commonly used for credentials"
    if name.startswith("id_rsa") or name.startswith("id_ed25519"):
        return "SSH private key"
    if Path(name).suffix in SENSITIVE_SUFFIXES:
        return "private key, certificate, or password vault"
    return None


def find_publish_blockers(
    files: Iterable[tuple[str, int]], max_file_bytes: int = MAX_FILE_BYTES
) -> list[str]:
    blockers: list[str] = []
    for path, size in files:
        reason = dangerous_path_reason(path)
        if reason:
            blockers.append(f"{path}: {reason}")
        if size > max_file_bytes:
            size_mib = size / (1024 * 1024)
            limit_mib = max_file_bytes / (1024 * 1024)
            blockers.append(f"{path}: {size_mib:.1f} MiB exceeds the {limit_mib:.0f} MiB limit")
    return blockers


def plan_publish(has_changes: bool, ahead_count: int, no_push: bool) -> tuple[bool, bool]:
    should_commit = has_changes
    should_push = not no_push and (has_changes or ahead_count > 0)
    return should_commit, should_push


def parse_commit_count(output: str) -> int:
    try:
        return max(0, int(output.strip()))
    except ValueError:
        return 0


def get_changed_paths() -> list[str]:
    # Deletions are safe to publish even when an ignored local archive copy remains.
    tracked = run(["git", "diff", "--name-only", "--diff-filter=ACMRTUXB", "-z", "HEAD", "--"])
    untracked = run(["git", "ls-files", "--others", "--exclude-standard", "-z"])
    return unique_paths([*parse_nul_paths(tracked.stdout), *parse_nul_paths(untracked.stdout)])


def get_existing_file_sizes(paths: Iterable[str]) -> list[tuple[str, int]]:
    files: list[tuple[str, int]] = []
    for path in paths:
        candidate = ROOT / path
        try:
            metadata = candidate.lstat()
        except FileNotFoundError:
            # Deleting a dangerous or large file must remain possible.
            continue
        if candidate.is_dir():
            continue
        files.append((path, metadata.st_size))
    return files


def get_ahead_count() -> int | None:
    result = run(["git", "rev-list", "--count", "@{upstream}..HEAD"], check=False)
    if result.returncode != 0:
        return None
    return parse_commit_count(result.stdout)


def get_ahead_file_versions() -> list[tuple[str, int]]:
    commits = run(["git", "rev-list", "@{upstream}..HEAD"], check=False)
    if commits.returncode != 0:
        return []

    largest_versions: dict[str, int] = {}
    for commit in commits.stdout.splitlines():
        commit = commit.strip()
        if not commit:
            continue
        changed = run(
            [
                "git",
                "diff-tree",
                "--root",
                "-m",
                "--no-commit-id",
                "--name-only",
                "--diff-filter=ACMRTUXB",
                "-r",
                "-z",
                commit,
            ]
        )
        for path in parse_nul_paths(changed.stdout):
            size_result = run(["git", "cat-file", "-s", f"{commit}:{path}"], check=False)
            size = parse_commit_count(size_result.stdout) if size_result.returncode == 0 else 0
            largest_versions[path] = max(largest_versions.get(path, 0), size)
    return list(largest_versions.items())


def build_site() -> None:
    env = dict(os.environ)
    env["ASTRO_TELEMETRY_DISABLED"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    result = subprocess.run(
        [npm_command(), "run", "build"],
        cwd=str(SITE_DIR),
        check=True,
        text=True,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        env=env,
    )
    print_output(result)


def main() -> int:
    parser = argparse.ArgumentParser(description="Commit and push blog updates to GitHub.")
    parser.add_argument("-m", "--message", default=DEFAULT_MESSAGE, help="Commit message.")
    parser.add_argument("--no-push", action="store_true", help="Commit only, do not push.")
    parser.add_argument("--skip-build", action="store_true", help="Skip npm build before committing.")
    args = parser.parse_args()

    print(f"Project root: {ROOT}")

    status = run(["git", "status", "--short"])
    has_changes = bool(status.stdout.strip())
    detected_ahead = get_ahead_count()
    ahead_count = detected_ahead or 0

    if ahead_count:
        ahead_blockers = find_publish_blockers(get_ahead_file_versions())
        if ahead_blockers:
            print("Push blocked. Unpushed commits contain unsafe files:", file=sys.stderr)
            for blocker in ahead_blockers:
                print(f"- {blocker}", file=sys.stderr)
            print("Remove the files from the unpushed Git history before retrying.", file=sys.stderr)
            return 2

    if has_changes:
        print("Changes to publish:")
        print(status.stdout.rstrip())
        blockers = find_publish_blockers(get_existing_file_sizes(get_changed_paths()))
        if blockers:
            print("Publish blocked. Remove or relocate these files:", file=sys.stderr)
            for blocker in blockers:
                print(f"- {blocker}", file=sys.stderr)
            return 2
    else:
        print("No changes to commit.")
        if detected_ahead is None:
            print("No upstream branch is configured; cannot check for unpushed commits.")
            return 0
        if ahead_count:
            print(f"Found {ahead_count} local commit(s) waiting to be pushed.")

    should_commit, should_push = plan_publish(has_changes, ahead_count, args.no_push)
    if not should_commit and not should_push:
        if ahead_count and args.no_push:
            print("Push skipped by --no-push.")
        else:
            print("Nothing to publish.")
        return 0

    if not args.skip_build:
        print("Running build check...")
        build_site()

    if should_commit:
        print("Staging changes...")
        print_output(run(["git", "add", "."]))

        print("Creating commit...")
        print_output(run(["git", "commit", "-m", args.message]))

    if not should_push:
        print("Commit created. Push skipped.")
        return 0

    print("Pushing to the configured upstream...")
    print_output(run(["git", "push"]))
    print("Update complete.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except subprocess.CalledProcessError as exc:
        print(f"Command failed: {' '.join(exc.cmd)}", file=sys.stderr)
        if exc.stdout:
            print(exc.stdout.strip())
        if exc.stderr:
            print(exc.stderr.strip(), file=sys.stderr)
        raise SystemExit(exc.returncode)
