import os
import tempfile
import unittest
from unittest import mock

from minios_gui import style


class StyleTests(unittest.TestCase):
    def test_apply_css_preserves_provider_order(self):
        with tempfile.TemporaryDirectory() as directory:
            base = os.path.join(directory, "base.css")
            override = os.path.join(directory, "override.css")
            for path in (base, override):
                with open(path, "w", encoding="utf-8") as handle:
                    handle.write("label { opacity: 1; }\n")

            providers = [mock.Mock(), mock.Mock()]
            with mock.patch.object(
                    style.Gdk.Screen, "get_default", return_value=object()), \
                    mock.patch.object(
                        style.Gtk, "CssProvider", side_effect=providers), \
                    mock.patch.object(
                        style.Gtk.StyleContext,
                        "add_provider_for_screen") as add_provider:
                loaded = style.apply_css(base, "/missing.css", override)

            self.assertEqual(loaded, (base, override))
            providers[0].load_from_path.assert_called_once_with(base)
            providers[1].load_from_path.assert_called_once_with(override)
            self.assertEqual(add_provider.call_count, 2)

    def test_resolve_icon_uses_first_available_candidate(self):
        theme = mock.Mock()
        theme.has_icon.side_effect = lambda name: name == "available-symbolic"
        with mock.patch.object(
                style.Gtk.IconTheme, "get_default", return_value=theme):
            result = style.resolve_icon(
                ("missing-symbolic", "available-symbolic"), fallback="fallback")
        self.assertEqual(result, "available-symbolic")

    def test_resolve_icon_returns_fallback(self):
        theme = mock.Mock()
        theme.has_icon.return_value = False
        with mock.patch.object(
                style.Gtk.IconTheme, "get_default", return_value=theme):
            result = style.resolve_icon("missing", fallback="fallback")
        self.assertEqual(result, "fallback")


if __name__ == "__main__":
    unittest.main()
