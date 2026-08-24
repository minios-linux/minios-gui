"""Native Markdown presentation helpers for MiniOS GTK applications."""

from __future__ import absolute_import

import locale
import os
import re
import unicodedata
from pathlib import Path
from urllib.parse import unquote, urljoin, urlparse

import gi
try:
    import mistune
except ImportError:  # Keep non-Markdown minios_gui helpers importable.
    mistune = None

gi.require_version("Gtk", "3.0")
from gi.repository import Gdk, Gio, GLib, Gtk, Pango

from .mermaid import MermaidDiagram, MermaidParseError


_LegacyRenderer = getattr(mistune, "Renderer", object)


class _NodeRenderer(_LegacyRenderer):
    """Build a small presentation tree instead of Mistune's default HTML."""

    def placeholder(self):
        return []

    def text(self, text):
        return [("text", text)]

    def escape(self, text):
        return self.text(text)

    def paragraph(self, children):
        return [("block", "paragraph", children)]

    def header(self, children, level, raw=None):
        return [("block", "heading{}".format(min(level, 3)), children)]

    def double_emphasis(self, children):
        return [("span", "strong", children)]

    def emphasis(self, children):
        return [("span", "emphasis", children)]

    def strikethrough(self, children):
        return [("span", "strikethrough", children)]

    def codespan(self, text):
        return [("span", "code", self.text(text.rstrip()))]

    def block_code(self, code, lang=None):
        return [("code_block", code.rstrip("\n"), lang)]

    def block_quote(self, children):
        return [("block", "quote", children)]

    def list(self, children, ordered=True):
        return [("list", ordered, children)]

    def list_item(self, children):
        return [("item", children)]

    def link(self, link, title, children):
        return [("link", link, title, children)]

    def autolink(self, link, is_email=False):
        uri = "mailto:{}".format(link) if is_email else link
        return self.link(uri, None, self.text(link))

    def image(self, src, title, text):
        return self.text(text or src)

    def linebreak(self):
        return [("text", "\n")]

    def newline(self):
        return [("text", "\n")]

    def hrule(self):
        return [("rule",)]

    def block_html(self, html):
        return self.text(html)

    def inline_html(self, html):
        return self.text(html)

    def table_cell(self, children, **flags):
        return [("table_cell", children)]

    def table_row(self, children):
        return [("table_row", children)]

    def table(self, header, body):
        return [("table", header + body)]

    def footnote_ref(self, key, index):
        return self.text("[{}]".format(index))

    def footnote_item(self, key, children):
        return [("item", children)]

    def footnotes(self, children):
        return [("list", True, children)]


def _safe_inline_html(text):
    """Translate the tiny HTML subset used by MiniOS docs into Markdown."""
    text = re.sub(r"(?i)<br\s*/?>", "  \n", text)
    text = re.sub(
        r"(?is)<kbd>(.*?)</kbd>",
        lambda match: "`{}`".format(match.group(1).replace("`", "")),
        text)
    text = re.sub(r"(?i)<(/?)strong\s*>", "**", text)
    text = re.sub(r"(?i)<(/?)em\s*>", "*", text)
    return text


def _normalize_safe_html(text):
    """Normalize safe inline HTML without touching fenced code blocks."""
    fence = re.compile(
        r"(^[ \t]*(```|~~~)[^\n]*\n.*?^[ \t]*\2[ \t]*$)",
        re.MULTILINE | re.DOTALL)
    parts = fence.split(text or "")
    out = []
    index = 0
    while index < len(parts):
        if index + 2 < len(parts) and parts[index + 1]:
            out.append(_safe_inline_html(parts[index]))
            out.append(parts[index + 1])
            index += 3
        else:
            out.append(_safe_inline_html(parts[index]))
            index += 1
    return "".join(out)


def parse_markdown(text):
    """Return presentation nodes for Markdown without producing HTML."""
    if mistune is None:
        raise RuntimeError("Mistune is required for Markdown rendering")
    text = _normalize_safe_html(text or "")
    if hasattr(mistune, "Renderer"):
        renderer = _NodeRenderer(escape=True)
        return mistune.Markdown(renderer=renderer)(text)

    parser = mistune.create_markdown(
        renderer="ast", plugins=["table", "strikethrough"])
    return _convert_ast_nodes(parser(text))


