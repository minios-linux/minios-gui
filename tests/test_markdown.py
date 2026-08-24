import tempfile
import unittest
from pathlib import Path
from unittest import mock

from minios_gui.markdown import MarkdownTextView, load_localized_markdown, parse_markdown
from minios_gui.mermaid import MermaidDiagram, MermaidParseError, parse_mermaid_flowchart


class MarkdownTests(unittest.TestCase):
    def test_parser_builds_native_nodes_without_html(self):
        nodes = parse_markdown(
            "## Storage\n\nUse **SquashFS** and `perchmode=squashfs`.\n\n"
            "- Resume a session\n- Keep free space\n")

        self.assertEqual(nodes[0][0:2], ("block", "heading2"))
        self.assertEqual(nodes[1][0:2], ("block", "paragraph"))
        self.assertTrue(any(node[0] == "list" for node in nodes))
        self.assertNotIn("<h2>", repr(nodes))

    def test_nested_lists_start_on_their_own_indented_lines(self):
        view = MarkdownTextView(
            "1. one\n2. two\n   - nested a\n   - nested b\n")
        buffer_ = view.get_buffer()
        text = buffer_.get_text(
            buffer_.get_start_iter(), buffer_.get_end_iter(), True)
        self.assertIn("1. one\n2. two\n  - nested a\n  - nested b", text)
        self.assertNotIn("two  - nested", text)

    def test_parser_normalizes_code_links_quotes_and_tables(self):
        nodes = parse_markdown(
            "Text `code` and [link](https://minios.dev).\n\n"
            "> quoted\n\n| A | B |\n| - | - |\n| x | y |\n")

        rendered = repr(nodes)
        self.assertIn("'code'", rendered)
        self.assertIn("https://minios.dev", rendered)
        self.assertIn("'quote'", rendered)
        self.assertIn("'table'", rendered)

    def test_fenced_code_without_language_renders_safely(self):
        nodes = parse_markdown("```\necho hello\n```\n")
        self.assertEqual(nodes[0][0], "code_block")
        view = MarkdownTextView("```\necho hello\n```\n")
        text = view.get_buffer().get_text(
            view.get_buffer().get_start_iter(),
            view.get_buffer().get_end_iter(), True)
        self.assertIn("echo hello", text)

    def test_safe_inline_html_is_converted_to_native_formatting(self):
        nodes = parse_markdown(
            "A<br>B <kbd>Esc</kbd> <strong>bold</strong> <em>italic</em>")
        rendered = repr(nodes)
        self.assertIn("'code'", rendered)
        self.assertIn("'strong'", rendered)
        self.assertIn("'emphasis'", rendered)
        view = MarkdownTextView(
            "A<br>B <kbd>Esc</kbd> <strong>bold</strong> <em>italic</em>")
        buffer_ = view.get_buffer()
        text = buffer_.get_text(
            buffer_.get_start_iter(), buffer_.get_end_iter(), True)
        self.assertIn("A\nB Esc bold italic", text)

    def test_headings_expose_unicode_anchors_and_ascii_aliases(self):
        view = MarkdownTextView("# Café Storage\n\n## Details\n")
        self.assertEqual(
            view.get_headings(),
            [(1, "Café Storage", "café-storage"), (2, "Details", "details")])
        self.assertTrue(view.scroll_to_anchor("#café-storage"))
        self.assertTrue(view.scroll_to_anchor("cafe-storage"))
        self.assertFalse(view.scroll_to_anchor("missing"))

    def test_internal_links_require_opt_in_and_use_callback(self):
        seen = []
        plain = MarkdownTextView("[Local](./page.md#part)")
        self.assertIsNone(plain._safe_uri("./page.md#part"))
        view = MarkdownTextView(
            "[Local](./page.md#part)",
            allow_internal_links=True,
            link_handler=lambda uri: seen.append(uri) or True)
        self.assertEqual(view._safe_uri("./page.md#part"), "./page.md#part")
        self.assertTrue(view._activate_uri("./page.md#part"))
        self.assertEqual(seen, ["./page.md#part"])
        for uri in ("file:///etc/passwd", "data:text/plain,x",
                    "javascript:alert(1)", "ftp://example.test"):
            self.assertIsNone(view._safe_uri(uri))

    def test_breaks_and_tables_render_as_readable_native_text(self):
        view = MarkdownTextView(
            "first\nsecond  \nthird\n\n| A | B |\n| - | - |\n| x | y |\n")
        buffer_ = view.get_buffer()
        text = buffer_.get_text(
            buffer_.get_start_iter(), buffer_.get_end_iter(), True)
        self.assertIn("first\nsecond\nthird", text)
        self.assertIn("A | B\nx | y", text)

    def test_raw_html_is_plain_text(self):
        nodes = parse_markdown("<script>alert('no')</script>")

        self.assertIn("script", repr(nodes))
        self.assertFalse(any(node[0] == "html" for node in nodes))

    def test_localized_loader_prefers_locale_language_then_english(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "pt-BR").mkdir()
            (root / "pt").mkdir()
            (root / "en").mkdir()
            (root / "pt-BR" / "help.md").write_text(
                "Brazil", encoding="utf-8")
            (root / "pt" / "help.md").write_text(
                "Portugal", encoding="utf-8")
            (root / "en" / "help.md").write_text(
                "English", encoding="utf-8")

            self.assertEqual(load_localized_markdown(
                root, "help.md", locale_name="pt_BR.UTF-8"), "Brazil")
            self.assertEqual(load_localized_markdown(
                root, "help.md", locale_name="pt_PT.UTF-8"), "Portugal")
            self.assertEqual(load_localized_markdown(
                root, "help.md", locale_name="de_DE.UTF-8"), "English")

    def test_localized_loader_rejects_parent_path(self):
        with self.assertRaises(ValueError):
            load_localized_markdown("/tmp/help", "../secret.md")

    def test_localized_loader_honors_gettext_language_order(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "ru").mkdir()
            (root / "en").mkdir()
            (root / "ru" / "help.md").write_text(
                "Russian", encoding="utf-8")
            (root / "en" / "help.md").write_text(
                "English", encoding="utf-8")

            with mock.patch.dict(
                    "os.environ", {"LANGUAGE": "missing:ru", "LANG": "en"},
                    clear=True):
                self.assertEqual(
                    load_localized_markdown(root, "help.md"), "Russian")


