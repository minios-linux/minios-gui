"""Native renderer for precompiled MiniOS markup documents."""

from __future__ import absolute_import

import json
import locale
import os
import re
import unicodedata
from pathlib import Path
from urllib.parse import unquote, urlparse

import gi

gi.require_version("Gdk", "3.0")
gi.require_version("GdkPixbuf", "2.0")
gi.require_version("Gtk", "3.0")
from gi.repository import Gdk, GdkPixbuf, Gio, GLib, Gtk, Pango

DOCUMENT_KIND = "minios-markup-document"
DOCUMENT_SCHEMA_VERSION = 1


class DocumentFormatError(ValueError):
    """Raised when a compiled document has an invalid shape."""


def _locale_candidates(locale_name=None, fallback="en"):
    candidates = []
    values = []
    if locale_name:
        values.append(locale_name)
    else:
        values.extend(
            item for item in os.environ.get("LANGUAGE", "").split(":") if item)
        values.extend(os.environ.get(name, "") for name in (
            "LC_ALL", "LC_MESSAGES", "LANG"))
        values.append(locale.getlocale()[0] or "")
    for value in values:
        value = value.split(".", 1)[0].split("@", 1)[0]
        if not value or not re.match(r"^[A-Za-z0-9_-]+$", value):
            continue
        normalized = value.replace("-", "_")
        candidates.extend((normalized, normalized.replace("_", "-")))
        candidates.append(normalized.split("_", 1)[0])
    if fallback and re.match(r"^[A-Za-z0-9_-]+$", fallback):
        candidates.append(fallback)
    unique = []
    for candidate in candidates:
        if candidate and candidate not in unique:
            unique.append(candidate)
    return unique


def validate_document(document):
    if not isinstance(document, dict):
        raise DocumentFormatError("compiled document must be an object")
    if document.get("product_kind") != DOCUMENT_KIND:
        raise DocumentFormatError("unexpected compiled document type")
    if document.get("schema_version") != DOCUMENT_SCHEMA_VERSION:
        raise DocumentFormatError("unsupported compiled document version")
    if not isinstance(document.get("nodes"), list):
        raise DocumentFormatError("compiled document has no node list")
    return document


def load_localized_document(root, relative_path, locale_name=None, fallback="en"):
    """Load a compiled document with locale/language/English fallback."""
    relative = Path(relative_path)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("document help path must stay below its locale directory")
    root = Path(root)
    base = root.resolve()
    attempted = []
    for language in _locale_candidates(locale_name, fallback=fallback):
        path = root / language / relative
        attempted.append(str(path))
        if path.is_symlink():
            continue
        try:
            resolved = path.resolve()
            resolved.relative_to(base)
        except (OSError, ValueError):
            continue
        if resolved.is_file():
            try:
                document = json.loads(resolved.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, ValueError) as error:
                raise DocumentFormatError(
                    "invalid compiled document {}: {}".format(path, error))
            return validate_document(document)
    raise FileNotFoundError(
        "Localized compiled help was not found: {}".format(
            ", ".join(attempted)))


def document_asset_path(root, relative_path):
    """Resolve a document asset while keeping it below the bundle root."""
    relative = Path(relative_path)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("document asset path must stay below its bundle root")
    root = Path(root).resolve()
    unresolved = root / relative
    if unresolved.is_symlink():
        raise FileNotFoundError(str(unresolved))
    candidate = unresolved.resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        raise ValueError("document asset path escapes its bundle root")
    if not candidate.is_file():
        raise FileNotFoundError(str(candidate))
    return candidate


class _DocumentTable(Gtk.Grid):
    """Grid allocated to the document viewport without widening the TextView."""

    def __init__(self, owner):
        Gtk.Grid.__init__(self)
        self._owner = owner
        self._dark = self._is_dark()
        self.get_style_context().add_class("minios-document-table")
        self.get_style_context().add_class(
            "minios-document-table-dark" if self._dark
            else "minios-document-table-light")

    def _is_dark(self):
        found, base = self._owner.get_style_context().lookup_color(
            "theme_base_color")
        if not found:
            return False
        return (base.red * 0.2126 + base.green * 0.7152 +
                base.blue * 0.0722) < 0.5

    def _target_width(self):
        width = self._owner.get_allocated_width()
        if width <= 1:
            return 1
        return max(
            1, width - self._owner.get_left_margin() -
            self._owner.get_right_margin() - 2)

    def do_size_allocate(self, allocation):
        adjusted = Gdk.Rectangle()
        adjusted.x = allocation.x
        adjusted.y = allocation.y
        adjusted.width = self._target_width()
        adjusted.height = allocation.height
        Gtk.Grid.do_size_allocate(self, adjusted)

    def do_get_preferred_height(self):
        return Gtk.Grid.do_get_preferred_height_for_width(
            self, self._target_width())

    def do_get_preferred_height_for_width(self, _width):
        return Gtk.Grid.do_get_preferred_height_for_width(
            self, self._target_width())


