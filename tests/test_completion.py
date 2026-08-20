import unittest

import gi

gi.require_version('Gtk', '3.0')
from gi.repository import Gdk, Gtk

from minios_gui.completion import TokenCompletionPopover, _token_bounds


def _gtk_available():
    initialized = Gtk.init_check([])
    return initialized[0] if isinstance(initialized, tuple) else initialized


class CompletionTests(unittest.TestCase):
    def test_token_bounds_support_whitespace_and_delimiters(self):
        self.assertEqual(_token_bounds('curl git', 6), ('g', 5, 8, 6))
        self.assertEqual(
            _token_bounds('foo, bar', 8, ','), ('bar', 5, 8, 8))

    def test_static_completion_can_match_candidate_aliases(self):
        if not _gtk_available():
            self.skipTest('GTK display is unavailable')
        entry = Gtk.Entry()
        helper = TokenCompletionPopover(
            entry, items=('ssh.service', 'cron.service'), delimiters=',',
            aliases=lambda value: (value, value[:-8]))
        self.assertEqual(helper._filter_items('ssh'), ('ssh.service',))

    def test_popover_points_to_current_token(self):
        if not _gtk_available():
            self.skipTest('GTK display is unavailable')
        window = Gtk.Window()
        entry = Gtk.Entry()
        window.add(entry)
        window.show_all()
        while Gtk.events_pending():
            Gtk.main_iteration_do(False)
        helper = TokenCompletionPopover(entry, items=('chromium', 'curl'))
        positions = []
        for text, cursor in (('chr', 3), ('curl chr', 8)):
            entry.set_text(text)
            entry.set_position(cursor)
            helper._point_to_token()
            _ok, rectangle = helper.popover.get_pointing_to()
            positions.append((rectangle.x, rectangle.width))
        self.assertGreater(positions[1][0], positions[0][0])
        self.assertGreater(positions[0][1], 1)
        window.destroy()

    def test_tab_accepts_first_visible_completion(self):
        if not _gtk_available():
            self.skipTest('GTK display is unavailable')
        window = Gtk.Window()
        entry = Gtk.Entry()
        window.add(entry)
        window.show_all()
        helper = TokenCompletionPopover(
            entry, items=('chromium', 'chromium-common'), append_text=' ')
        entry.set_text('chr')
        entry.set_position(3)
        request = helper._request
        helper._apply(request, 'chr', ('chromium', 'chromium-common'))
        event = type('Event', (), {'keyval': Gdk.KEY_Tab, 'state': 0})()
        self.assertTrue(helper._key_press(entry, event))
        self.assertEqual(entry.get_text(), 'chromium ')
        window.destroy()

    def test_arrow_selection_stays_in_entry_and_tab_accepts_selected_row(self):
        if not _gtk_available():
            self.skipTest('GTK display is unavailable')
        window = Gtk.Window()
        entry = Gtk.Entry()
        window.add(entry)
        window.show_all()
        entry.grab_focus()
        helper = TokenCompletionPopover(
            entry, items=('chromium', 'chromium-common', 'chromium-driver'),
            append_text=' ')
        entry.set_text('chr')
        entry.set_position(3)
        request = helper._request
        helper._apply(
            request, 'chr', ('chromium', 'chromium-common', 'chromium-driver'))
        down = type('Event', (), {'keyval': Gdk.KEY_Down, 'state': 0})()
        self.assertTrue(helper._key_press(entry, down))
        self.assertTrue(helper._key_press(entry, down))
        self.assertEqual(
            helper.listbox.get_selected_row().completion_value,
            'chromium-common')
        tab = type('Event', (), {'keyval': Gdk.KEY_Tab, 'state': 0})()
        self.assertTrue(helper._key_press(entry, tab))
        self.assertEqual(entry.get_text(), 'chromium-common ')
        window.destroy()

    def test_shift_tab_keeps_normal_focus_navigation(self):
        if not _gtk_available():
            self.skipTest('GTK display is unavailable')
        window = Gtk.Window()
        entry = Gtk.Entry()
        window.add(entry)
        window.show_all()
        helper = TokenCompletionPopover(entry, items=('chromium',))
        entry.set_text('chr')
        entry.set_position(3)
        request = helper._request
        helper._apply(request, 'chr', ('chromium',))
        event = type('Event', (), {
            'keyval': Gdk.KEY_Tab, 'state': Gdk.ModifierType.SHIFT_MASK})()
        self.assertFalse(helper._key_press(entry, event))
        self.assertEqual(entry.get_text(), 'chr')
        window.destroy()


if __name__ == '__main__':
    unittest.main()
