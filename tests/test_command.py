import unittest
from unittest import mock

from minios_gui.command import CommandRunner, format_log_line


class CommandRunnerTests(unittest.TestCase):
    def test_format_log_line_uses_shared_metadata_order(self):
        self.assertEqual(
            format_log_line("message\n", timestamp="12:34:56", level="warn"),
            "[12:34:56] WARN message\n")

    def test_cancel_requested_before_popen_is_applied_after_start(self):
        results = []
        process = mock.Mock()
        process.pid = 1234
        process.poll.return_value = None
        process.stdout.readline.return_value = b''
        process.wait.return_value = -15
        process.returncode = -15

        def idle_add(callback, *args):
            callback(*args)
            return 1

        runner = CommandRunner(
            ['/bin/true'], lambda _line: None,
            lambda returncode, cancelled: results.append((returncode, cancelled)))
        runner.cancel()
        with mock.patch('minios_gui.command.subprocess.Popen', return_value=process), \
                mock.patch.object(CommandRunner, '_terminate_process') as terminate, \
                mock.patch('minios_gui.command.GLib.idle_add', side_effect=idle_add):
            runner._worker()

        terminate.assert_called_once_with(process)
        self.assertEqual(results, [(-15, True)])

    def test_runner_streams_output_and_reports_success(self):
        lines = []
        results = []

        def idle_add(callback, *args):
            callback(*args)
            return 1

        runner = CommandRunner(
            ["/bin/sh", "-c", "printf 'hello\\n'"],
            lines.append,
            lambda returncode, cancelled: results.append(
                (returncode, cancelled)),
        )
        with mock.patch(
                "minios_gui.command.GLib.idle_add", side_effect=idle_add):
            runner._worker()

        self.assertEqual(lines, ["hello\n"])
        self.assertEqual(results, [(0, False)])


if __name__ == "__main__":
    unittest.main()