class _DocumentCodeBlock(Gtk.Box):
    """Selectable code block sized to the document content column."""

    def __init__(self, owner, source, tokens):
        Gtk.Box.__init__(self, orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self._owner = owner
        self._source = str(source or "")
        self._copy_feedback_source = 0
        self._dark = self._is_dark()
        self.get_style_context().add_class(
            "minios-document-code-block-dark" if self._dark
            else "minios-document-code-block-light")

        overlay = Gtk.Overlay()
        self._label = Gtk.Label(xalign=0, yalign=0)
        self._label.set_use_markup(True)
        # Code is copied with the dedicated button. Keeping the label
        # selectable makes GTK draw an I-beam/caret inside a read-only help
        # page, which looks like an editable field.
        self._label.set_selectable(False)
        self._label.set_line_wrap(True)
        self._label.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
        self._label.set_margin_start(12)
        self._label.set_margin_end(44)
        self._label.set_margin_top(10)
        self._label.set_margin_bottom(10)
        self._label.set_markup(self._markup(self._source, tokens or []))
        overlay.add(self._label)

        self._copy_button = Gtk.Button()
        self._copy_button.set_relief(Gtk.ReliefStyle.NONE)
        self._copy_button.set_focus_on_click(False)
        self._copy_button.set_halign(Gtk.Align.END)
        self._copy_button.set_valign(Gtk.Align.START)
        self._copy_button.set_margin_top(5)
        self._copy_button.set_margin_end(5)
        self._copy_button.get_style_context().add_class("minios-code-copy-button")
        self._copy_button.set_image(Gtk.Image.new_from_icon_name(
            "edit-copy-symbolic", Gtk.IconSize.MENU))
        accessible = self._copy_button.get_accessible()
        if accessible is not None:
            accessible.set_name("Copy code")
        self._copy_button.connect("clicked", self._copy_to_clipboard)
        self.connect("destroy", self._on_destroy)
        overlay.add_overlay(self._copy_button)

        self.pack_start(overlay, True, True, 0)
        overlay.show_all()

    def _set_copy_icon(self, icon_name):
        self._copy_button.set_image(Gtk.Image.new_from_icon_name(
            icon_name, Gtk.IconSize.MENU))
        self._copy_button.get_image().show()

    def _copy_to_clipboard(self, _button=None):
        clipboard = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
        clipboard.set_text(self._source, -1)
        clipboard.store()
        if self._copy_feedback_source:
            GLib.source_remove(self._copy_feedback_source)
        self._set_copy_icon("emblem-ok-symbolic")
        self._copy_button.get_style_context().add_class(
            "minios-code-copy-success")
        self._copy_feedback_source = GLib.timeout_add(
            1200, self._reset_copy_feedback)

    def _reset_copy_feedback(self):
        self._copy_feedback_source = 0
        self._set_copy_icon("edit-copy-symbolic")
        self._copy_button.get_style_context().remove_class(
            "minios-code-copy-success")
        return False

    def _on_destroy(self, _widget=None):
        if self._copy_feedback_source:
            GLib.source_remove(self._copy_feedback_source)
            self._copy_feedback_source = 0

    def _is_dark(self):
        found, base = self._owner.get_style_context().lookup_color(
            "theme_base_color")
        if not found:
            return False
        return (base.red * 0.2126 + base.green * 0.7152 +
                base.blue * 0.0722) < 0.5

    def _target_width(self):
        width = self._owner.get_allocated_width()
        if width <= 1:
            return 32
        return max(
            32, width - self._owner.get_left_margin() -
            self._owner.get_right_margin() - 2)

    @staticmethod
    def _valid_color(value):
        color = Gdk.RGBA()
        return bool(value) and color.parse(str(value))

    def _markup(self, source, tokens):
        valid = bool(tokens) and all(
            isinstance(token, (list, tuple)) and len(token) >= 4 and
            token[0] == "syntax" for token in tokens)
        if valid and "".join(str(token[1]) for token in tokens) != source:
            valid = False
        default_color = "#e1e4e8" if self._dark else "#24292e"
        parts = []
        values = tokens if valid else [
            ["syntax", source, default_color, default_color]]
        for token in values:
            text = GLib.markup_escape_text(str(token[1]))
            color = token[3] if self._dark else token[2]
            color = color if self._valid_color(color) else default_color
            parts.append('<span foreground="{}">{}</span>'.format(color, text))
        return "<tt>{}</tt>".format("".join(parts))

    def get_text(self):
        return self._label.get_text()

    def do_get_preferred_width(self):
        return (1, 1)

    def do_get_preferred_height(self):
        return self._label.get_preferred_height_for_width(self._target_width())

    def do_get_preferred_height_for_width(self, _width):
        return self._label.get_preferred_height_for_width(self._target_width())

    def do_size_allocate(self, allocation):
        adjusted = Gdk.Rectangle()
        adjusted.x = allocation.x
        adjusted.y = allocation.y
        adjusted.width = self._target_width()
        adjusted.height = allocation.height
        Gtk.Box.do_size_allocate(self, adjusted)


class _DocumentAdmonition(Gtk.Box):
    """Semantic notice block sized to the document content column."""

    _STYLE_CLASSES = {
        "note": "minios-document-admonition-info",
        "info": "minios-document-admonition-info",
        "tip": "minios-document-admonition-success",
        "success": "minios-document-admonition-success",
        "warning": "minios-document-admonition-warning",
        "caution": "minios-document-admonition-warning",
        "danger": "minios-document-admonition-danger",
        "error": "minios-document-admonition-danger",
    }
    _ICONS = {
        "note": "dialog-information-symbolic",
        "info": "dialog-information-symbolic",
        "tip": "emblem-default-symbolic",
        "success": "emblem-default-symbolic",
        "warning": "dialog-warning-symbolic",
        "caution": "dialog-warning-symbolic",
        "danger": "dialog-error-symbolic",
        "error": "dialog-error-symbolic",
    }

    def __init__(self, owner, kind, title, nodes):
        Gtk.Box.__init__(self, orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self._owner = owner
        self.kind = str(kind or "note").lower()
        self.get_style_context().add_class("minios-document-admonition")
        self.get_style_context().add_class(
            self._STYLE_CLASSES.get(
                self.kind, "minios-document-admonition-info"))

        heading = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        icon = Gtk.Image.new_from_icon_name(
            self._ICONS.get(self.kind, "dialog-information-symbolic"),
            Gtk.IconSize.MENU)
        label = Gtk.Label(label=str(title or self.kind.title()), xalign=0)
        label.set_line_wrap(True)
        label.get_style_context().add_class("minios-document-admonition-title")
        heading.pack_start(icon, False, False, 0)
        heading.pack_start(label, True, True, 0)
        self.pack_start(heading, False, False, 0)

        self.body = DocumentTextView({
            "product_kind": DOCUMENT_KIND,
            "schema_version": DOCUMENT_SCHEMA_VERSION,
            "nodes": nodes or [],
        }, link_handler=owner.link_handler, asset_resolver=owner.asset_resolver)
        self.body.set_left_margin(22)
        self.body.set_right_margin(0)
        self.body.set_top_margin(0)
        self.body.set_bottom_margin(0)
        self.body.set_hexpand(True)
        self.body.get_style_context().add_class("minios-document-admonition-body")
        # Paragraph rendering deliberately adds spacing between top-level
        # blocks. At the end of a compact notice that becomes dead space, so
        # trim it when there are no embedded child widgets to preserve.
        if not self.body._embedded_widgets:
            buffer_ = self.body.get_buffer()
            text = buffer_.get_text(
                buffer_.get_start_iter(), buffer_.get_end_iter(), True)
            trimmed = text.rstrip()
            if len(trimmed) != len(text):
                buffer_.delete(
                    buffer_.get_iter_at_offset(len(trimmed)),
                    buffer_.get_end_iter())
        self.pack_start(self.body, True, True, 0)
        self.show_all()

    def _target_width(self):
        width = self._owner.get_allocated_width()
        if width <= 1:
            return 32
        return max(
            32, width - self._owner.get_left_margin() -
            self._owner.get_right_margin() - 2)

    def do_get_preferred_width(self):
        return (1, 1)

    def do_get_preferred_height(self):
        return Gtk.Box.do_get_preferred_height_for_width(
            self, self._target_width())

    def do_get_preferred_height_for_width(self, _width):
        return Gtk.Box.do_get_preferred_height_for_width(
            self, self._target_width())

    def do_size_allocate(self, allocation):
        adjusted = Gdk.Rectangle()
        adjusted.x = allocation.x
        adjusted.y = allocation.y
        adjusted.width = self._target_width()
        adjusted.height = allocation.height
        Gtk.Box.do_size_allocate(self, adjusted)


class _DocumentAssetImage(Gtk.Image):
    """Image that rerenders vector assets at the document column width."""

    def __init__(self, owner, filename, alt, expand=False):
        Gtk.Image.__init__(self)
        self._owner = owner
        self._filename = str(filename)
        self._expand = bool(expand)
        self._last_width = None
        probe = GdkPixbuf.Pixbuf.new_from_file(self._filename)
        self._source_width = max(1, probe.get_width())
        self.set_halign(Gtk.Align.START)
        self.set_tooltip_text(alt or None)
        if self._expand:
            self.get_style_context().add_class("minios-document-diagram")
            self.set_margin_top(10)
            self.set_margin_bottom(14)
        self.update_width()

    def _content_width(self):
        width = self._owner.get_allocated_width()
        if width <= 1:
            return 1
        return max(
            1, width - self._owner.get_left_margin() -
            self._owner.get_right_margin() - 2)

    def update_width(self):
        available = self._content_width()
        target = available if self._expand else min(self._source_width, available)
        target = max(1, int(target))
        if target == self._last_width:
            return
        pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_scale(
            self._filename, target, -1, True)
        self.set_from_pixbuf(pixbuf)
        self._last_width = target


class DocumentTextView(Gtk.TextView):
    """Render a precompiled markup document without a Markdown parser."""

    _ALLOWED_URI_SCHEMES = ("http", "https", "mailto")

    def __init__(self, document=None, link_handler=None, asset_resolver=None):
        Gtk.TextView.__init__(self)
        self.link_handler = link_handler
        self.asset_resolver = asset_resolver
        self._link_uris = {}
        self._embedded_widgets = []
        self._table_widgets = []
        self._code_widgets = []
        self._admonition_widgets = []
        self._asset_widgets = []
        self._anchors = {}
        self._headings = []
        self._link_cursor = None
        self._text_cursor = None
        self._hover_link_tag = None
        self.set_editable(False)
        self.set_cursor_visible(False)
        self.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self.set_left_margin(4)
        self.set_right_margin(4)
        self.set_top_margin(4)
        self.set_bottom_margin(4)
        self.get_style_context().add_class("minios-document-view")
        self._create_tags()
        self.add_events(
            Gdk.EventMask.POINTER_MOTION_MASK | Gdk.EventMask.LEAVE_NOTIFY_MASK)
        self.connect("key-release-event", self._on_key_release)
        self.connect("motion-notify-event", self._on_motion_notify)
        self.connect("leave-notify-event", self._on_leave_notify)
        self.connect("size-allocate", self._on_size_allocate)
        buffer_ = self.get_buffer()
        buffer_.create_tag(
            "kbd", family="monospace", weight=Pango.Weight.BOLD)
        buffer_.create_tag(
            "footnote", scale=0.85, rise=2500)
        buffer_.create_tag("subscript", scale=0.8, rise=-2500)
        buffer_.create_tag("superscript", scale=0.8, rise=2500)
        self.get_style_context().add_class("minios-document-view")
        if document is None:
            document = {
                "product_kind": DOCUMENT_KIND,
                "schema_version": DOCUMENT_SCHEMA_VERSION,
                "nodes": [],
            }
        self.set_document(document)

    def _create_tags(self):
        buffer_ = self.get_buffer()
        buffer_.create_tag(
            "heading1", weight=Pango.Weight.BOLD, scale=1.2,
            pixels_above_lines=8, pixels_below_lines=5)
        buffer_.create_tag(
            "heading2", weight=Pango.Weight.BOLD, scale=1.1,
            pixels_above_lines=7, pixels_below_lines=4)
        buffer_.create_tag(
            "heading3", weight=Pango.Weight.BOLD, scale=1.0,
            pixels_above_lines=6, pixels_below_lines=3)
        buffer_.create_tag("strong", weight=Pango.Weight.BOLD)
        buffer_.create_tag("emphasis", style=Pango.Style.ITALIC)
        buffer_.create_tag("strikethrough", strikethrough=True)
        found, base = self.get_style_context().lookup_color("theme_base_color")
        dark = bool(found and (
            base.red * 0.2126 + base.green * 0.7152 +
            base.blue * 0.0722) < 0.5)
        accent = "#a8b1ff" if dark else "#3451b2"
        code_background = "#242426" if dark else "#f6f6f7"
        # Inline code must remain part of the TextView's Pango layout so it
        # shares the exact text baseline. A child widget here sits on the
        # object-replacement glyph box and appears a few pixels too high.
        buffer_.create_tag(
            "code", family="monospace", scale=0.9, foreground=accent,
            background=code_background)
        buffer_.create_tag(
            "quote", style=Pango.Style.ITALIC, left_margin=18,
            right_margin=8)
        buffer_.create_tag(
            "link", foreground=accent, underline=Pango.Underline.NONE)

    def _reset_content(self):
        self._set_hover_link(None)
        for widget in self._embedded_widgets:
            try:
                widget.destroy()
            except Exception:
                pass
        self._embedded_widgets = []
        self._table_widgets = []
        self._code_widgets = []
        self._admonition_widgets = []
        self._asset_widgets = []
        self.get_buffer().set_text("")
        self._link_uris = {}
        self._anchors = {}
        self._headings = []

    def set_document(self, document):
        document = validate_document(document)
        self._reset_content()
        self._render_nodes(document["nodes"], ())

    def set_asset_resolver(self, callback):
        self.asset_resolver = callback

    def set_link_handler(self, callback):
        self.link_handler = callback

    def get_headings(self):
        return list(self._headings)

    def heading_at_y(self, y, min_level=1, max_level=6):
        """Return the last heading at or above a document y coordinate."""
        result = self.get_line_at_y(max(0, int(y)))
        iter_ = result[0]
        target = iter_.get_offset()
        current = None
        buffer_ = self.get_buffer()
        for level, title, anchor in self._headings:
            if level < min_level or level > max_level:
                continue
            mark = self._anchors.get(str(anchor or "").lower())
            if mark is None:
                continue
            if buffer_.get_iter_at_mark(mark).get_offset() > target:
                break
            current = (level, title, anchor)
        return current

    def scroll_to_anchor(self, anchor):
        buffer_ = self.get_buffer()
        if not anchor:
            iter_ = buffer_.get_start_iter()
        else:
            name = unquote(str(anchor)).lstrip("#").strip().lower()
            mark = self._anchors.get(name)
            if mark is None:
                mark = self._anchors.get(self._anchor_match_key(name))
            if mark is None:
                return False
            iter_ = buffer_.get_iter_at_mark(mark)

        buffer_.place_cursor(iter_)
        parent = self.get_parent()
        while parent is not None and not isinstance(parent, Gtk.ScrolledWindow):
            parent = parent.get_parent()
        adjustment = parent.get_vadjustment() if parent is not None else None
        if adjustment is None:
            self.scroll_to_iter(iter_, 0.0, True, 0.0, 0.0)
            return True

        location = self.get_iter_location(iter_)
        target = float(location.y - self.get_top_margin() - 4)
        maximum = max(
            adjustment.get_lower(),
            adjustment.get_upper() - adjustment.get_page_size())
        adjustment.set_value(max(
            adjustment.get_lower(), min(target, maximum)))
        return True

    def _tag(self, name):
        return self.get_buffer().get_tag_table().lookup(name)

    def _insert(self, text, tag_names=()):
        if not text:
            return
        buffer_ = self.get_buffer()
        tags = [self._tag(name) for name in tag_names if self._tag(name)]
        if tags:
            buffer_.insert_with_tags(buffer_.get_end_iter(), text, *tags)
        else:
            buffer_.insert(buffer_.get_end_iter(), text)

    def _register_anchor(self, name):
        name = str(name or "").lstrip("#").strip().lower()
        if not name:
            return None
        mark = self.get_buffer().create_mark(
            None, self.get_buffer().get_end_iter(), True)
        self._anchors[name] = mark
        alias = self._anchor_match_key(name)
        if alias:
            self._anchors.setdefault(alias, mark)
        return mark

    def _render_nodes(self, nodes, tag_names=(), list_depth=0):
        for node in nodes or ():
            if not isinstance(node, (list, tuple)) or not node:
                continue
            kind = node[0]
            if kind == "heading":
                level = max(1, min(int(node[1]), 6))
                anchor = node[2]
                children = node[3]
                self._register_anchor(anchor)
                title = self._plain_text(children)
                self._headings.append((level, title, anchor))
                style = "heading{}".format(min(level, 3))
                self._render_base_nodes(
                    children, tag_names + (style,), list_depth)
                self._insert("\n\n")
            elif kind == "anchor":
                self._register_anchor(node[1])
            elif kind in ("image", "diagram"):
                self._render_asset(node)
            elif kind == "admonition":
                self._render_admonition(node, tag_names, list_depth)
            else:
                self._render_base_nodes([node], tag_names, list_depth)

    def _render_base_nodes(self, nodes, tag_names=(), list_depth=0):
        for node in nodes or ():
            if not node:
                continue
            kind = node[0]
            if kind == "text":
                self._insert(node[1], tag_names)
            elif kind == "span":
                if node[1] == "code":
                    self._render_inline_code(node[2], tag_names, list_depth)
                else:
                    self._render_nodes(
                        node[2], tag_names + (node[1],), list_depth)
            elif kind == "block":
                self._render_nodes(node[2], tag_names + (node[1],), list_depth)
                self._insert("\n\n")
            elif kind == "code_block":
                self._render_code_block(node, tag_names)
            elif kind == "list":
                end = self.get_buffer().get_end_iter()
                if list_depth > 0 and not end.starts_line():
                    self._insert("\n")
                self._render_list(node[2], node[1], list_depth)
                if list_depth == 0:
                    self._insert("\n")
            elif kind == "link":
                self._render_link(node, tag_names, list_depth)
            elif kind == "rule":
                self._insert("----------------\n\n", tag_names)
            elif kind == "table":
                self._render_table(node[1], tag_names, list_depth)

    def _render_inline_code(self, nodes, tag_names, list_depth):
        # Thin spaces reproduce the small horizontal breathing room of the
        # VitePress pill without leaving Pango text flow or changing baseline.
        tags = tag_names + ("code",)
        self._insert("\u2009", tags)
        self._render_nodes(nodes, tags, list_depth)
        self._insert("\u2009", tags)

    def _render_code_block(self, node, _tag_names):
        source = str(node[1] or "")
        tokens = node[3] if len(node) > 3 and isinstance(node[3], list) else []
        end = self.get_buffer().get_end_iter()
        if not end.starts_line():
            self._insert("\n")
        block = _DocumentCodeBlock(self, source, tokens)
        anchor = self.get_buffer().create_child_anchor(
            self.get_buffer().get_end_iter())
        self.add_child_at_anchor(block, anchor)
        self._embedded_widgets.append(block)
        self._code_widgets.append(block)
        block.show()
        self._insert("\n\n")

    def _render_admonition(self, node, _tag_names, _list_depth):
        kind = str(node[1] or "note").lower()
        title = node[2] or kind.title()
        end = self.get_buffer().get_end_iter()
        if not end.starts_line():
            self._insert("\n")
        block = _DocumentAdmonition(self, kind, title, node[3])
        anchor = self.get_buffer().create_child_anchor(
            self.get_buffer().get_end_iter())
        self.add_child_at_anchor(block, anchor)
        self._embedded_widgets.append(block)
        self._admonition_widgets.append(block)
        block.show_all()
        self._insert("\n\n")

    def _render_asset(self, node):
        relative = node[1] if len(node) > 1 else ""
        alt = node[2] if len(node) > 2 else ""
        if self.asset_resolver is None:
            self._insert(alt or relative)
            self._insert("\n\n")
            return
        try:
            path = Path(self.asset_resolver(relative))
            image = _DocumentAssetImage(
                self, path, alt, expand=(node[0] == "diagram"))
        except Exception:
            self._insert(alt or relative)
            self._insert("\n\n")
            return
        anchor = self.get_buffer().create_child_anchor(
            self.get_buffer().get_end_iter())
        self.add_child_at_anchor(image, anchor)
        self._embedded_widgets.append(image)
        self._asset_widgets.append(image)
        image.show()
        self._insert("\n\n")

    def _render_list(self, nodes, ordered, list_depth):
        start = 1
        if isinstance(ordered, dict):
            start = max(1, int(ordered.get("start", 1)))
            ordered = bool(ordered.get("ordered"))
        index = start - 1
        for node in nodes:
            if node[0] != "item":
                self._render_nodes([node], (), list_depth + 1)
                continue
            index += 1
            checked = node[1] if len(node) > 2 else None
            children = node[2] if len(node) > 2 else node[1]
            prefix = "{}. ".format(index) if ordered else "- "
            if checked is True:
                prefix += "☑ "
            elif checked is False:
                prefix += "☐ "
            self._insert("  " * list_depth + prefix)
            self._render_nodes(children, (), list_depth + 1)
            end = self.get_buffer().get_end_iter()
            if not end.starts_line():
                self._insert("\n")

    def _render_table(self, rows, _tag_names, _list_depth):
        grid = _DocumentTable(self)
        grid.set_row_spacing(0)
        grid.set_column_spacing(0)
        grid.set_halign(Gtk.Align.FILL)
        grid.set_hexpand(True)
        valid_rows = [row for row in rows if row and row[0] == "table_row"]
        for row_index, row in enumerate(valid_rows):
            header = bool(row[1]) if len(row) > 2 else row_index == 0
            cells = row[2] if len(row) > 2 else row[1]
            for column, cell in enumerate(cells):
                children = cell[1] if cell and cell[0] == "table_cell" else []
                label = Gtk.Label(xalign=0, yalign=0)
                label.set_use_markup(True)
                label.set_markup(self._inline_markup(children))
                label.set_line_wrap(True)
                label.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
                label.set_hexpand(True)
                label.set_halign(Gtk.Align.FILL)
                label.set_selectable(False)
                context = label.get_style_context()
                context.add_class("minios-table-cell")
                if header:
                    context.add_class("minios-table-header")
                if row_index == 0:
                    context.add_class("minios-table-first-row")
                if row_index == len(valid_rows) - 1:
                    context.add_class("minios-table-last-row")
                if column == 0:
                    context.add_class("minios-table-first-column")
                if column == len(cells) - 1:
                    context.add_class("minios-table-last-column")
                label.connect("activate-link", self._on_table_link)
                grid.attach(label, column, row_index, 1, 1)
        anchor = self.get_buffer().create_child_anchor(
            self.get_buffer().get_end_iter())
        self.add_child_at_anchor(grid, anchor)
        self._embedded_widgets.append(grid)
        self._table_widgets.append(grid)
        grid.show_all()
        self._insert("\n\n")

    def _on_size_allocate(self, _widget, _allocation):
        for grid in self._table_widgets:
            grid.queue_resize()
        for block in self._code_widgets:
            block.queue_resize()
        for block in self._admonition_widgets:
            block.queue_resize()
        for image in self._asset_widgets:
            image.update_width()

    def _on_table_link(self, _label, uri):
        safe = self._safe_uri(uri)
        if not safe:
            return True
        return bool(self._activate_uri(safe))

    def _inline_markup(self, nodes):
        parts = []
        for node in nodes or ():
            kind = node[0]
            if kind == "text":
                parts.append(GLib.markup_escape_text(str(node[1])))
            elif kind == "span":
                parts.append(self._span_markup(node[1], node[2]))
            elif kind == "link":
                uri = self._safe_uri(node[1])
                body = self._inline_markup(node[3])
                if uri:
                    parts.append('<a href="{}">{}</a>'.format(
                        GLib.markup_escape_text(uri), body))
                else:
                    parts.append(body)
            elif kind in ("image", "diagram"):
                parts.append(GLib.markup_escape_text(node[2] or node[1]))
        return "".join(parts)

    def _span_markup(self, style, children):
        body = self._inline_markup(children)
        tags = {
            "strong": ("<b>", "</b>"),
            "emphasis": ("<i>", "</i>"),
            "strikethrough": ("<s>", "</s>"),
            "code": ("<tt>", "</tt>"),
            "kbd": ("<b><tt>", "</tt></b>"),
            "footnote": ("<small>", "</small>"),
            "subscript": ("<sub>", "</sub>"),
            "superscript": ("<sup>", "</sup>"),
        }
        opening, closing = tags.get(style, ("", ""))
        return opening + body + closing

    def _render_link(self, node, tag_names, list_depth):
        uri = self._safe_uri(node[1])
        if not uri:
            self._render_nodes(node[3], tag_names, list_depth)
            return
        buffer_ = self.get_buffer()
        start = buffer_.get_end_iter().get_offset()
        self._render_nodes(node[3], tag_names + ("link",), list_depth)
        begin_iter = buffer_.get_iter_at_offset(start)
        end_iter = buffer_.get_end_iter()
        link_tag = buffer_.create_tag(None, underline=Pango.Underline.NONE)
        self._link_uris[link_tag] = uri
        link_tag.connect("event", self._on_link_event, uri)
        buffer_.apply_tag(link_tag, begin_iter, end_iter)

    def _safe_uri(self, uri):
        if not isinstance(uri, str) or not uri:
            return None
        if any(ord(char) < 32 or ord(char) == 127 for char in uri):
            return None
        value = uri.strip()
        parsed = urlparse(value)
        if parsed.scheme:
            return value if parsed.scheme.lower() in self._ALLOWED_URI_SCHEMES else None
        if value.startswith("//"):
            return None
        return value

    @staticmethod
    def _anchor_match_key(value):
        normalized = unicodedata.normalize("NFKD", value or "").lower()
        return "".join(
            char for char in normalized
            if unicodedata.category(char)[0] != "M")

    @staticmethod
    def _plain_text(nodes):
        values = []
        for node in nodes or ():
            if not node:
                continue
            if node[0] == "text":
                values.append(str(node[1]))
            elif node[0] in ("span", "block"):
                values.append(DocumentTextView._plain_text(node[2]))
            elif node[0] == "link":
                values.append(DocumentTextView._plain_text(node[3]))
        return "".join(values).strip()

    def _link_tag_at_iter(self, iter_):
        for tag in iter_.get_tags():
            uri = self._link_uris.get(tag)
            if uri:
                return tag, uri
        return None, None

    def _link_uri_at_iter(self, iter_):
        return self._link_tag_at_iter(iter_)[1]

    def _link_tag_at_event(self, event):
        event_window = getattr(event, "window", None)
        if event_window is None:
            return None, None
        window_type = self.get_window_type(event_window)
        if window_type not in (Gtk.TextWindowType.TEXT, Gtk.TextWindowType.WIDGET):
            return None, None
        coords = event.get_coords()
        if not coords:
            return None, None
        if len(coords) == 2:
            x, y = coords
        else:
            has_coords, x, y = coords
            if not has_coords:
                return None, None
        buffer_x, buffer_y = self.window_to_buffer_coords(
            window_type, int(x), int(y))
        found, iter_ = self.get_iter_at_location(buffer_x, buffer_y)
        if not found:
            return None, None
        return self._link_tag_at_iter(iter_)

    def _set_link_pointer(self, active):
        window = self.get_window(Gtk.TextWindowType.TEXT)
        if window is None:
            return
        display = window.get_display()
        if self._link_cursor is None:
            self._link_cursor = Gdk.Cursor.new_for_display(
                display, Gdk.CursorType.HAND2)
        if self._text_cursor is None:
            self._text_cursor = Gdk.Cursor.new_for_display(
                display, Gdk.CursorType.XTERM)
        window.set_cursor(self._link_cursor if active else self._text_cursor)

    def _set_hover_link(self, tag):
        if self._hover_link_tag is tag:
            return
        if self._hover_link_tag is not None:
            self._hover_link_tag.set_property(
                "underline", Pango.Underline.NONE)
        self._hover_link_tag = tag
        if tag is not None:
            tag.set_property("underline", Pango.Underline.SINGLE)

    def _on_motion_notify(self, _view, event):
        tag, uri = self._link_tag_at_event(event)
        self._set_link_pointer(uri is not None)
        self._set_hover_link(tag)
        return False

    def _on_leave_notify(self, _view, _event):
        self._set_link_pointer(False)
        self._set_hover_link(None)
        return False

    def _on_link_event(self, _tag, _object, event, _iter, uri):
        if event.type != Gdk.EventType.BUTTON_RELEASE:
            return False
        has_button, button = event.get_button()
        if has_button and button == Gdk.BUTTON_PRIMARY:
            return self._activate_uri(uri)
        return False

    def _on_key_release(self, _view, event):
        if event.keyval not in (Gdk.KEY_Return, Gdk.KEY_KP_Enter):
            return False
        buffer_ = self.get_buffer()
        cursor = buffer_.get_iter_at_mark(buffer_.get_insert())
        uri = self._link_uri_at_iter(cursor)
        if uri:
            return self._activate_uri(uri)
        return False

    def _activate_uri(self, uri):
        if self.link_handler is not None and self.link_handler(uri):
            return True
        if urlparse(uri).scheme.lower() in self._ALLOWED_URI_SCHEMES:
            return self._open_uri(uri)
        return False

    @staticmethod
    def _open_uri(uri):
        try:
            Gio.AppInfo.launch_default_for_uri(uri, None)
        except GLib.Error:
            return False
        return True
