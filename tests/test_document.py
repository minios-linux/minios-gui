import tempfile
from pathlib import Path

import gi
import pytest

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, GLib, Gtk, Pango

from minios_gui.document import DocumentFormatError, DocumentTextView


def document(nodes):
    return {
        "product_kind": "minios-markup-document",
        "schema_version": 1,
        "nodes": nodes,
    }


def buffer_text(view):
    buffer_ = view.get_buffer()
    return buffer_.get_text(
        buffer_.get_start_iter(), buffer_.get_end_iter(), True)


def test_document_renderer_renders_compiled_nodes_directly():
    view = DocumentTextView(document([
        ["heading", 1, "title", [["text", "Title"]]],
        ["block", "paragraph", [
            ["text", "Compiled "],
            ["span", "strong", [["text", "document"]]],
        ]],
    ]))
    assert "Title" in buffer_text(view)
    assert "Compiled document" in buffer_text(view)
    assert view.get_headings() == [(1, "Title", "title")]


def test_document_renderer_reports_heading_at_document_y():
    view = DocumentTextView(document([
        ["heading", 1, "title", [["text", "Title"]]],
        ["block", "paragraph", [["text", "Intro text"]]],
        ["heading", 2, "section", [["text", "Section"]]],
        ["block", "paragraph", [["text", "Section body"]]],
    ]))
    scrolled = Gtk.ScrolledWindow()
    scrolled.add(view)
    window = Gtk.Window()
    window.set_default_size(400, 240)
    window.add(scrolled)
    window.show_all()
    while Gtk.events_pending():
        Gtk.main_iteration()
    try:
        mark = view._anchors["section"]
        iter_ = view.get_buffer().get_iter_at_mark(mark)
        y = view.get_iter_location(iter_).y + 1
        assert view.heading_at_y(y, min_level=2) == (2, "Section", "section")
    finally:
        window.destroy()


def test_document_scroll_to_anchor_aligns_heading_immediately():
    view = DocumentTextView(document([
        ["heading", 1, "title", [["text", "Title"]]],
        ["block", "paragraph", [["text", "Intro\n" * 80]]],
        ["heading", 2, "section", [["text", "Section"]]],
        ["block", "paragraph", [["text", "Body\n" * 80]]],
    ]))
    view.set_top_margin(18)
    scrolled = Gtk.ScrolledWindow()
    scrolled.add(view)
    window = Gtk.Window()
    window.set_default_size(400, 240)
    window.add(scrolled)
    window.show_all()
    while Gtk.events_pending():
        Gtk.main_iteration()
    try:
        adjustment = scrolled.get_vadjustment()
        assert view.scroll_to_anchor("section")
        assert adjustment.get_value() > 0
        mark = view._anchors["section"]
        iter_ = view.get_buffer().get_iter_at_mark(mark)
        heading_y = view.get_iter_location(iter_).y
        viewport_y = heading_y - adjustment.get_value()
        assert abs(viewport_y - (view.get_top_margin() + 4)) <= 1
        assert view.heading_at_y(
            adjustment.get_value() + view.get_top_margin() + 4,
            min_level=2) == (2, "Section", "section")
    finally:
        window.destroy()


def test_document_renderer_hides_text_caret():
    view = DocumentTextView(document([[
        "block", "paragraph", [["text", "Read-only document"]],
    ]]))
    assert not view.get_cursor_visible()


def test_document_renderer_styles_warning_and_danger_admonitions():
    view = DocumentTextView(document([
        ["admonition", "warning", "Warning", [
            ["block", "paragraph", [["text", "Be careful"]]],
        ]],
        ["admonition", "danger", "Danger", [
            ["block", "paragraph", [["text", "Data may be lost"]]],
        ]],
    ]))
    assert len(view._admonition_widgets) == 2
    warning, danger = view._admonition_widgets
    assert warning.get_style_context().has_class(
        "minios-document-admonition-warning")
    assert danger.get_style_context().has_class(
        "minios-document-admonition-danger")
    assert "Be careful" in buffer_text(warning.body)
    assert "Data may be lost" in buffer_text(danger.body)
    assert not buffer_text(warning.body).endswith("\n")
    assert not buffer_text(danger.body).endswith("\n")


def test_document_renderer_keeps_inline_code_on_text_baseline():
    view = DocumentTextView(document([[
        "block", "paragraph", [
            ["text", "Use "],
            ["span", "code", [["text", "live-config"]]],
            ["text", " here."],
        ],
    ]]))
    text = buffer_text(view)
    assert "\u2009live-config\u2009" in text
    assert not view._embedded_widgets
    tag = view._tag("code")
    assert tag.props.family == "monospace"
    assert tag.props.scale == pytest.approx(0.9)
    assert tag.props.foreground_rgba is not None
    assert tag.props.background_rgba is not None


