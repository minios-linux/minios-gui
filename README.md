# minios-gui

Shared GUI resources for MiniOS graphical applications.

This source repository builds two architecture-independent Debian packages:

- **`minios-gui`** — the canonical GTK 3 application stylesheet;
- **`python3-minios-gui`** — Python 3.6-compatible GTK helpers.

The stylesheet is installed to:

```
/usr/share/minios/minios.css
```

The design and interaction standard lives in this repository:
[MiniOS GUI guidelines](doc/minios-gui-guidelines.md).

## What it provides

`minios.css` is a GTK 3 stylesheet organized into 15 sections: brand tokens,
header bar, sidebar, sidebar steps, typography, content cards, status banners,
buttons, badge pills, lists, entries/validation, progress, footer/action bar,
log view, and drop-zone/empty-state helpers.

Design rules encoded by the sheet:

- **Theme-aware.** Surfaces derive from the running GTK theme
  (`@theme_bg_color`, `@theme_base_color`, `@borders`, `@theme_fg_color`,
  `@theme_selected_bg_color`), so light and dark desktops both work.
- **Brand accent.** Only the primary action (`suggested-action`) and small brand
  accents use the fixed MiniOS blue; destructive actions use the MiniOS red.
- **One vocabulary.** Canonical class names (`minios-headerbar`,
  `minios-sidebar`, `content-card`, `info/warning/error/success-banner`,
  `badge*`, `minios-list`, `minios-footer`, …) replace the per-app variants.
- **Consistent text buttons.** Label-only GTK buttons receive shared 12 px
  horizontal padding automatically; icon+text buttons use
  `minios-text-button`. Emphasized/footer actions use 14 px.

Only the eight semantic brand colors are hard-coded (via `@define-color`);
everything else follows the theme. Action/status icons come from the existing
`elementary-minios-icon-theme`, whose source is maintained in the
`elementary-xfce-minios` repository.

The `minios_gui` Python package provides:

- `apply_minios_css()` / `apply_css()` for deterministic base + app CSS loading;
- `resolve_icon()` / `new_icon()` for safe icon-theme lookup;
- standard informational, error and irreversible-action confirmation dialogs;
- `new_header_bar()` for the canonical MiniOS workspace header;
- `StatusBanner` for reusable info/warning/error/success banners with semantic
  styling and icon handling;
- `classify_module()` / `format_bytes()` for consistent compact module
  presentation across MiniOS graphical tools;
- `TokenCompletionPopover` for token-aware static or asynchronous entry
  completion, anchored visually to the word being completed; arrows choose a
  result and Tab/Enter accept it while Shift+Tab keeps normal focus navigation;
- `HelpPopoverButton` for keyboard-accessible contextual help, from compact
  field explanations to structured page-level guidance with titled sections or
  native Markdown content;
- `MarkdownTextView`, `parse_markdown()` and `load_localized_markdown()` for
  safe native Markdown help without WebKit, including locale fallback, internal
  link callbacks, heading anchors and a non-executable safe HTML subset;
- `MermaidDiagram` and `parse_mermaid_flowchart()` for optional native Mermaid
  flowcharts without JavaScript; unsupported Mermaid remains readable source;
- `LogView`, `CommandRunner` and `CommandDialog` for responsive, cancellable,
  streamed command execution outside the GTK main loop.

## How applications adopt it

The source repository **does not modify any application**. An app opts in by
depending on the relevant binary package and loading shared resources first:

```python
from minios_gui import apply_minios_css

apply_minios_css("/usr/share/minios-installer/style.css")
```

Load order matters: the shared base first, the app sheet second so an app can
still override or add genuinely app-specific widgets.

An application that only loads the stylesheet depends on `minios-gui`. An app
that imports `minios_gui` depends on `python3-minios-gui` (which in turn depends
on the matching `minios-gui` binary version).

Localized Markdown help uses an application-owned document tree:

```python
from minios_gui import HelpPopoverButton, load_localized_markdown

help_text = load_localized_markdown(
    "/usr/share/example-app/help", "settings/storage.md")
help_button = HelpPopoverButton(
    "Storage", markdown=help_text, compact=True)
```

The Markdown document should begin with its own level-one heading. The `title`
argument remains the button's accessible name and fallback tooltip; it is not
duplicated above Markdown content.

The loader tries `LANGUAGE`, `LC_ALL`, `LC_MESSAGES`, and `LANG` in order, then
falls back from a full locale to its language and finally to English. Use
`MarkdownTextView` directly when help belongs in a dialog or permanent page
instead of a popover. Applications that need diagrams can pass
`render_mermaid=True` to `MarkdownTextView` or `HelpPopoverButton`. The Mermaid
renderer executes no script or HTML; it supports native flowcharts and falls
back to the fenced source when syntax is unsupported.

## Build

Standard Debian packaging (`debhelper` compat 11):

```sh
dpkg-buildpackage -us -uc -b
```

Or install both resource groups into a staging tree:

```sh
make install DESTDIR=/path/to/root
```

The build produces `minios-gui_<version>_all.deb` and
`python3-minios-gui_<version>_all.deb`.

## Compatibility

- Python 3.6 and later;
- GTK 3.22 and later;
- Mistune 0.8, 2.x, and 3.x;
- Debian 10–13 and later, equivalent Devuan releases, Ubuntu 18.04–26.04 and
  later.

No dataclasses, assignment expressions, structural matching or GTK 4 APIs are
used by the shared Python package.

## Scope

This is **not** a GTK system theme. It is an application-level stylesheet and
helper library loaded on top of the active GTK theme. The shared MiniOS icon
theme is `elementary-minios-icon-theme`, maintained in the
`elementary-xfce-minios` source repository.