def _ast_value(node, name, default=None):
    attrs = node.get("attrs") or {}
    return attrs.get(name, node.get(name, default))


def _ast_text(node):
    return node.get("raw", node.get("text", ""))


def _convert_ast_nodes(nodes):
    converted = []
    for node in nodes or ():
        converted.extend(_convert_ast_node(node))
    return converted


def _convert_ast_node(node):
    kind = node.get("type", "")
    children = node.get("children") or ()

    if kind == "text":
        return [("text", _ast_text(node))]
    if kind in ("blank_line", "newline"):
        return []
    if kind in ("softbreak", "linebreak"):
        return [("text", "\n")]
    if kind == "paragraph":
        return [("block", "paragraph", _convert_ast_nodes(children))]
    if kind == "block_text":
        return _convert_ast_nodes(children)
    if kind == "heading":
        level = min(int(_ast_value(node, "level", 1)), 3)
        return [("block", "heading{}".format(level),
                 _convert_ast_nodes(children))]
    if kind in ("strong", "emphasis", "strikethrough"):
        tag = "strong" if kind == "strong" else kind
        return [("span", tag, _convert_ast_nodes(children))]
    if kind == "codespan":
        return [("span", "code", [("text", _ast_text(node).rstrip())])]
    if kind == "block_code":
        language = _ast_value(node, "info")
        return [("code_block", _ast_text(node).rstrip("\n"), language)]
    if kind == "block_quote":
        return [("block", "quote", _convert_ast_nodes(children))]
    if kind == "list":
        ordered = bool(_ast_value(node, "ordered", False))
        return [("list", ordered, _convert_ast_nodes(children))]
    if kind == "list_item":
        return [("item", _convert_ast_nodes(children))]
    if kind == "link":
        return [("link", _ast_value(node, "url", _ast_value(node, "link", "")),
                 _ast_value(node, "title"), _convert_ast_nodes(children))]
    if kind == "image":
        alt = _ast_value(node, "alt")
        if alt is None:
            alt = MarkdownTextView._plain_text(_convert_ast_nodes(children))
        return [("text", alt or _ast_value(node, "url", ""))]
    if kind in ("thematic_break", "hrule"):
        return [("rule",)]
    if kind in ("inline_html", "block_html"):
        return [("text", _ast_text(node))]
    if kind == "table":
        return [("table", _convert_ast_nodes(children))]
    if kind == "table_head":
        return [("table_row", _convert_ast_nodes(children))]
    if kind == "table_body":
        return _convert_ast_nodes(children)
    if kind == "table_row":
        return [("table_row", _convert_ast_nodes(children))]
    if kind == "table_cell":
        return [("table_cell", _convert_ast_nodes(children))]

    if children:
        return _convert_ast_nodes(children)
    value = _ast_text(node)
    return [("text", value)] if value else []


def _locale_candidates(locale_name=None, fallback="en"):
    candidates = []
    values = []
    if locale_name:
        values.append(locale_name)
    else:
        values.extend(
            item for item in os.environ.get("LANGUAGE", "").split(":")
            if item)
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


def load_localized_markdown(root, relative_path, locale_name=None,
                            fallback="en"):
    """Load ``root/locale/relative_path`` with language and English fallback."""
    relative = Path(relative_path)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("Markdown help path must stay below its locale directory")

    root = Path(root)
    attempted = []
    for language in _locale_candidates(locale_name, fallback=fallback):
        path = root / language / relative
        attempted.append(str(path))
        if path.is_file():
            return path.read_text(encoding="utf-8")
    raise FileNotFoundError(
        "Localized Markdown help was not found: {}".format(
            ", ".join(attempted)))


