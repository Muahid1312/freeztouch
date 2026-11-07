"""Optional GTK tests: run inside a display, or skip explicitly on headless hosts."""
import time
import unittest
from unittest.mock import Mock, patch

try:
    from touchswitch.app import Window, Gtk, GLib
    from touchswitch.backend import Device, Session, ControlError
    AVAILABLE = Gtk.init_check()[0]
except (ImportError, ValueError):
    AVAILABLE = False


@unittest.skipUnless(AVAILABLE, 'GTK 3 and a graphical display are required')
class Gui(unittest.TestCase):
    def make_window(self, session='x11', devices=True):
        backend = Mock()
        backend.session = Session('Ubuntu 24.04 LTS', session)
        backend.discover.return_value = [Device('Test panel', '/dev/input/event3', '/sys/test')] if devices else []
        backend.status.return_value = True
        with patch('touchswitch.app.Backend', return_value=backend):
            window = Window()
        self.addCleanup(window.destroy)
        self.addCleanup(setattr, window, 'closed', True)
        self.drain(window)
        return window, backend

    def drain(self, window):
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            while GLib.MainContext.default().pending():
                GLib.MainContext.default().iteration(False)
            if not window.busy:
                return
            time.sleep(.01)
        self.fail('GUI worker did not finish')

    @patch.dict('os.environ', {'DISPLAY': ':98'})
    def test_enabled_device_controls(self):
        window, _ = self.make_window()
        self.assertIn('Enabled', window.indicator.get_text())
        self.assertTrue(window.disable.get_sensitive())
        self.assertFalse(window.enable.get_sensitive())

    def test_no_device_disables_both_actions(self):
        window, _ = self.make_window(devices=False)
        self.assertFalse(window.disable.get_sensitive())
        self.assertFalse(window.enable.get_sensitive())
        self.assertIn('No dedicated touchscreen', window.message.get_text())

    def test_wayland_displays_device_and_limitation(self):
        window, backend = self.make_window(session='wayland')
        self.assertEqual(window.selector.get_active(), 0)
        self.assertIn('Wayland', window.message.get_text())
        self.assertFalse(window.disable.get_sensitive())
        backend.status.assert_not_called()

    @patch.dict('os.environ', {'DISPLAY': ':98'})
    def test_command_error_remains_visible(self):
        window, backend = self.make_window()
        backend.status.side_effect = ControlError('Permission denied')
        window.selection_changed()
        self.drain(window)
        self.assertIn('Permission denied', window.message.get_text())
        self.assertFalse(window.disable.get_sensitive())
        # Enable remains accessible so recovery can be retried.
        self.assertTrue(window.enable.get_sensitive())
