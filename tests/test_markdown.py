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

    def test_parser_normalizes_code_links_quotes_and_tables(self):
        nodes = parse_markdown(
            "Text `code` and [link](https://minios.dev).\n\n"
            "> quoted\n\n| A | B |\n| - | - |\n| x | y |\n")

        rendered = repr(nodes)
        self.assertIn("'code'", rendered)
        self.assertIn("https://minios.dev", rendered)
        self.assertIn("'quote'", rendered)
        self.assertIn("'table'", rendered)

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
