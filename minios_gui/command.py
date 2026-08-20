"""Responsive command execution and streamed output widgets for GTK 3."""

import gettext
import os
import re
import signal
import subprocess
import threading

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import GLib, Gtk


_ = gettext.gettext


_ANSI_RE = re.compile(
    r"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b[@-Z\\-_]|[\x00\x07\x08]")


def format_log_line(message, timestamp=None, level=None):
    """Return one normalized log record with optional metadata prefix."""
    prefix = []
    if timestamp:
        prefix.append("[{}]".format(timestamp))
    if level:
        prefix.append(str(level).upper())
    text = str(message).rstrip("\r\n")
    if prefix:
        text = "{} {}".format(" ".join(prefix), text)
    return text + "\n"


class LogView(Gtk.ScrolledWindow):
    """Read-only monospace output with terminal-style carriage returns."""

    def __init__(self, maximum_characters=None):
        Gtk.ScrolledWindow.__init__(self)
        self.maximum_characters = maximum_characters
        self.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        self.set_hexpand(True)
        self.set_vexpand(True)
        self._textview = Gtk.TextView()
        self._textview.set_editable(False)
        self._textview.set_cursor_visible(False)
        self._textview.set_monospace(True)
        self._textview.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self._textview.set_left_margin(6)
        self._textview.set_right_margin(6)
        self._textview.get_style_context().add_class("log-view")
        self._buffer = self._textview.get_buffer()
        self._line_start = self._buffer.create_mark(
            "line-start", self._buffer.get_end_iter(), True)
        self.add(self._textview)

    @property
    def text_view(self):
        return self._textview

    @property
    def text_buffer(self):
        return self._buffer

    def clear(self):
        self._buffer.set_text("")
        self._buffer.move_mark(self._line_start, self._buffer.get_end_iter())

    def feed(self, text):
        text = _ANSI_RE.sub("", text)
        if not text:
            return False
        for part in re.split(r"(\r\n|\r|\n)", text):
            if not part:
                continue
            if part in ("\n", "\r\n"):
                self._buffer.insert(self._buffer.get_end_iter(), "\n")
                self._buffer.move_mark(
                    self._line_start, self._buffer.get_end_iter())
            elif part == "\r":
                start = self._buffer.get_iter_at_mark(self._line_start)
                self._buffer.delete(start, self._buffer.get_end_iter())
            else:
                self._buffer.insert(self._buffer.get_end_iter(), part)
        self._textview.scroll_to_iter(
            self._buffer.get_end_iter(), 0.0, False, 0.0, 0.0)
        self._trim_history()
        return False

    def append_line(self, message, timestamp=None, level=None):
        """Append one record using the shared metadata layout."""
        return self.feed(format_log_line(message, timestamp, level))

    def _trim_history(self):
        if not self.maximum_characters:
            return
        overflow = self._buffer.get_char_count() - self.maximum_characters
        if overflow <= 0:
            return
        start = self._buffer.get_start_iter()
        end = self._buffer.get_iter_at_offset(overflow)
        self._buffer.delete(start, end)

    def get_text(self):
        return self._buffer.get_text(
            self._buffer.get_start_iter(), self._buffer.get_end_iter(), False)


