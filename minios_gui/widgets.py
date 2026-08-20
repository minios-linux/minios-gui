"""Reusable semantic GTK 3 widgets for MiniOS applications."""

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk

from .style import new_icon, resolve_icon


_BANNER_CLASSES = {
    "info": "info-banner",
    "warning": "warning-banner",
    "error": "error-banner",
    "success": "success-banner",
}

_BANNER_ICONS = {
    "info": "dialog-information-symbolic",
    "warning": "dialog-warning-symbolic",
    "error": "dialog-error-symbolic",
    "success": "emblem-default-symbolic",
}


def new_header_bar(title):
    """Return the canonical MiniOS workspace header bar."""
    header = Gtk.HeaderBar(show_close_button=True)
    header.set_has_subtitle(False)
    header.get_style_context().add_class("minios-headerbar")
    header.props.title = title
    return header


class StatusBanner(Gtk.Box):
    """Theme-aware status banner with a semantic intent, icon and message."""

    def __init__(self, text="", intent="info", icon=None):
        Gtk.Box.__init__(self, orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self._intent = None
        self._icon = new_icon("dialog-information-symbolic",
                              Gtk.IconSize.LARGE_TOOLBAR)
        self._label = Gtk.Label(xalign=0)
        self._label.set_line_wrap(True)
        self._label.set_hexpand(True)
        self.pack_start(self._icon, False, False, 0)
        self.pack_start(self._label, True, True, 0)
        self.set_intent(intent, icon=icon)
        self.set_text(text)

    @property
    def label(self):
        return self._label

    @property
    def icon(self):
        return self._icon

    @property
    def intent(self):
        return self._intent

    def set_text(self, text):
        self._label.set_text(text or "")

    def set_intent(self, intent, icon=None):
        if intent not in _BANNER_CLASSES:
            raise ValueError("unknown status banner intent: {}".format(intent))
        context = self.get_style_context()
        for style_class in _BANNER_CLASSES.values():
            context.remove_class(style_class)
        context.add_class(_BANNER_CLASSES[intent])
        icon_name = resolve_icon(icon or _BANNER_ICONS[intent])
        self._icon.set_from_icon_name(icon_name, Gtk.IconSize.LARGE_TOOLBAR)
        self._intent = intent


class HelpPopoverButton(Gtk.Button):
    """Context-help button with structured, keyboard-accessible popover text."""

    def __init__(self, title, summary="", sections=(), label=None,
                 tooltip=None, compact=False, markup=False, width=None):
        Gtk.Button.__init__(self)
        self.set_focus_on_click(False)
        self.get_style_context().add_class("minios-help-button")
        if compact:
            self.set_relief(Gtk.ReliefStyle.NONE)
        icon = new_icon("dialog-information-symbolic", Gtk.IconSize.MENU,
                        accessible_name=label or title)
        if label:
            box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=5)
            box.pack_start(icon, False, False, 0)
            box.pack_start(Gtk.Label(label=label), False, False, 0)
            self.add(box)
            self.get_style_context().add_class("minios-text-button")
        else:
            self.add(icon)
            icon.get_style_context().add_class("field-help-icon")
        self.set_tooltip_text(tooltip or title)
        accessible = self.get_accessible()
        if accessible is not None:
            accessible.set_name(label or title)

        popover = Gtk.Popover.new(self)
        popover.set_position(Gtk.PositionType.BOTTOM)
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        content_width = int(width or (420 if compact else 600))
        scrolled.set_min_content_width(content_width)
        scrolled.set_size_request(content_width, -1)
        if hasattr(scrolled, "set_propagate_natural_width"):
            scrolled.set_propagate_natural_width(True)
        if hasattr(scrolled, "set_max_content_height"):
            scrolled.set_max_content_height(420)
        if hasattr(scrolled, "set_propagate_natural_height"):
            scrolled.set_propagate_natural_height(True)
        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        body.set_margin_top(12)
        body.set_margin_bottom(12)
        body.set_margin_start(12)
        body.set_margin_end(12)

        heading = Gtk.Label(label=title, xalign=0)
        heading.get_style_context().add_class("section-title")
        body.pack_start(heading, False, False, 0)
        if summary:
            body.pack_start(
                self._help_label(summary, markup=markup), False, False, 0)
        for section_title, section_text in sections:
            section_heading = Gtk.Label(label=section_title, xalign=0)
            section_heading.get_style_context().add_class("row-title")
            body.pack_start(section_heading, False, False, 2)
            body.pack_start(
                self._help_label(section_text, markup=markup), False, False, 0)
        scrolled.add(body)
        popover.add(scrolled)
        self.help_popover = popover
        self.connect("clicked", self._toggle_help)

    def _toggle_help(self, _button):
        if self.help_popover.get_visible():
            self.help_popover.popdown()
        else:
            self.help_popover.show_all()
            self.help_popover.popup()

    @staticmethod
    def _help_label(text, markup=False):
        label = Gtk.Label(xalign=0)
        if markup:
            label.set_markup(text)
        else:
            label.set_text(text)
        label.set_line_wrap(True)
        label.set_max_width_chars(58)
        label.set_selectable(False)
        return label
