from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


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


if __name__ == "__main__":
    unittest.main()