def test_document_renderer_uses_colored_links_with_hover_underline():
    view = DocumentTextView(document([[
        "block", "paragraph", [[
            "link", "https://minios.dev", "", [["text", "MiniOS"]]
        ]],
    ]]))
    iter_ = view.get_buffer().get_iter_at_offset(1)
    tag, uri = view._link_tag_at_iter(iter_)
    assert uri == "https://minios.dev"
    assert view._tag("link").props.underline == Pango.Underline.NONE
    assert view._tag("link").props.foreground_rgba is not None
    assert tag.props.underline == Pango.Underline.NONE
    view._set_hover_link(tag)
    assert tag.props.underline == Pango.Underline.SINGLE
    view._set_hover_link(None)
    assert tag.props.underline == Pango.Underline.NONE


def test_document_renderer_uses_hand_cursor_for_links():
    view = DocumentTextView(document([[
        "block", "paragraph", [[
            "link", "https://minios.dev", "", [["text", "MiniOS"]]
        ]],
    ]]))
    window = Gtk.Window()
    window.add(view)
    window.show_all()
    while Gtk.events_pending():
        Gtk.main_iteration()
    try:
        iter_ = view.get_buffer().get_iter_at_offset(1)
        assert view._link_uri_at_iter(iter_) == "https://minios.dev"
        text_window = view.get_window(Gtk.TextWindowType.TEXT)
        view._set_link_pointer(True)
        assert text_window.get_cursor() == view._link_cursor
        view._set_link_pointer(False)
        assert text_window.get_cursor() == view._text_cursor
    finally:
        window.destroy()


def test_document_renderer_styles_code_block_and_syntax_without_language_label():
    source = "sudo apt-get update"
    view = DocumentTextView(document([[
        "code_block", source, "bash", [
            ["syntax", "sudo", "#6F42C1", "#B392F0"],
            ["syntax", " ", "#24292E", "#E1E4E8"],
            ["syntax", "apt-get", "#032F62", "#9ECBFF"],
            ["syntax", " ", "#24292E", "#E1E4E8"],
            ["syntax", "update", "#032F62", "#9ECBFF"],
        ],
    ]]))
    assert "bash" not in buffer_text(view)
    assert len(view._code_widgets) == 1
    block = view._code_widgets[0]
    assert block.get_text() == source
    markup = block._label.get_label()
    assert "#6F42C1" in markup or "#B392F0" in markup
    assert "#032F62" in markup or "#9ECBFF" in markup


def test_document_code_block_has_copy_button_without_text_caret():
    source = "sudo apt-get update"
    view = DocumentTextView(document([[
        "code_block", source, "bash", [],
    ]]))
    block = view._code_widgets[0]
    assert not block._label.get_selectable()
    assert block._copy_button.get_halign() == Gtk.Align.END
    assert block._copy_button.get_valign() == Gtk.Align.START
    block._copy_to_clipboard()
    assert Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD).wait_for_text() == source
    assert block._copy_button.get_style_context().has_class(
        "minios-code-copy-success")
    assert block._copy_button.get_image().get_icon_name()[0] == (
        "emblem-ok-symbolic")
    GLib.source_remove(block._copy_feedback_source)
    block._copy_feedback_source = 0
    block._reset_copy_feedback()
    assert not block._copy_button.get_style_context().has_class(
        "minios-code-copy-success")
    assert block._copy_button.get_image().get_icon_name()[0] == (
        "edit-copy-symbolic")


def test_document_code_block_tracks_document_width():
    view = DocumentTextView(document([[
        "code_block", "sudo apt-get update", "bash", [],
    ]]))
    view.set_left_margin(24)
    view.set_right_margin(24)
    scrolled = Gtk.ScrolledWindow()
    scrolled.add(view)
    window = Gtk.Window()
    window.set_default_size(600, 300)
    window.add(scrolled)
    window.show_all()
    while Gtk.events_pending():
        Gtk.main_iteration()
    try:
        block = view._code_widgets[0]
        expected = view.get_allocated_width() - 50
        assert abs(block.get_allocated_width() - expected) <= 2
        assert block._label.get_line_wrap_mode() == Pango.WrapMode.WORD_CHAR
    finally:
        window.destroy()


