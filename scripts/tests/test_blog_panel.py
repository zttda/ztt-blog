from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch


SCRIPTS_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS_DIR))

import blog_panel  # noqa: E402


class FrontmatterTests(unittest.TestCase):
    def test_single_quotes_are_unescaped(self) -> None:
        source = "---\ntitle: 'Bob''s note'\ndraft: true\n---\n"

        parsed = blog_panel.parse_frontmatter_text(source)

        self.assertEqual(parsed["title"], "Bob's note")
        self.assertTrue(parsed["draft"])

    def test_commas_inside_quoted_tags_are_preserved(self) -> None:
        source = "---\ntags: ['C#, .NET', 'Astro']\n---\n"

        parsed = blog_panel.parse_frontmatter_text(source)

        self.assertEqual(parsed["tags"], ["C#, .NET", "Astro"])

    def test_unknown_frontmatter_blocks_are_preserved(self) -> None:
        source = """---
title: 'Known title'
socialImage: '/social.webp'
authors:
  - ztt
draft: true
---
Body
"""

        preserved = blog_panel.preserved_frontmatter_lines(source)

        self.assertEqual(
            preserved,
            ["socialImage: '/social.webp'", "authors:", "  - ztt"],
        )

    def test_complex_managed_yaml_is_detected_before_structured_save(self) -> None:
        source = """---
title: 'Example'
description: >-
  A folded description.
tags:
  - Astro
  - Notes
draft: true
---
"""

        fields = blog_panel.complex_managed_frontmatter_fields(source)

        self.assertEqual(fields, ["description", "tags"])

    def test_complex_yaml_with_inline_comments_is_detected(self) -> None:
        source = """---
title: 'Example'
description: >- # folded for readability
  A folded description.
tags: # one per line
  - Astro
draft: true
---
"""

        fields = blog_panel.complex_managed_frontmatter_fields(source)

        self.assertEqual(fields, ["description", "tags"])

    def test_draft_update_preserves_inline_comment(self) -> None:
        source = "---\ndraft: true # keep private until reviewed\n---\n"

        updated = blog_panel.set_draft_frontmatter(source, False)

        self.assertIn("draft: false # keep private until reviewed", updated)
        self.assertFalse(blog_panel.parse_frontmatter_text(updated)["draft"])

    def test_draft_update_accepts_yaml_boolean_case_variants(self) -> None:
        source = "---\ndraft: True # YAML boolean\n---\n"

        updated = blog_panel.set_draft_frontmatter(source, False)

        self.assertEqual(updated.count("draft:"), 1)
        self.assertIn("draft: false # YAML boolean", updated)

    def test_draft_update_does_not_touch_body_examples(self) -> None:
        source = """---
title: 'Example'
---

```yaml
draft: true
```
"""

        updated = blog_panel.set_draft_frontmatter(source, False)

        self.assertIn("---\ndraft: false\ntitle: 'Example'\n---", updated)
        self.assertIn("```yaml\ndraft: true\n```", updated)

    def test_draft_update_supports_crlf_frontmatter(self) -> None:
        source = "---\r\ntitle: 'Example'\r\n---\r\nBody\r\n"

        updated = blog_panel.set_draft_frontmatter(source, False)

        self.assertEqual(updated.count("---"), 2)
        self.assertTrue(updated.startswith("---\r\ndraft: false\r\ntitle: 'Example'\r\n---"))

    def test_structured_save_refuses_complex_yaml_without_changing_file(self) -> None:
        source = """---
title: 'Example'
description: >-
  Folded text
tags:
  - Astro
draft: true
pubDate: '2026-07-10'
---
Body
"""
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "post.md"
            path.write_text(source, encoding="utf-8")
            with patch.object(blog_panel, "post_path_from_rel", return_value=path):
                result = blog_panel.save_post({"file": "post.md"})

            self.assertEqual(result.code, 1)
            self.assertEqual(path.read_text(encoding="utf-8"), source)

    def test_structured_save_preserves_unknown_simple_fields(self) -> None:
        source = """---
title: 'Old title'
description: 'Old description'
tags: ['Astro']
draft: true
pubDate: '2026-07-10'
socialImage: '/social.webp'
---
Old body
"""
        form = {
            "file": "post.md",
            "title": "New title",
            "description": "New description",
            "tags": "Astro, Notes",
            "draft": "on",
            "pubDate": "2026-07-10",
            "body": "New body",
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            path = root / "post.md"
            path.write_text(source, encoding="utf-8")
            with (
                patch.object(blog_panel, "ROOT", root),
                patch.object(blog_panel, "post_path_from_rel", return_value=path),
            ):
                result = blog_panel.save_post(form)

            saved = path.read_text(encoding="utf-8")
            self.assertEqual(result.code, 0)
            self.assertIn("title: 'New title'", saved)
            self.assertIn("socialImage: '/social.webp'", saved)
            self.assertTrue(saved.endswith("New body\n"))


class RequestSecurityTests(unittest.TestCase):
    def test_panel_host_must_be_loopback_and_match_port(self) -> None:
        self.assertTrue(blog_panel.is_trusted_host("127.0.0.1:8765", 8765))
        self.assertTrue(blog_panel.is_trusted_host("localhost:8765", 8765))
        self.assertFalse(blog_panel.is_trusted_host("example.com:8765", 8765))
        self.assertFalse(blog_panel.is_trusted_host("127.0.0.1:4321", 8765))

    def test_cross_origin_request_is_rejected(self) -> None:
        host = "127.0.0.1:8765"
        self.assertTrue(blog_panel.is_trusted_origin("http://127.0.0.1:8765", host))
        self.assertFalse(blog_panel.is_trusted_origin("https://example.com", host))

    def test_csrf_field_is_added_only_to_post_forms(self) -> None:
        html = '<form method="get"></form><form class="x" method="post"></form>'

        secured = blog_panel.inject_csrf_fields(html)

        self.assertEqual(secured.count('name="_csrf"'), 1)
        self.assertIn(blog_panel.CSRF_TOKEN, secured)

    def test_multipart_parser_preserves_file_trailing_newline(self) -> None:
        body = (
            b"--test\r\n"
            b'Content-Disposition: form-data; name="images"; filename="note.png"\r\n'
            b"Content-Type: image/png\r\n\r\n"
            b"payload\r\n\r\n"
            b"--test--\r\n"
        )

        _, files = blog_panel.parse_multipart_multi(body, "multipart/form-data; boundary=test")

        self.assertEqual(files["images"][0].data, b"payload\r\n")

    def test_existing_panel_probe_requires_the_control_panel_marker(self) -> None:
        response = Mock()
        response.status = 200
        response.read.return_value = "<h1>博客控制面板</h1>".encode("utf-8")
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)

        with patch.object(blog_panel.urllib.request, "urlopen", return_value=response):
            self.assertTrue(blog_panel.is_panel_ready(8765))

        response.read.return_value = b"<h1>Another local service</h1>"
        with patch.object(blog_panel.urllib.request, "urlopen", return_value=response):
            self.assertFalse(blog_panel.is_panel_ready(8765))


