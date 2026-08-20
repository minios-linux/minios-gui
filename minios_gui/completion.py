"""Reusable token-aware completion popover for GTK 3 entries."""

import threading

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, GLib, Gtk, Pango


def _token_bounds(text, cursor, delimiters=None):
    cursor = max(0, min(int(cursor), len(text)))
    if delimiters is None:
        start = cursor
        while start > 0 and not text[start - 1].isspace():
            start -= 1
        end = cursor
        while end < len(text) and not text[end].isspace():
            end += 1
        return text[start:cursor], start, end, cursor

    separators = set(delimiters)
    start = cursor
    while start > 0 and text[start - 1] not in separators:
        start -= 1
    end = cursor
    while end < len(text) and text[end] not in separators:
        end += 1
    while start < cursor and text[start].isspace():
        start += 1
    while end > start and text[end - 1].isspace():
        end -= 1
    return text[start:cursor], start, end, cursor


class TokenCompletionPopover(object):
    """Complete only the token surrounding the cursor in a Gtk.Entry."""

    def __init__(self, entry, items=None, provider=None, delimiters=None,
                 min_chars=1, max_results=12, append_text="", aliases=None):
        if (items is None) == (provider is None):
            raise ValueError("provide exactly one of items or provider")
        self.entry = entry
        self.items = tuple(sorted(set(items or ())))
        self.provider = provider
        self.delimiters = delimiters
        self.min_chars = int(min_chars)
        self.max_results = int(max_results)
        self.append_text = append_text or ""
        self.aliases = aliases
        self._request = 0

        self.popover = Gtk.Popover.new(entry)
        self.popover.set_position(Gtk.PositionType.BOTTOM)
        self.popover.set_modal(False)
        self.listbox = Gtk.ListBox()
        self.listbox.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.listbox.set_activate_on_single_click(True)
        self.listbox.connect("row-activated", self._row_activated)
        self.popover.add(self.listbox)

        entry.connect("changed", self._changed)
        entry.connect("key-press-event", self._key_press)
        entry.connect("unmap", lambda _entry: self.popover.popdown())
        entry._minios_token_completion = self

    def token(self):
        return _token_bounds(
            self.entry.get_text(), self.entry.get_position(), self.delimiters)

    def _changed(self, _entry):
        self._request += 1
        request = self._request
        GLib.idle_add(self._start_request, request)

    def _start_request(self, request):
        if request != self._request:
            return False
        prefix, _start, _end, _cursor = self.token()
        if len(prefix) < self.min_chars:
            self.popover.popdown()
            return False
        if self.provider is None:
            self._apply(request, prefix, self._filter_items(prefix))
            return False
        thread = threading.Thread(
            target=self._provider_worker, args=(request, prefix))
        thread.daemon = True
        thread.start()
        return False

    def _provider_worker(self, request, prefix):
        try:
            values = tuple(self.provider(prefix) or ())
        except Exception:
            values = ()
        GLib.idle_add(self._apply, request, prefix, values)

    def _filter_items(self, prefix):
        matches = []
        for candidate in self.items:
            aliases = self.aliases(candidate) if self.aliases else (candidate,)
            if any(value.startswith(prefix) for value in aliases if value):
                matches.append(candidate)
                if len(matches) >= self.max_results:
                    break
        return tuple(matches)

    def _apply(self, request, prefix, values):
        if request != self._request:
            return False
        current, _start, _end, _cursor = self.token()
        if current != prefix or not self.entry.get_mapped():
            return False
        for child in self.listbox.get_children():
            self.listbox.remove(child)
        for candidate in tuple(values)[:self.max_results]:
            row = Gtk.ListBoxRow()
            row.completion_value = candidate
            label = Gtk.Label(label=candidate, xalign=0)
            label.set_margin_top(4)
            label.set_margin_bottom(4)
            label.set_margin_start(8)
            label.set_margin_end(8)
            row.add(label)
            self.listbox.add(row)
        if not values:
            self.popover.popdown()
            return False
        self._point_to_token()
        self.popover.show_all()
        self.popover.popup()
        return False

    def _point_to_token(self):
        _prefix, start, _end, cursor = self.token()
        text = self.entry.get_text()
        layout = self.entry.get_layout()
        offset_x, offset_y = self.entry.get_layout_offsets()
        start_index = len(text[:start].encode("utf-8"))
        cursor_index = len(text[:cursor].encode("utf-8"))
        start_rect = layout.index_to_pos(start_index)
        cursor_rect = layout.index_to_pos(cursor_index)
        left = offset_x + int(start_rect.x / Pango.SCALE)
        right = offset_x + int(cursor_rect.x / Pango.SCALE)
        top = offset_y + int(start_rect.y / Pango.SCALE)
        height = max(1, int(start_rect.height / Pango.SCALE))
        rectangle = Gdk.Rectangle()
        rectangle.x = min(left, right)
        rectangle.y = top
        rectangle.width = max(1, abs(right - left))
        rectangle.height = height
        self.popover.set_pointing_to(rectangle)

    def _row_activated(self, _listbox, row):
        value = getattr(row, "completion_value", None)
        if value:
            self.insert(value)

    def insert(self, candidate):
        prefix, start, end, _cursor = self.token()
        if not prefix:
            return
        text = self.entry.get_text()
        suffix = text[end:]
        replacement = candidate
        if self.append_text and not suffix.startswith(self.append_text):
            replacement += self.append_text
        self.entry.set_text(text[:start] + replacement + suffix)
        self.entry.set_position(start + len(replacement))
        self.popover.popdown()

    def _key_press(self, _entry, event):
        if not self.popover.get_visible():
            return False
        if event.keyval == Gdk.KEY_Escape:
            self.popover.popdown()
            return True
        if event.keyval in (Gdk.KEY_Down, Gdk.KEY_Up):
            rows = self.listbox.get_children()
            if not rows:
                return False
            selected = self.listbox.get_selected_row()
            index = selected.get_index() if selected is not None else -1
            if event.keyval == Gdk.KEY_Down:
                index = min(len(rows) - 1, index + 1)
            else:
                index = max(0, index - 1 if index >= 0 else len(rows) - 1)
            self.listbox.select_row(rows[index])
            return True
        if event.keyval == Gdk.KEY_Tab and not (event.state & Gdk.ModifierType.SHIFT_MASK):
            row = self.listbox.get_selected_row() or self.listbox.get_row_at_index(0)
            if row is not None:
                self.insert(row.completion_value)
                return True
        if event.keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter):
            row = self.listbox.get_selected_row() or self.listbox.get_row_at_index(0)
            if row is not None:
                self.insert(row.completion_value)
                return True
        return False
