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
        self.assertEqual(button.get_tooltip_text(), "Packages")
        window.destroy()

    def test_compact_help_popover_accepts_markup(self):
        button = HelpPopoverButton(
            "Filesystem", "<b>ext4</b> is recommended.",
            compact=True, markup=True)
        self.assertIsNotNone(button.help_popover)


if __name__ == "__main__":
    unittest.main()
