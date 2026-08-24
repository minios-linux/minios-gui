"""Shared GTK 3 helpers for MiniOS graphical applications.

The public API intentionally uses syntax available in Python 3.6 and GTK 3.22.
"""

from .command import CommandDialog, CommandRunner, LogView, format_log_line
from .completion import TokenCompletionPopover
from .dialogs import ask_confirmation, show_error_dialog, show_info_dialog
from .markdown import MarkdownTextView, load_localized_markdown, parse_markdown
from .mermaid import MermaidDiagram, MermaidParseError, parse_mermaid_flowchart
from .module_display import classify_module, format_bytes
from .style import (
    SHARED_CSS_PATH,
    apply_css,
    apply_minios_css,
    new_icon,
    resolve_icon,
)
from .widgets import HelpPopoverButton, StatusBanner, new_header_bar

__version__ = "1.2.0"

__all__ = (
    "SHARED_CSS_PATH",
    "CommandDialog",
    "CommandRunner",
    "HelpPopoverButton",
    "LogView",
    "MarkdownTextView",
    "MermaidDiagram",
    "MermaidParseError",
    "StatusBanner",
    "TokenCompletionPopover",
    "apply_css",
    "classify_module",
    "apply_minios_css",
    "ask_confirmation",
    "format_bytes",
    "format_log_line",
    "load_localized_markdown",
    "new_header_bar",
    "new_icon",
    "parse_markdown",
    "parse_mermaid_flowchart",
    "resolve_icon",
    "show_error_dialog",
    "show_info_dialog",
)