MERMAID_SAMPLE = """flowchart TD
    Start([Start]) --> Choice{Choose}
    Choice -->|Yes| Done[Finished<br/>successfully]
    Choice -.->|No| Start
    classDef success fill:#e8f5e8,stroke:#388e3c,stroke-width:2px
    class Done success
"""


class MermaidTests(unittest.TestCase):
    def test_flowchart_parser_handles_shapes_edges_classes_and_breaks(self):
        graph = parse_mermaid_flowchart(MERMAID_SAMPLE)
        self.assertEqual(graph.direction, "TD")
        self.assertEqual(len(graph.nodes), 3)
        self.assertEqual(len(graph.edges), 3)
        self.assertEqual(graph.nodes["Start"].shape, "stadium")
        self.assertEqual(graph.nodes["Choice"].shape, "diamond")
        self.assertEqual(graph.nodes["Done"].label, "Finished\nsuccessfully")
        self.assertEqual(graph.nodes["Done"].style["stroke"], "#388e3c")
        self.assertTrue(graph.edges[2].dotted)

    def test_unsupported_mermaid_is_rejected_without_execution(self):
        with self.assertRaises(MermaidParseError):
            parse_mermaid_flowchart("sequenceDiagram\nA->>B: hello")

    def test_markdown_mermaid_is_opt_in_and_falls_back_to_source(self):
        source = "```mermaid\n{}\n```".format(MERMAID_SAMPLE.rstrip())
        plain = MarkdownTextView(source)
        self.assertEqual(len(plain._embedded_widgets), 0)
        text = plain.get_buffer().get_text(
            plain.get_buffer().get_start_iter(), plain.get_buffer().get_end_iter(), True)
        self.assertIn("flowchart TD", text)

        rendered = MarkdownTextView(source, render_mermaid=True)
        self.assertEqual(len(rendered._embedded_widgets), 1)
        self.assertIsInstance(rendered._embedded_widgets[0], MermaidDiagram)

        unsupported = MarkdownTextView(
            "```mermaid\nsequenceDiagram\nA->>B: hello\n```", render_mermaid=True)
        self.assertEqual(len(unsupported._embedded_widgets), 0)
        fallback = unsupported.get_buffer().get_text(
            unsupported.get_buffer().get_start_iter(),
            unsupported.get_buffer().get_end_iter(), True)
        self.assertIn("sequenceDiagram", fallback)


if __name__ == "__main__":
    unittest.main()
