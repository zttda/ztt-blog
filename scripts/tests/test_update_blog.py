from __future__ import annotations

import subprocess
import unittest
from unittest.mock import patch

from scripts.update_blog import (
    MAX_FILE_BYTES,
    ROOT,
    dangerous_path_reason,
    find_publish_blockers,
    get_ahead_file_versions,
    parse_commit_count,
    parse_nul_paths,
    plan_publish,
    unique_paths,
)


class DangerousPathTests(unittest.TestCase):
    def test_blocks_temporary_and_generated_review_directories(self) -> None:
        blocked = [
            ".tmp-edge-screens/Default/History",
            "work/.TMP-preview/result.png",
            "site/design-previews/home.png",
            "site/image-candidates/hero.webp",
        ]

        for path in blocked:
            with self.subTest(path=path):
                self.assertIsNotNone(dangerous_path_reason(path))

    def test_blocks_common_secret_files(self) -> None:
        blocked = [
            ".env",
            "site/.env.production",
            "scripts/github_token.txt",
            "credentials.json",
            "keys/id_rsa",
            "keys/id_ed25519.pub.pem",
            "certificate/private.key",
            ".npmrc",
        ]

        for path in blocked:
            with self.subTest(path=path):
                self.assertIsNotNone(dangerous_path_reason(path))

    def test_allows_normal_content_and_safe_env_examples(self) -> None:
        allowed = [
            "site/src/content/blog/example.md",
            "site/public/uploads/posts/example.webp",
            ".env.example",
            "docs/token-usage.md",
        ]

        for path in allowed:
            with self.subTest(path=path):
                self.assertIsNone(dangerous_path_reason(path))


class PublishBlockerTests(unittest.TestCase):
    def test_blocks_files_over_limit_but_allows_exact_limit(self) -> None:
        blockers = find_publish_blockers(
            [
                ("site/public/exact.bin", MAX_FILE_BYTES),
                ("site/public/large.bin", MAX_FILE_BYTES + 1),
            ]
        )

        self.assertEqual(len(blockers), 1)
        self.assertIn("large.bin", blockers[0])

    def test_reports_both_path_and_size_problems(self) -> None:
        blockers = find_publish_blockers(
            [(".tmp-render/large.png", MAX_FILE_BYTES + 1)]
        )

        self.assertEqual(len(blockers), 2)

    def test_scans_every_file_version_in_unpushed_commits(self) -> None:
        def fake_run(command: list[str], check: bool = True) -> subprocess.CompletedProcess[str]:
            if command[1] == "rev-list":
                output = "commit-a\ncommit-b\n"
            elif command[1] == "diff-tree" and command[-1] == "commit-a":
                output = "secrets.json\0site/large.bin\0"
            elif command[1] == "diff-tree":
                output = "site/large.bin\0"
            elif command[1] == "cat-file" and command[-1].startswith("commit-a:site/large.bin"):
                output = str(MAX_FILE_BYTES + 1)
            else:
                output = "10"
            return subprocess.CompletedProcess(command, 0, output, "")

        with patch("scripts.update_blog.run", side_effect=fake_run):
            versions = get_ahead_file_versions()

        blockers = find_publish_blockers(versions)
        self.assertTrue(any("secrets.json" in blocker for blocker in blockers))
        self.assertTrue(any("large.bin" in blocker for blocker in blockers))


class PublishPlanTests(unittest.TestCase):
    def test_pushes_unpushed_commits_when_workspace_is_clean(self) -> None:
        self.assertEqual(plan_publish(False, 2, False), (False, True))

    def test_no_push_keeps_local_commits_local(self) -> None:
        self.assertEqual(plan_publish(False, 2, True), (False, False))

    def test_changes_are_committed_and_pushed(self) -> None:
        self.assertEqual(plan_publish(True, 0, False), (True, True))


class ParsingTests(unittest.TestCase):
    def test_parses_and_deduplicates_nul_paths(self) -> None:
        parsed = parse_nul_paths("./site/a.md\0site\\b.md\0")

        self.assertEqual(unique_paths([*parsed, "site/a.md"]), ["site/a.md", "site/b.md"])

    def test_commit_count_is_nonnegative_and_tolerates_bad_output(self) -> None:
        self.assertEqual(parse_commit_count("3\n"), 3)
        self.assertEqual(parse_commit_count("-1"), 0)
        self.assertEqual(parse_commit_count("not-a-number"), 0)


class RepositoryPolicyTests(unittest.TestCase):
    def test_tracked_files_follow_publish_policy(self) -> None:
        result = subprocess.run(
            ["git", "ls-files", "-z"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        paths = parse_nul_paths(result.stdout)
        files = []
        for path in paths:
            candidate = ROOT / path
            if candidate.is_file():
                files.append((path, candidate.stat().st_size))

        self.assertEqual(find_publish_blockers(files), [])


if __name__ == "__main__":
    unittest.main()