class CommandRunner(object):
    """Run a subprocess off the GTK main loop and stream combined output."""

    def __init__(self, argv, line_callback, finished_callback, cwd=None,
                 env=None):
        self.argv = argv
        self.line_callback = line_callback
        self.finished_callback = finished_callback
        self.cwd = cwd
        self.env = env
        self._process = None
        self._cancelled = False
        self._lock = threading.Lock()

    def start(self):
        thread = threading.Thread(target=self._worker)
        thread.daemon = True
        thread.start()

    @staticmethod
    def _terminate_process(process):
        if process is None or process.poll() is not None:
            return
        try:
            os.killpg(os.getpgid(process.pid), signal.SIGTERM)
        except (OSError, ProcessLookupError):
            try:
                process.terminate()
            except OSError:
                pass

    def cancel(self):
        with self._lock:
            self._cancelled = True
            process = self._process
        self._terminate_process(process)

    def _worker(self):
        env = self.env.copy() if self.env is not None else os.environ.copy()
        env.setdefault("TERM", "xterm")
        try:
            process = subprocess.Popen(
                self.argv,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                cwd=self.cwd,
                env=env,
                close_fds=True,
                preexec_fn=os.setsid,
            )
        except Exception as error:
            GLib.idle_add(self.line_callback,
                          _("Failed to start: {}\n").format(error))
            GLib.idle_add(self.finished_callback, 127, False)
            return

        with self._lock:
            self._process = process
            cancelled = self._cancelled
        if cancelled:
            self._terminate_process(process)
        while True:
            chunk = process.stdout.readline()
            if not chunk:
                break
            GLib.idle_add(
                self.line_callback, chunk.decode("utf-8", "replace"))
        process.wait()
        process.stdout.close()
        with self._lock:
            self._process = None
        GLib.idle_add(
            self.finished_callback, process.returncode, self._cancelled)


class CommandDialog(Gtk.Dialog):
    """Modal progress dialog with streamed output and safe cancellation."""

    def __init__(self, parent, title, argv, description=None,
                 finished_callback=None, cwd=None, env=None):
        Gtk.Dialog.__init__(
            self, title=title, transient_for=parent, modal=True,
            destroy_with_parent=True)
        self.set_default_size(700, 480)
        self._argv = argv
        self._cwd = cwd
        self._env = env
        self._finished_callback = finished_callback
        self._finished = False
        self._runner = None

        content = self.get_content_area()
        content.set_spacing(8)
        content.set_margin_top(12)
        content.set_margin_bottom(12)
        content.set_margin_start(12)
        content.set_margin_end(12)

        if description:
            label = Gtk.Label(label=description, xalign=0)
            label.set_line_wrap(True)
            content.pack_start(label, False, False, 0)

        command = Gtk.Label(label="$ " + " ".join(argv), xalign=0)
        command.set_selectable(True)
        command.set_line_wrap(True)
        command.get_style_context().add_class("command-line")
        content.pack_start(command, False, False, 0)

        status = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self._spinner = Gtk.Spinner()
        status.pack_start(self._spinner, False, False, 0)
        self._status_label = Gtk.Label(label=_("Working..."), xalign=0)
        status.pack_start(self._status_label, True, True, 0)
        content.pack_start(status, False, False, 0)

        self.log_view = LogView()
        content.pack_start(self.log_view, True, True, 0)
        self._cancel_button = self.add_button(
            _("Cancel"), Gtk.ResponseType.CANCEL)
        self._close_button = self.add_button(_("Close"), Gtk.ResponseType.CLOSE)
        self._close_button.set_sensitive(False)
        self.connect("response", self._on_response)
        self.connect("delete-event", self._on_delete_event)

    def start(self):
        self.show_all()
        self._spinner.start()
        self._runner = CommandRunner(
            self._argv, self.log_view.feed, self._on_finished,
            cwd=self._cwd, env=self._env)
        self._runner.start()

    def _on_finished(self, returncode, cancelled):
        self._finished = True
        succeeded = returncode == 0 and not cancelled
        self._spinner.stop()
        self._cancel_button.set_sensitive(False)
        self._close_button.set_sensitive(True)
        self._close_button.grab_focus()
        if cancelled:
            self._status_label.set_text(_("Cancelled."))
        elif succeeded:
            self._status_label.set_text(_("Completed successfully."))
        else:
            self._status_label.set_text(
                _("Failed (exit code {}).").format(returncode))
        if self._finished_callback is not None:
            self._finished_callback(succeeded)
        return False

    def _on_response(self, _dialog, response):
        if response == Gtk.ResponseType.CLOSE or self._finished:
            self.destroy()
        elif response == Gtk.ResponseType.CANCEL and self._runner is not None:
            self._status_label.set_text(_("Cancelling..."))
            self._cancel_button.set_sensitive(False)
            self._runner.cancel()

    def _on_delete_event(self, _widget, _event):
        if self._finished:
            return False
        if self._runner is not None:
            self._runner.cancel()
        return True