class MarkdownTextView(Gtk.TextView):
    """Read-only GTK text view rendering a safe, useful Markdown subset.

    ``allow_internal_links`` exposes relative and fragment links to an optional
    ``link_handler`` callback. ``render_mermaid`` enables the reusable native
    flowchart renderer; unsupported Mermaid remains a source-code block. The
    defaults remain compatible with older callers: only http, https and mailto
    links are activated externally and Mermaid is not rendered unless enabled.
    """

    _ALLOWED_URI_SCHEMES = ("http", "https", "mailto")

    def __init__(self, markdown="", base_uri=None, link_handler=None,
                 allow_internal_links=False, render_mermaid=False):
        Gtk.TextView.__init__(self)
        self.base_uri = base_uri
        self.link_handler = link_handler
        self.allow_internal_links = bool(allow_internal_links)
        self.render_mermaid = bool(render_mermaid)
        self._link_uris = {}
        self._embedded_widgets = []
        self._anchors = {}
        self._headings = []
        self._slug_counts = {}
        self.set_editable(False)
        self.set_cursor_visible(True)
        self.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self.set_left_margin(4)
        self.set_right_margin(4)
        self.set_top_margin(4)
        self.set_bottom_margin(4)
        self.get_style_context().add_class("minios-markdown-view")
        self._create_tags()
        self.connect("key-release-event", self._on_key_release)
        self.set_markdown(markdown)

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
        buffer_.create_tag("code", family="monospace")
        buffer_.create_tag(
            "code_label", family="monospace", weight=Pango.Weight.BOLD,
            left_margin=12, pixels_above_lines=5)
        buffer_.create_tag(
            "code_block", family="monospace", left_margin=12, right_margin=8,
            pixels_above_lines=2,
            pixels_below_lines=5)
        buffer_.create_tag(
            "quote", style=Pango.Style.ITALIC, left_margin=18,
            right_margin=8)
        buffer_.create_tag("link", underline=Pango.Underline.SINGLE)

    def set_markdown(self, markdown):
        for widget in self._embedded_widgets:
            try:
                widget.destroy()
            except Exception:
                pass
        self._embedded_widgets = []
        buffer_ = self.get_buffer()
        buffer_.set_text("")
        self._link_uris = {}
        self._anchors = {}
        self._headings = []
        self._slug_counts = {}
        self._render_nodes(parse_markdown(markdown), ())

    def set_link_handler(self, callback):
        """Set a callback receiving activated safe links, or ``None``."""
        self.link_handler = callback

    def get_headings(self):
        """Return ``(level, title, anchor)`` tuples for rendered headings."""
        return list(self._headings)

    def scroll_to_anchor(self, anchor):
        """Move the view to a rendered heading anchor."""
        if not anchor:
            mark = self.get_buffer().get_insert()
            self.get_buffer().place_cursor(self.get_buffer().get_start_iter())
            self.scroll_mark_onscreen(mark)
            return True
        name = unquote(str(anchor)).lstrip("#").strip().lower()
        mark = self._anchors.get(name)
        if mark is None:
            mark = self._anchors.get(self._anchor_match_key(name))
        if mark is None:
            return False
        buffer_ = self.get_buffer()
        buffer_.place_cursor(buffer_.get_iter_at_mark(mark))
        self.scroll_to_mark(mark, 0.08, True, 0.0, 0.0)
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

    def _render_nodes(self, nodes, tag_names=(), list_depth=0):
        for node in nodes:
            kind = node[0]
            if kind == "text":
                self._insert(node[1], tag_names)
            elif kind == "span":
                self._render_nodes(
                    node[2], tag_names + (node[1],), list_depth)
            elif kind == "block":
                if node[1].startswith("heading"):
                    self._register_heading(node[1], node[2])
                self._render_nodes(
                    node[2], tag_names + (node[1],), list_depth)
                self._insert("\n\n")
            elif kind == "code_block":
                info = (node[2] or "").strip()
                language = info.split(None, 1)[0] if info else ""
                if language.lower() == "mermaid" and self.render_mermaid:
                    if self._render_mermaid(node[1]):
                        continue
                if language:
                    self._insert(language + "\n", tag_names + ("code_label",))
                self._insert(node[1], tag_names + ("code_block",))
                self._insert("\n\n")
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

    def _render_mermaid(self, source):
        try:
            diagram = MermaidDiagram(source)
        except MermaidParseError:
            return False
        buffer_ = self.get_buffer()
        anchor = buffer_.create_child_anchor(buffer_.get_end_iter())
        self.add_child_at_anchor(diagram, anchor)
        self._embedded_widgets.append(diagram)
        diagram.show()
        self._insert("\n\n")
        return True

    def _register_heading(self, style_name, nodes):
        title = self._plain_text(nodes)
        level = int(style_name[-1])
        base = self._slugify_heading(title)
        count = self._slug_counts.get(base, 0)
        self._slug_counts[base] = count + 1
        anchor = base if count == 0 else "{}-{}".format(base, count)
        mark = self.get_buffer().create_mark(
            None, self.get_buffer().get_end_iter(), True)
        self._anchors[anchor] = mark
        alias = self._anchor_match_key(anchor)
        if alias:
            self._anchors.setdefault(alias, mark)
        self._headings.append((level, title, anchor))

    @staticmethod
    def _slugify_heading(title):
        value = unicodedata.normalize("NFKC", title or "").strip().lower()
        chars = []
        for char in value:
            category = unicodedata.category(char)
            if category[0] in ("L", "N", "M") or char in ("-", "_"):
                chars.append(char)
            elif char.isspace():
                chars.append("-")
        slug = re.sub(r"-+", "-", "".join(chars)).strip("-")
        return slug or "section"

    @staticmethod
    def _anchor_match_key(value):
        normalized = unicodedata.normalize("NFKD", value or "").lower()
        return "".join(
            char for char in normalized
            if unicodedata.category(char)[0] != "M")

    def _render_list(self, nodes, ordered, list_depth):
        index = 0
        for node in nodes:
            if node[0] != "item":
                self._render_nodes([node], (), list_depth + 1)
                continue
            index += 1
            prefix = "{}. ".format(index) if ordered else "- "
            self._insert("  " * list_depth + prefix)
            self._render_nodes(node[1], (), list_depth + 1)
            end = self.get_buffer().get_end_iter()
            if not end.starts_line():
                self._insert("\n")

    def _render_table(self, rows, tag_names, list_depth):
        for row in rows:
            if row[0] != "table_row":
                continue
            cells = []
            for cell in row[1]:
                if cell[0] == "table_cell":
                    cells.append(self._plain_text(cell[1]))
            self._insert(" | ".join(cells) + "\n", tag_names)
        self._insert("\n")

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
        link_tag = buffer_.create_tag(None, underline=Pango.Underline.SINGLE)
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
            if parsed.scheme.lower() in self._ALLOWED_URI_SCHEMES:
                return value
            return None
        if value.startswith("//"):
            return None
        if self.allow_internal_links:
            return value
        if self.base_uri:
            resolved = urljoin(self.base_uri, value)
            if urlparse(resolved).scheme.lower() in self._ALLOWED_URI_SCHEMES:
                return resolved
        return None

    @staticmethod
    def _plain_text(nodes):
        values = []
        for node in nodes:
            if node[0] == "text":
                values.append(node[1])
            elif node[0] in ("span", "block"):
                values.append(MarkdownTextView._plain_text(node[2]))
            elif node[0] == "link":
                values.append(MarkdownTextView._plain_text(node[3]))
        return "".join(values).strip()

    def _on_link_event(self, _tag, _object, event, _iter, uri):
        if (event.type == Gdk.EventType.BUTTON_RELEASE and
                event.button == Gdk.BUTTON_PRIMARY):
            return self._activate_uri(uri)
        return False

    def _on_key_release(self, _view, event):
        if event.keyval not in (Gdk.KEY_Return, Gdk.KEY_KP_Enter):
            return False
        buffer_ = self.get_buffer()
        cursor = buffer_.get_iter_at_mark(buffer_.get_insert())
        for tag in cursor.get_tags():
            uri = self._link_uris.get(tag)
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
