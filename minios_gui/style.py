"""Theme and icon helpers shared by MiniOS GTK 3 applications."""

import os

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, Gtk


SHARED_CSS_PATH = "/usr/share/minios/minios.css"


def apply_css(*paths):
    """Load existing stylesheets in order and return their loaded paths.

    Later providers at the same priority override earlier providers. Invalid or
    missing optional files are skipped so applications can still start on a
    partially installed or development system.
    """
    screen = Gdk.Screen.get_default()
    if screen is None:
        return ()

    loaded = []
    for path in paths:
        if not path or not os.path.isfile(path):
            continue
        provider = Gtk.CssProvider()
        try:
            provider.load_from_path(path)
        except Exception:
            continue
        Gtk.StyleContext.add_provider_for_screen(
            screen, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        loaded.append(path)
    return tuple(loaded)


def apply_minios_css(*app_paths):
    """Load the MiniOS base stylesheet, then optional app-specific overrides."""
    return apply_css(*((SHARED_CSS_PATH,) + tuple(app_paths)))


def resolve_icon(candidates, fallback="image-missing", prefer_color=True):
    """Return the first icon name available in the active GTK icon theme.

    Classic desktops use full-color icons on buttons and toolbars. When
    ``prefer_color`` is set (the default) a ``*-symbolic`` candidate first tries
    its full-color base name (e.g. ``document-open`` before
    ``document-open-symbolic``) and only falls back to the symbolic variant when
    the theme has no colored version.
    """
    if isinstance(candidates, str):
        candidates = (candidates,)
    theme = Gtk.IconTheme.get_default()
    if theme is None:
        return fallback
    for name in candidates:
        if not name:
            continue
        options = []
        if prefer_color and name.endswith("-symbolic"):
            options.append(name[:-len("-symbolic")])
        options.append(name)
        for option in options:
            if theme.has_icon(option):
                return option
    return fallback


def new_icon(candidates, size=Gtk.IconSize.BUTTON, fallback="image-missing",
             accessible_name=None):
    """Create a theme icon with an optional accessible name."""
    image = Gtk.Image.new_from_icon_name(
        resolve_icon(candidates, fallback=fallback), size)
    if accessible_name:
        accessible = image.get_accessible()
        if accessible is not None:
            accessible.set_name(accessible_name)
    return image