def test_document_renderer_embeds_native_table():
    view = DocumentTextView(document([[
        "table", [
            ["table_row", True, [
                ["table_cell", [["text", "Name"]]],
                ["table_cell", [["text", "Value"]]],
            ]],
            ["table_row", False, [
                ["table_cell", [["text", "MiniOS"]]],
                ["table_cell", [["span", "code", [["text", "GTK3"]]]]],
            ]],
        ],
    ]]))
    assert len(view._embedded_widgets) == 1
    grid = view._embedded_widgets[0]
    assert isinstance(grid, Gtk.Grid)
    labels = [child for child in grid.get_children() if isinstance(child, Gtk.Label)]
    assert len(labels) == 4
    assert sorted(label.get_text() for label in labels) == ["GTK3", "MiniOS", "Name", "Value"]
    assert grid.get_style_context().has_class("minios-document-table")
    assert any(grid.get_style_context().has_class(name) for name in (
        "minios-document-table-light", "minios-document-table-dark"))
    assert all(not label.get_selectable() for label in labels)
    by_text = {label.get_text(): label for label in labels}
    assert by_text["Name"].get_style_context().has_class("minios-table-header")
    assert by_text["Name"].get_style_context().has_class("minios-table-first-column")
    assert by_text["GTK3"].get_style_context().has_class("minios-table-last-row")
    assert by_text["GTK3"].get_style_context().has_class("minios-table-last-column")


def test_document_table_tracks_document_width_and_wraps_cells():
    view = DocumentTextView(document([[
        "table", [
            ["table_row", True, [
                ["table_cell", [["text", "Term"]]],
                ["table_cell", [["text", "Description"]]],
                ["table_cell", [["text", "Added"]]],
                ["table_cell", [["text", "Notes"]]],
            ]],
            ["table_row", False, [
                ["table_cell", [["text", "very-long-unbroken-term"]]],
                ["table_cell", [["text", "A long description " * 12]]],
                ["table_cell", [["text", "6.x"]]],
                ["table_cell", [["text", "A long note " * 10]]],
            ]],
        ],
    ]]))
    view.set_left_margin(24)
    view.set_right_margin(24)
    scrolled = Gtk.ScrolledWindow()
    scrolled.add(view)
    window = Gtk.Window()
    window.set_default_size(600, 400)
    window.add(scrolled)
    window.show_all()
    while Gtk.events_pending():
        Gtk.main_iteration()
    try:
        grid = view._table_widgets[0]
        expected = view.get_allocated_width() - 50
        assert abs(grid.get_allocated_width() - expected) <= 2
        labels = [
            child for child in grid.get_children()
            if isinstance(child, Gtk.Label)
        ]
        assert all(label.get_line_wrap() for label in labels)
        assert all(
            label.get_line_wrap_mode() == Pango.WrapMode.WORD_CHAR
            for label in labels)
    finally:
        window.destroy()


def test_document_renderer_embeds_svg_asset():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        svg = root / "diagram.svg"
        svg.write_text(
            '<svg xmlns="http://www.w3.org/2000/svg" width="40" height="20">'
            '<rect width="40" height="20" fill="black"/></svg>',
            encoding="utf-8")

        view = DocumentTextView(
            document([["diagram", "assets/diagram.svg", "Diagram"]]),
            asset_resolver=lambda _relative: svg)
        view.set_left_margin(24)
        view.set_right_margin(24)
        scrolled = Gtk.ScrolledWindow()
        scrolled.add(view)
        window = Gtk.Window()
        window.set_default_size(400, 300)
        window.add(scrolled)
        window.show_all()
        while Gtk.events_pending():
            Gtk.main_iteration()
        try:
            image = view._asset_widgets[0]
            pixbuf = image.get_pixbuf()
            expected = view.get_allocated_width() - 50
            assert abs(pixbuf.get_width() - expected) <= 2
            assert abs(pixbuf.get_height() * 2 - pixbuf.get_width()) <= 2
            assert image.get_margin_top() == 10
            assert image.get_margin_bottom() == 14
            assert image.get_style_context().has_class("minios-document-diagram")
        finally:
            window.destroy()


def test_document_renderer_rejects_unknown_schema():
    with pytest.raises(DocumentFormatError):
        DocumentTextView({
            "product_kind": "minios-markup-document",
            "schema_version": 99,
            "nodes": [],
        })


def test_localized_document_loader_uses_locale_and_english_fallback(tmp_path):
    import json
    from minios_gui import load_localized_document

    for language, title in (("en", "English"), ("pt-BR", "Brasil")):
        target = tmp_path / language / "help.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(document([
            ["heading", 1, "title", [["text", title]]],
        ])), encoding="utf-8")
    brazil = load_localized_document(
        tmp_path, "help.json", locale_name="pt_BR.UTF-8")
    fallback = load_localized_document(
        tmp_path, "help.json", locale_name="de_DE.UTF-8")
    assert brazil["nodes"][0][3][0][1] == "Brasil"
    assert fallback["nodes"][0][3][0][1] == "English"


def test_document_asset_path_rejects_parent_traversal(tmp_path):
    from minios_gui import document_asset_path

    asset = tmp_path / "assets" / "diagram.svg"
    asset.parent.mkdir()
    asset.write_text("<svg/>", encoding="utf-8")
    assert document_asset_path(tmp_path, "assets/diagram.svg") == asset
    with pytest.raises(ValueError):
        document_asset_path(tmp_path, "../outside.svg")
