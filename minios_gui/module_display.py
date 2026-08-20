"""Shared presentation metadata for MiniOS module filenames."""


def classify_module(name):
    """Return ``(role_id, icon_candidates)`` for a MiniOS module filename."""
    lower = (name or "").lower()
    if "core" in lower or "minios" in lower:
        return "core", ("application-x-executable", "computer", "system-run")
    if "kernel" in lower:
        return "kernel", ("cpu", "application-x-firmware", "system-run")
    if any(token in lower for token in ("firmware", "ucode", "microcode")):
        return "firmware", ("application-x-firmware", "media-flash")
    if any(token in lower for token in ("gui-base", "guibase", "xorg", "x11", "wayland")):
        return "gui-base", ("preferences-desktop-display", "video-display")
    if any(token in lower for token in (
            "desktop", "xfce", "kde", "plasma", "gnome", "lxqt", "lxde",
            "mate", "cinnamon", "fluxbox", "openbox")):
        return "desktop", ("user-desktop", "preferences-desktop")
    if any(token in lower for token in ("firefox", "chromium", "chrome", "browser")):
        return "browser", ("web-browser", "firefox", "internet-web-browser")
    if "toolbox" in lower or "tools" in lower:
        return "toolbox", ("applications-utilities", "applications-accessories")
    if "ultra" in lower:
        return "ultra", ("applications-graphics", "applications-other")
    if any(token in lower for token in ("apps", "application", "software", "office")):
        return "apps", ("applications-other", "application-x-addon")
    return "custom", ("package-x-generic",)


def format_bytes(size):
    """Format a byte count for compact UI presentation; return None if unknown."""
    if size is None:
        return None
    if size >= 1024 * 1024 * 1024:
        return "{:.1f} GiB".format(size / float(1024 * 1024 * 1024))
    if size >= 1024 * 1024:
        return "{:.0f} MiB".format(size / float(1024 * 1024))
    return "{:.0f} KiB".format(size / 1024.0)
