"""Standard MiniOS message and confirmation dialogs."""

import gettext
import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk


_ = gettext.gettext


def _message_dialog(parent, message_type, message, secondary=None,
                    buttons=Gtk.ButtonsType.OK):
    dialog = Gtk.MessageDialog(
        transient_for=parent,
        modal=True,
        destroy_with_parent=True,
        message_type=message_type,
        buttons=buttons,
        text=message,
    )
    if secondary:
        dialog.format_secondary_text(secondary)
    try:
        return dialog.run()
    finally:
        dialog.destroy()


def show_error_dialog(parent, message, secondary=None):
    """Show a modal error attached to its parent window."""
    return _message_dialog(parent, Gtk.MessageType.ERROR, message, secondary)


def show_info_dialog(parent, message, secondary=None):
    """Show a modal informational message attached to its parent window."""
    return _message_dialog(parent, Gtk.MessageType.INFO, message, secondary)


def ask_confirmation(parent, message, secondary=None, destructive=False,
                     confirm_label=None, cancel_label=None):
    """Ask for confirmation and return True only for the affirmative response.

    Callers must use this only for an irreversible/high-impact decision; prefer
    Undo for reversible actions.
    """
    dialog = Gtk.MessageDialog(
        transient_for=parent,
        modal=True,
        destroy_with_parent=True,
        message_type=Gtk.MessageType.WARNING if destructive else Gtk.MessageType.QUESTION,
        buttons=Gtk.ButtonsType.NONE,
        text=message,
    )
    if secondary:
        dialog.format_secondary_text(secondary)
    dialog.add_button(cancel_label or _("Cancel"), Gtk.ResponseType.CANCEL)
    confirm = dialog.add_button(
        confirm_label or _("Continue"), Gtk.ResponseType.OK)
    if destructive:
        confirm.get_style_context().add_class("destructive-action")
    else:
        confirm.get_style_context().add_class("suggested-action")
    dialog.set_default_response(Gtk.ResponseType.CANCEL)
    try:
        return dialog.run() == Gtk.ResponseType.OK
    finally:
        dialog.destroy()
