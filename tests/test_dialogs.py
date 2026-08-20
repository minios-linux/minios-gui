import unittest
from unittest import mock

from gi.repository import Gtk

from minios_gui import dialogs


class DialogTests(unittest.TestCase):
    def test_destructive_confirmation_uses_safe_default(self):
        dialog = mock.Mock()
        confirm = mock.Mock()
        dialog.add_button.side_effect = [mock.Mock(), confirm]
        dialog.run.return_value = Gtk.ResponseType.OK

        with mock.patch.object(dialogs.Gtk, "MessageDialog", return_value=dialog):
            accepted = dialogs.ask_confirmation(
                None,
                "Delete item?",
                "This cannot be undone.",
                destructive=True,
                confirm_label="Delete",
                cancel_label="Keep",
            )

        self.assertTrue(accepted)
        dialog.set_default_response.assert_called_once_with(
            Gtk.ResponseType.CANCEL)
        confirm.get_style_context.return_value.add_class.assert_called_once_with(
            "destructive-action")
        dialog.destroy.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
