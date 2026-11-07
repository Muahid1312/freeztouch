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
        backend.blocked_key = None
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

    @patch('touchswitch.wayland.installation_error', return_value='Wayland helper installation required')
    def test_wayland_displays_device_and_limitation(self, _):
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

    @patch('touchswitch.wayland.installation_error', return_value='')
    def test_wayland_helper_ready_enables_disable_control(self, _):
        window, backend = self.make_window(session='wayland')
        self.assertIn('Not blocked by TouchSwitch', window.indicator.get_text())
        self.assertTrue(window.disable.get_sensitive())
        self.assertFalse(window.enable.get_sensitive())
        self.assertIsNone(backend.blocked_key)

    @patch('touchswitch.wayland.installation_error', return_value='')
    @patch('touchswitch.wayland.send')
    def test_wayland_block_confirm_enable_uses_same_helper(self, send, _):
        window, backend = self.make_window(session='wayland')
        process = Mock()
        process.stdin.closed = False
        window.process = process
        window.trial_device = window.selected()
        window.trial_event({'event': 'disabled', 'seconds': 15})
        self.assertIn('Touch input blocked', window.indicator.get_text())
        self.assertEqual(backend.blocked_key, window.selected().key)
        window.trial_event({'event': 'kept'})
        self.assertIs(window.process, process)
        self.assertFalse(window.keep.get_visible())
        window.heartbeat()
        send.assert_called_with(process, b'PING\n')
        window.enable_selected()
        send.assert_called_with(process, b'RELEASE\n')
        process.stdin.close.assert_called_once()
        window.trial_event({'event': 'restored', 'reason': 'enabled by user'})
        self.assertIsNone(backend.blocked_key)
        self.assertIn('Not blocked', window.indicator.get_text())

    @patch('touchswitch.wayland.installation_error', return_value='')
    def test_wayland_denial_never_reports_blocked(self, _):
        window, backend = self.make_window(session='wayland')
        window.trial_event({'event': 'error', 'message': 'Permission denied'})
        self.assertIsNone(backend.blocked_key)
        self.assertIn('Status unavailable', window.indicator.get_text())
        window.trial_finished(126, 'Authorization denied')
        self.drain(window)
        self.assertIsNone(backend.blocked_key)
        self.assertIn('Authorization denied', window.message.get_text())
        self.assertNotIn('Touch input blocked', window.indicator.get_text())

    @patch('touchswitch.wayland.installation_error', return_value='')
    @patch('touchswitch.wayland.send')
    def test_keyboard_confirmation_waits_for_helper_ack(self, send, _):
        from types import SimpleNamespace
        from touchswitch.app import Gdk
        window, _ = self.make_window(session='wayland')
        window.process = Mock()
        window.trial_device = window.selected()
        window.trial_event({'event': 'disabled', 'seconds': 15})
        self.assertIn('Keep touchscreen disabled', window.keep.get_label())
        self.assertIn('15s', window.keep.get_label())
        # Explicit key handling works even when clicked has no current GDK event.
        with patch('touchswitch.app.Gtk.get_current_event', return_value=None):
            self.assertTrue(window.confirm_key(window.keep, SimpleNamespace(keyval=Gdk.KEY_space)))
        send.assert_called_once_with(window.process, b'KEEP\n')
        self.assertTrue(window.confirmation_pending)
        self.assertGreater(window.deadline, 0)
        self.assertFalse(window.session_confirmed)
        window.trial_event({'event': 'kept', 'confirmed': True, 'trial_remaining': None})
        self.assertEqual(window.deadline, 0)
        self.assertTrue(window.session_confirmed)
        self.assertFalse(window.keep.get_visible())

    @patch('touchswitch.wayland.installation_error', return_value='')
    @patch('touchswitch.wayland.send')
    def test_mouse_confirmation_accepts_mouse_and_rejects_touch(self, send, _):
        from touchswitch.app import Gdk
        window, _ = self.make_window(session='wayland')
        window.process = Mock()
        window.trial_device = window.selected()
        window.trial_event({'event': 'disabled', 'seconds': 15})
        event = Mock(button=1)
        event.get_source_device.return_value.get_source.return_value = Gdk.InputSource.TOUCHSCREEN
        window.confirm_pointer(window.keep, event)
        send.assert_not_called()
        event.get_source_device.return_value.get_source.return_value = Gdk.InputSource.MOUSE
        window.confirm_pointer(window.keep, event)
        send.assert_called_once_with(window.process, b'KEEP\n')

    @patch('touchswitch.wayland.installation_error', return_value='')
    def test_gui_helper_roundtrip_confirmed_past_15s_and_later_disable(self, _):
        self.run_helper_roundtrip(confirm=True, repeat=True)

    @patch('touchswitch.wayland.installation_error', return_value='')
    def test_gui_helper_roundtrip_unconfirmed_expires_at_15s(self, _):
        self.run_helper_roundtrip(confirm=False)

    def run_helper_roundtrip(self, confirm, repeat=False):
        """Actual helper parser/timer and GUI callbacks; only kernel/time/transport mocked."""
        from types import SimpleNamespace
        from test_evdev_helper import helper
        from touchswitch.app import Gdk
        window, _ = self.make_window(session='wayland')

        def run_once(first):
            now = [0.0]
            queued = []
            current = [b'']
            process = Mock()
            process.stdin.closed = False
            window.process = process
            window.trial_device = window.selected()
            ioctl, close = Mock(), Mock()
            events = []

            def send_command(process, command):
                queued.append(command)

            def received(event):
                events.append(event)
                window.trial_event(event)
                if event['event'] == 'disabled':
                    if first and confirm:
                        window.confirm_key(window.keep, SimpleNamespace(keyval=Gdk.KEY_Return))
                    elif not first:
                        self.assertFalse(window.keep.get_visible())

            def poll(*args):
                now[0] += args[-1]
                if now[0] > 16:
                    # A live confirmed grab must survive the original deadline.
                    ioctl.assert_called_once_with(55, helper.EVIOCGRAB, 1)
                    close.assert_not_called()
                    self.assertTrue(window.helper_confirmed)
                    self.assertEqual(window.deadline, 0)
                    window.enable_selected()
                elif not queued:
                    window.heartbeat()
                current[0] = queued.pop(0)
                return [0], [], []

            with patch('touchswitch.wayland.send', side_effect=send_command), patch('time.monotonic', side_effect=lambda: now[0]):
                helper.own_grab(55, Mock(pidfd=99), send=received,
                                clock=lambda: now[0], poll=poll,
                                read=lambda fd, count: current[0], ioctl=ioctl, close=close)
            if confirm:
                self.assertGreater(now[0], 16)
                self.assertEqual(events[-1]['reason'], 'enabled by user')
                self.assertTrue(window.session_confirmed)
            else:
                self.assertEqual(now[0], 15)
                self.assertEqual(events[-1]['reason'], '15-second trial expired')
                self.assertFalse(window.session_confirmed)
            close.assert_called_once_with(55)
            self.assertIsNone(window.backend.blocked_key)
            self.assertIn('Not blocked', window.indicator.get_text())
            return events

        run_once(first=True)
        if repeat:
            # A fresh helper still needs KEEP; the GUI sends it without another trial UI.
            run_once(first=False)