class ThemeSettingsTests(unittest.TestCase):
    def test_invalid_saved_visual_style_falls_back_to_default(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            theme_file = Path(temp_dir) / "theme.json"
            theme_file.write_text('{"visualStyle": "unknown"}', encoding="utf-8")
            with patch.object(blog_panel, "THEME_FILE", theme_file):
                theme = blog_panel.read_theme()

        self.assertEqual(theme["visualStyle"], "crayon-party")

    def test_non_string_visual_style_falls_back_to_default(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            theme_file = Path(temp_dir) / "theme.json"
            theme_file.write_text('{"visualStyle": []}', encoding="utf-8")
            with patch.object(blog_panel, "THEME_FILE", theme_file):
                theme = blog_panel.read_theme()

        self.assertEqual(theme["visualStyle"], "crayon-party")

    def test_visual_style_can_be_saved_from_the_local_panel(self) -> None:
        with (
            patch.object(blog_panel, "read_theme", return_value=blog_panel.DEFAULT_THEME.copy()),
            patch.object(blog_panel, "write_theme") as write_theme,
        ):
            result = blog_panel.update_theme({"visualStyle": "paper"})

        self.assertEqual(result.code, 0)
        self.assertEqual(write_theme.call_args.args[0]["visualStyle"], "paper")

    def test_unknown_visual_style_is_rejected_without_writing(self) -> None:
        with (
            patch.object(blog_panel, "read_theme", return_value=blog_panel.DEFAULT_THEME.copy()),
            patch.object(blog_panel, "write_theme") as write_theme,
        ):
            result = blog_panel.update_theme({"visualStyle": "not-a-theme"})

        self.assertEqual(result.code, 1)
        write_theme.assert_not_called()


class PanelSingleInstanceTests(unittest.TestCase):
    def test_existing_panel_is_reused_and_opened(self) -> None:
        with (
            patch.object(blog_panel, "BlogPanelServer", side_effect=OSError("in use")),
            patch.object(blog_panel, "is_panel_ready", return_value=True),
            patch.object(blog_panel.webbrowser, "open") as open_browser,
        ):
            result = blog_panel.serve_panel(8765)

        self.assertEqual(result, 0)
        open_browser.assert_called_once_with("http://127.0.0.1:8765/")

    def test_no_browser_reuses_existing_panel_without_opening_it(self) -> None:
        with (
            patch.object(blog_panel, "BlogPanelServer", side_effect=OSError("in use")),
            patch.object(blog_panel, "is_panel_ready", return_value=True),
            patch.object(blog_panel.webbrowser, "open") as open_browser,
        ):
            result = blog_panel.serve_panel(8765, no_browser=True)

        self.assertEqual(result, 0)
        open_browser.assert_not_called()

    def test_unrelated_service_blocks_start_without_opening_browser(self) -> None:
        with (
            patch.object(blog_panel, "BlogPanelServer", side_effect=OSError("in use")),
            patch.object(blog_panel, "is_panel_ready", return_value=False),
            patch.object(blog_panel.webbrowser, "open") as open_browser,
        ):
            result = blog_panel.serve_panel(8765)

        self.assertEqual(result, 1)
        open_browser.assert_not_called()

    @unittest.skipUnless(blog_panel.os.name == "nt", "Windows socket behavior")
    def test_windows_server_refuses_a_second_listener_on_the_same_port(self) -> None:
        primary = blog_panel.BlogPanelServer(
            (blog_panel.PANEL_HOST, 0),
            blog_panel.BlogPanelHandler,
        )
        try:
            with self.assertRaises(OSError):
                blog_panel.BlogPanelServer(
                    (blog_panel.PANEL_HOST, primary.server_port),
                    blog_panel.BlogPanelHandler,
                )
        finally:
            primary.server_close()


class FakePreviewProcess:
    def __init__(self, return_code: int | None = None) -> None:
        self.pid = 12345
        self.stdout = iter(())
        self.return_code = return_code

    def poll(self) -> int | None:
        return self.return_code

    def wait(self, timeout: float | None = None) -> int:
        self.return_code = 0
        return 0


class PreviewProcessTests(unittest.TestCase):
    def setUp(self) -> None:
        self.original_process = blog_panel.preview_process
        self.original_port = blog_panel.active_preview_port
        blog_panel.preview_process = None
        blog_panel.active_preview_port = blog_panel.PREVIEW_PORT
        blog_panel.preview_output.clear()

    def tearDown(self) -> None:
        blog_panel.preview_process = self.original_process
        blog_panel.active_preview_port = self.original_port
        blog_panel.preview_output.clear()

    def test_preview_ready_requires_http_success(self) -> None:
        response = Mock()
        response.status = 200
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)

        with patch.object(blog_panel.urllib.request, "urlopen", return_value=response):
            self.assertTrue(blog_panel.is_preview_ready("127.0.0.1", 4321))

        http_error = blog_panel.urllib.error.HTTPError(
            "http://127.0.0.1:4321/",
            500,
            "Internal Server Error",
            {},
            None,
        )
        with patch.object(blog_panel.urllib.request, "urlopen", side_effect=http_error):
            self.assertFalse(blog_panel.is_preview_ready("127.0.0.1", 4321))

    def test_available_preview_port_skips_an_occupied_port(self) -> None:
        with patch.object(blog_panel, "is_port_open", side_effect=lambda _host, port: port == 4321):
            port = blog_panel.find_available_preview_port("127.0.0.1", 4321, attempts=3)

        self.assertEqual(port, 4322)

    def test_preview_status_does_not_trust_an_external_service(self) -> None:
        with patch.object(blog_panel, "is_preview_ready", return_value=True) as ready:
            self.assertFalse(blog_panel.is_owned_preview_ready())

        ready.assert_not_called()

        blog_panel.preview_process = FakePreviewProcess()
        with patch.object(blog_panel, "is_preview_ready", return_value=True):
            self.assertTrue(blog_panel.is_owned_preview_ready())

    def test_preview_state_keeps_one_process_and_port_snapshot(self) -> None:
        process = Mock()

        def finish_while_rendering() -> None:
            blog_panel.preview_process = None
            blog_panel.active_preview_port = 4323
            return None

        process.poll.side_effect = finish_while_rendering
        blog_panel.preview_process = process
        blog_panel.active_preview_port = 4322
        with patch.object(blog_panel, "is_preview_ready", return_value=True) as ready:
            url, running = blog_panel.get_preview_state()

        self.assertTrue(running)
        self.assertEqual(url, "http://127.0.0.1:4322/")
        ready.assert_called_once_with("127.0.0.1", 4322)

    def test_preview_port_is_read_from_the_astro_local_url(self) -> None:
        blog_panel.preview_output.extend(
            [
                "Port 4321 is in use, trying another one...",
                "┃ Local    http://127.0.0.1:4322/",
            ]
        )

        self.assertEqual(blog_panel.preview_port_from_output(), 4322)

    def test_start_preview_uses_next_free_port_and_waits_until_ready(self) -> None:
        process = FakePreviewProcess()
        blog_panel.preview_output.append("┃ Local    http://127.0.0.1:4322/")
        with (
            patch.object(blog_panel.shutil, "which", return_value=r"C:\Program Files\nodejs\npm.cmd"),
            patch.object(blog_panel, "node_modules_ready", return_value=True),
            patch.object(blog_panel, "find_available_preview_port", return_value=4322),
            patch.object(blog_panel, "launch_preview_process", return_value=process) as launch,
            patch.object(blog_panel, "is_preview_ready", return_value=True),
        ):
            result = blog_panel.start_preview()

        self.assertEqual(result.code, 0)
        self.assertIn("4322", result.output)
        self.assertEqual(blog_panel.active_preview_port, 4322)
        launch.assert_called_once_with(r"C:\Program Files\nodejs\npm.cmd", 4322)

    def test_start_preview_follows_astro_when_the_port_is_taken_during_bind(self) -> None:
        process = FakePreviewProcess()
        blog_panel.preview_output.extend(
            [
                "Port 4321 is in use, trying another one...",
                "┃ Local    http://127.0.0.1:4322/",
            ]
        )
        with (
            patch.object(blog_panel.shutil, "which", return_value="npm.cmd"),
            patch.object(blog_panel, "node_modules_ready", return_value=True),
            patch.object(blog_panel, "find_available_preview_port", return_value=4321),
            patch.object(blog_panel, "launch_preview_process", return_value=process),
            patch.object(
                blog_panel,
                "is_preview_ready",
                side_effect=lambda _host, port: port == 4322,
            ) as ready,
        ):
            result = blog_panel.start_preview()

        self.assertEqual(result.code, 0)
        self.assertEqual(blog_panel.active_preview_port, 4322)
        self.assertIn("自动改用 4322", result.output)
        ready.assert_called_once_with("127.0.0.1", 4322)

    def test_start_preview_reports_an_early_process_exit(self) -> None:
        process = FakePreviewProcess(return_code=7)
        with (
            patch.object(blog_panel.shutil, "which", return_value="npm.cmd"),
            patch.object(blog_panel, "node_modules_ready", return_value=True),
            patch.object(blog_panel, "find_available_preview_port", return_value=4321),
            patch.object(blog_panel, "launch_preview_process", return_value=process),
            patch.object(blog_panel, "is_preview_ready", return_value=False),
        ):
            result = blog_panel.start_preview()

        self.assertEqual(result.code, 1)
        self.assertIn("退出码 7", result.output)
        self.assertIsNone(blog_panel.preview_process)

    def test_start_preview_cleans_up_after_a_readiness_timeout(self) -> None:
        process = FakePreviewProcess()
        with (
            patch.object(blog_panel.shutil, "which", return_value="npm.cmd"),
            patch.object(blog_panel, "node_modules_ready", return_value=True),
            patch.object(blog_panel, "find_available_preview_port", return_value=4321),
            patch.object(blog_panel, "launch_preview_process", return_value=process),
            patch.object(blog_panel, "is_preview_ready", return_value=False),
            patch.object(blog_panel, "PREVIEW_START_TIMEOUT_SECONDS", 0),
            patch.object(blog_panel, "terminate_preview_process") as terminate,
        ):
            result = blog_panel.start_preview()

        self.assertEqual(result.code, 1)
        self.assertIn("预览仍未就绪", result.output)
        terminate.assert_called_once_with(process)
        self.assertIsNone(blog_panel.preview_process)

    def test_windows_termination_kills_the_process_tree(self) -> None:
        process = FakePreviewProcess()
        completed = Mock(returncode=0)
        with (
            patch.object(blog_panel.os, "name", "nt"),
            patch.object(blog_panel.subprocess, "run", return_value=completed) as run,
        ):
            blog_panel.terminate_preview_process(process)

        self.assertEqual(process.return_code, 0)
        self.assertEqual(run.call_args.args[0], ["taskkill", "/PID", "12345", "/T", "/F"])

    def test_stop_preview_terminates_the_whole_owned_process_tree(self) -> None:
        process = FakePreviewProcess()
        blog_panel.preview_process = process
        blog_panel.active_preview_port = 4322

        with (
            patch.object(blog_panel, "terminate_preview_process") as terminate,
            patch.object(blog_panel, "wait_for_port_closed", return_value=True),
        ):
            result = blog_panel.stop_preview()

        terminate.assert_called_once_with(process)
        self.assertEqual(result.code, 0)
        self.assertIsNone(blog_panel.preview_process)
        self.assertEqual(blog_panel.active_preview_port, blog_panel.PREVIEW_PORT)

    def test_stop_preview_reports_a_port_that_remains_open(self) -> None:
        blog_panel.preview_process = FakePreviewProcess()

        with (
            patch.object(blog_panel, "terminate_preview_process"),
            patch.object(blog_panel, "wait_for_port_closed", return_value=False),
        ):
            result = blog_panel.stop_preview()

        self.assertEqual(result.code, 1)
        self.assertIn("仍被占用", result.output)


if __name__ == "__main__":
    unittest.main()
