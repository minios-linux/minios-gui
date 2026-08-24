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
