import re
from pathlib import Path


CSS = (Path(__file__).resolve().parents[1] / "share/minios.css").read_text(
    encoding="utf-8")


def css_declarations(selector):
    match = re.search(rf"{re.escape(selector)}\s*\{{([^}}]+)\}}", CSS)
    assert match, f"missing CSS rule for {selector}"
    return {
        name.strip(): value.strip()
        for name, value in re.findall(
            r"([\w-]+)\s*:\s*([^;]+);", match.group(1))
    }


def test_text_buttons_have_shared_horizontal_padding():
    assert "button.text-button,\n.minios-text-button {\n    padding-left: 12px;\n    padding-right: 12px;\n}" in CSS
    assert "button.suggested-action,\nbutton.destructive-action," in CSS
    assert "padding-left: 14px;" in CSS
    assert "padding-right: 14px;" in CSS


def test_help_title_is_larger_than_section_titles():
    assert css_declarations(".minios-help-title")["font-size"] == "20px"
    assert css_declarations(".section-title")["font-size"] == "15px"


def test_manager_state_row_content_css_contract():
    declarations = css_declarations(".manager-state-row-content")

    assert declarations["padding"] == "12px 16px"
    assert declarations["min-height"] == "80px"


def test_manager_state_edges_use_shared_semantic_tokens():
    assert css_declarations(".row-status-active")["border-left"] == (
        "3px solid @minios_active_edge")
    assert "@define-color minios_active_edge #73d216;" in CSS
    assert css_declarations(".row-status-running")["border-left"] == (
        "3px solid @minios_amber")
    assert css_declarations(".row-status-available")["border-left"] == (
        "3px solid alpha(@theme_fg_color, 0.25)")


def test_document_renderer_owns_base_surface_and_nested_notice_transparency():
    base = css_declarations(
        ".minios-document-view,\n.minios-document-view text")
    assert base["background-color"] == "@theme_base_color"
    body = css_declarations(
        ".minios-document-admonition-body,\n.minios-document-admonition-body text")
    assert body["background-color"] == "transparent"


def test_document_code_copy_button_is_compact():
    declarations = css_declarations(".minios-code-copy-button")
    assert declarations["min-width"] == "24px"
    assert declarations["min-height"] == "24px"
    assert declarations["border-radius"] == "4px"
    assert "@minios_green" in css_declarations(
        ".minios-code-copy-success,\n.minios-code-copy-success image")["color"]


def test_document_tables_match_code_block_surface_language():
    declarations = css_declarations(".minios-document-table")
    assert declarations["border-radius"] == "8px"
    assert declarations["border"] == "1px solid alpha(@borders, 0.60)"
    assert css_declarations(
        ".minios-document-table-light")["background-color"] == "#f6f6f7"
    assert css_declarations(
        ".minios-document-table-dark")["background-color"] == "#161618"
    cell = css_declarations(".minios-table-cell")
    assert cell["padding"] == "7px 10px"
    assert cell["border-right"] == "1px solid alpha(@borders, 0.35)"
    assert cell["border-bottom"] == "1px solid alpha(@borders, 0.35)"


def test_document_admonitions_are_compact_framed_notices():
    declarations = css_declarations(".minios-document-admonition")
    assert declarations["margin-top"] == "6px"
    assert declarations["margin-bottom"] == "10px"
    assert declarations["padding"] == "9px 12px"
    assert declarations["border-width"] == "1px 1px 1px 4px"
    assert declarations["border-radius"] == "6px"
    assert css_declarations(
        ".minios-document-admonition-title")["font-weight"] == "bold"
    assert css_declarations(
        ".minios-document-admonition-warning")["background-color"] == (
            "alpha(@minios_amber, 0.10)")
    assert css_declarations(
        ".minios-document-admonition-danger")["background-color"] == (
            "alpha(@minios_red, 0.08)")
