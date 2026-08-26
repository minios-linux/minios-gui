import unittest

from gi.repository import Gtk

from minios_gui import HelpPopoverButton, StatusBanner, new_header_bar


class WidgetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        initialized, _argv = Gtk.init_check([])
        if not initialized:
            raise unittest.SkipTest("GTK display is unavailable")

    def test_header_bar_uses_canonical_style(self):
        header = new_header_bar("MiniOS Test")
        self.assertEqual(header.props.title, "MiniOS Test")
        self.assertFalse(header.get_has_subtitle())
        self.assertTrue(
            header.get_style_context().has_class("minios-headerbar"))

    def test_status_banner_updates_intent_and_text(self):
        banner = StatusBanner("Initial", intent="warning")
        self.assertEqual(banner.intent, "warning")
        self.assertEqual(banner.label.get_text(), "Initial")
        self.assertTrue(
            banner.get_style_context().has_class("warning-banner"))

        banner.set_text("Ready")
        banner.set_intent("success")
        self.assertEqual(banner.label.get_text(), "Ready")
        self.assertEqual(banner.intent, "success")
        self.assertFalse(
            banner.get_style_context().has_class("warning-banner"))
        self.assertTrue(
            banner.get_style_context().has_class("success-banner"))

    def test_status_banner_rejects_unknown_intent(self):
        with self.assertRaises(ValueError):
            StatusBanner("Broken", intent="unknown")

    def test_help_popover_builds_structured_content(self):
        window = Gtk.Window()
        button = HelpPopoverButton(
            "Packages", "Build from packages.",
            (("Use this when", "APT should resolve dependencies."),),
            label="Help")
        window.add(button)
        window.show_all()
        button.clicked()
        while Gtk.events_pending():
            Gtk.main_iteration_do(False)
        self.assertIsInstance(button, Gtk.Button)
        self.assertTrue(button.help_popover.get_visible())
        minimum, _natural = button.help_popover.get_preferred_width()
        self.assertGreaterEqual(minimum, 600)
        self.assertTrue(
            button.get_style_context().has_class("minios-help-button"))
        self.assertTrue(button.help_heading.get_style_context().has_class(
            "minios-help-title"))
        self.assertEqual(button.get_tooltip_text(), "Packages")
        window.destroy()

    def test_compact_help_popover_accepts_markup(self):
        button = HelpPopoverButton(
            "Filesystem", "<b>ext4</b> is recommended.",
            compact=True, markup=True)
        self.assertIsNotNone(button.help_popover)

    def test_help_popover_accepts_compiled_document(self):
        document = {
            "product_kind": "minios-markup-document",
            "schema_version": 1,
            "nodes": [
                ["heading", 1, "filesystem", [["text", "Filesystem"]]],
                ["block", "paragraph", [
                    ["text", "Use "],
                    ["span", "strong", [["text", "ext4"]]],
                    ["text", " or "],
                    ["span", "code", [["text", "perchmode=squashfs"]]],
                    ["text", "."],
                ]],
            ],
        }
        button = HelpPopoverButton("Filesystem", compact=True, document=document)
        self.assertIsNotNone(button.help_popover)
        self.assertIsNotNone(button.document_view)
        self.assertFalse(hasattr(button, "help_heading"))
        self.assertIs(button.document_view.get_parent(), button.help_scrolled)
        tags = button.document_view.get_buffer().get_tag_table()
        self.assertGreater(tags.lookup("heading1").props.scale,
                           tags.lookup("heading2").props.scale)

    def test_document_scroll_range_ends_with_document(self):
        window = Gtk.Window()
        nodes = [["heading", 1, "help", [["text", "Help"]]]]
        nodes.extend([
            ["block", "paragraph", [["text",
                "Paragraph {} with enough text to wrap onto another line.".format(i)]]]
            for i in range(40)
        ])
        document = {
            "product_kind": "minios-markup-document",
            "schema_version": 1,
            "nodes": nodes,
        }
        button = HelpPopoverButton("Help", document=document)
        window.add(button)
        window.show_all()
        button.clicked()
        while Gtk.events_pending():
            Gtk.main_iteration_do(False)

        view = button.document_view
        end_rect = view.get_iter_location(view.get_buffer().get_end_iter())
        upper = button.help_scrolled.get_vadjustment().get_upper()
        self.assertLessEqual(upper - end_rect.y - end_rect.height, 32)
        window.destroy()


if __name__ == "__main__":
    unittest.main()
