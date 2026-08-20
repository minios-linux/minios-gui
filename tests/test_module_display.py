import unittest

from minios_gui import classify_module, format_bytes


class ModuleDisplayTests(unittest.TestCase):
    def test_classifies_standard_module_roles(self):
        cases = {
            '00-core-amd64.sb': 'core',
            '01-kernel-6.12-amd64.sb': 'kernel',
            '02-firmware-amd64.sb': 'firmware',
            '03-gui-base-amd64.sb': 'gui-base',
            '04-xfce-desktop-amd64.sb': 'desktop',
            '05-toolbox-amd64.sb': 'toolbox',
            '06-firefox-amd64.sb': 'browser',
            '90-custom.sb': 'custom',
        }
        for name, expected in cases.items():
            role, icons = classify_module(name)
            self.assertEqual(role, expected)
            self.assertTrue(icons)

    def test_formats_compact_byte_sizes(self):
        self.assertIsNone(format_bytes(None))
        self.assertEqual(format_bytes(1024), '1 KiB')
        self.assertEqual(format_bytes(4 * 1024 * 1024), '4 MiB')
        self.assertEqual(format_bytes(3 * 1024 ** 3), '3.0 GiB')


if __name__ == '__main__':
    unittest.main()
