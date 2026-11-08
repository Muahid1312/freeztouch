"""No real input nodes are opened or grabbed by these tests."""
import errno
import importlib.machinery
import importlib.util
import os
from pathlib import Path
import stat
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from touchswitch.backend import Device
from touchswitch.wayland import identity_token, helper_command, send

SOURCE = Path(__file__).resolve().parent.parent / 'privileged/touchswitch-helper'
loader = importlib.machinery.SourceFileLoader('evdev_helper', str(SOURCE))
spec = importlib.util.spec_from_loader(loader.name, loader)
helper = importlib.util.module_from_spec(spec)
loader.exec_module(helper)


class Validation(unittest.TestCase):
    def test_finger_touchscreen_accepted(self):
        helper.validate_capabilities({0, 1, 3}, {330, 325}, {0x2f, 0x35, 0x36, 0x39}, {1})
        helper.validate_udev({'DEVNAME': '/dev/input/event42', 'ID_INPUT_TOUCHSCREEN': '1'},
                             '/dev/input/event42', 'seat0')

    def test_rejects_keyboard_mouse_touchpad_and_mixed_udev(self):
        for kind in helper.REJECT:
            with self.subTest(kind=kind), self.assertRaises(helper.UnsafeDevice):
                helper.validate_udev({'DEVNAME': '/dev/input/event42', 'ID_INPUT_TOUCHSCREEN': '1',
                                      'ID_INPUT_' + kind: '1'}, '/dev/input/event42', 'seat0')

    def test_rejects_missing_classification_wrong_node_and_seat(self):
        for props in ({'DEVNAME': '/dev/input/event42'},
                      {'DEVNAME': '/dev/input/event9', 'ID_INPUT_TOUCHSCREEN': '1'},
                      {'DEVNAME': '/dev/input/event42', 'ID_INPUT_TOUCHSCREEN': '1', 'ID_SEAT': 'seat1'}):
            with self.subTest(props=props), self.assertRaises(helper.UnsafeDevice):
                helper.validate_udev(props, '/dev/input/event42', 'seat0')

    def test_rejects_mixed_kernel_capabilities(self):
        for events, keys, axes, props in (
            ({0, 1, 2, 3}, {330}, {0, 1}, {1}),  # Relative mouse movement.
            ({0, 1, 3}, {30, 330}, {0, 1}, {1}),  # KEY_A.
            ({0, 1, 3}, {272, 330}, {0, 1}, {1}),  # BTN_LEFT.
            ({0, 1, 3}, {320, 330}, {0, 1}, {1}),  # Pen.
            ({0, 1, 3}, {330}, {0, 1}, {0, 1}),  # Pointer/touchpad.
            ({0, 1, 3}, {330}, {0, 1}, set()),
            ({0, 1, 3}, {330}, {0x18}, {1}),
            ({0, 1, 3}, {330}, {0, 1, 3}, {1}),  # Unrelated ABS_RX.
            ({0, 1, 3, 5}, {330}, {0, 1}, {1}),  # Switches.
        ):
            with self.subTest(events=events, keys=keys, axes=axes, props=props), self.assertRaises(helper.UnsafeDevice):
                helper.validate_capabilities(events, keys, axes, props)

    def test_identity_is_opaque_and_not_hardcoded_to_event_number(self):
        for event in ('event8', 'event42'):
            path = '/sys/devices/test/input/' + event
            device = Device('Wacom HID 48CA Finger', '/dev/input/' + event, path)
            self.assertEqual(identity_token(device), helper.token_for(path, device.name))
        with self.assertRaises(helper.UnsafeDevice):
            helper.open_verified('/dev/input/event8', 'seat0')

    def test_open_verifies_fd_and_rejects_mismatched_rdev(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            event = root / 'event42'
            (event / 'device').mkdir(parents=True)
            (event / 'device/name').write_text('Wacom HID 48CA Finger')
            (event / 'dev').write_text('13:99')
            token = helper.token_for(str(event), 'Wacom HID 48CA Finger')
            props = {'DEVNAME': '/dev/input/event42', 'ID_INPUT_TOUCHSCREEN': '1'}
            info = SimpleNamespace(st_mode=stat.S_IFCHR, st_rdev=os.makedev(13, 42))
            with patch.object(helper, 'udev_properties', return_value=props), patch.object(helper.os, 'open', return_value=55) as opened, patch.object(helper.os, 'fstat', return_value=info), patch.object(helper.os, 'close') as close:
                with self.assertRaisesRegex(helper.UnsafeDevice, 'identity changed'):
                    helper.open_verified(token, 'seat0', root)
                self.assertEqual(opened.call_args.args[0], '/dev/input/event42')
                self.assertTrue(opened.call_args.args[1] & os.O_NOFOLLOW)
                close.assert_called_once_with(55)

    def test_unrelated_identity_never_opens_any_path(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(helper.os, 'open') as opened:
            with self.assertRaises(helper.UnsafeDevice):
                helper.open_verified('0' * 64, 'seat0', Path(tmp))
            opened.assert_not_called()

    def test_unsafe_installation_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'helper'
            path.write_text('not root owned')
            with self.assertRaises(helper.UnsafeDevice):
                helper.trusted_file(path)


class GrabLifecycle(unittest.TestCase):
    def setUp(self):
        self.guard = Mock(pidfd=99)
        self.guard.alive.return_value = True
        self.now = 0.0
        self.mono = 0.0
        self.commands = []
        self.events = []
        self.ioctl = Mock()
        self.close = Mock()
        self.pending = b''
        self.device_data = b'input events discarded'
        self.poller = self.poll

    def poll(self, fds, write, error, timeout):
        self.now += timeout
        self.mono += timeout
        if self.commands:
            action = self.commands.pop(0)
            if action == 'DEVICE':
                return [55], [], []
            if action == 'EXIT':
                return [99], [], []
            if action == 'SUSPEND':
                self.now += 30
                return [], [], []
            self.pending = action
            return [0], [], []
        return [], [], []

    def read(self, fd, size):
        return self.pending if fd == 0 else self.device_data

    def own(self):
        with patch.object(helper.time, 'monotonic', side_effect=lambda: self.mono):
            helper.own_grab(55, self.guard, self.events.append, clock=lambda: self.now,
                            poll=self.poller, read=self.read, ioctl=self.ioctl, close=self.close, trial=True)

    def assert_released(self):
        self.assertEqual(self.ioctl.call_args_list[-1].args, (55, helper.EVIOCGRAB, 0))
        self.close.assert_called_once_with(55)
        self.assertEqual(self.events[-1]['event'], 'restored')

    def test_success_reported_only_after_grab(self):
        def send_event(event):
            if event['event'] == 'disabled':
                self.ioctl.assert_called_once_with(55, helper.EVIOCGRAB, 1)
            self.events.append(event)
        self.commands = [b'RELEASE\n']
        with patch.object(helper.time, 'monotonic', return_value=0):
            helper.own_grab(55, self.guard, send_event, clock=lambda: 0,
                            poll=self.poll, read=self.read, ioctl=self.ioctl, close=self.close)
        self.assert_released()

    def test_busy_and_permission_failure_never_report_blocked(self):
        for code in (errno.EBUSY, errno.EACCES):
            with self.subTest(code=code):
                self.ioctl.reset_mock()
                self.close.reset_mock()
                self.ioctl.side_effect = OSError(code, 'grab rejected')
                with self.assertRaises(OSError):
                    self.own()
                self.close.assert_called_once_with(55)
                self.assertEqual(self.events, [])

    def test_trial_expires_in_helper_despite_heartbeats(self):
        self.commands = [b'PING\n'] * 40
        self.own()
        self.assertEqual(self.now, 15)
        self.assertEqual(self.events[-1]['reason'], '15-second trial expired')
        self.assert_released()

    def test_confirmed_grab_stays_until_explicit_release(self):
        self.commands = [b'KEEP\n'] + [b'PING\n'] * 35 + [b'RELEASE\n']
        self.own()
        self.assertGreater(self.now, 15)
        states = [event for event in self.events if event['event'] == 'state']
        self.assertTrue(states)
        self.assertTrue(all(event['confirmed'] and event['trial_remaining'] is None for event in states))
        self.assertIn({'event': 'kept', 'confirmed': True, 'trial_remaining': None}, self.events)
        self.assert_released()

    def test_gui_eof_releases_even_after_confirmation(self):
        self.commands = [b'KEEP\n', b'']
        self.own()
        self.assert_released()
        self.assertEqual(self.events[-1]['reason'], 'GUI connection closed')

    def test_heartbeat_loss_releases_confirmed_grab(self):
        self.commands = [b'KEEP\n']
        self.own()
        self.assertEqual(self.events[-1]['reason'], 'connection heartbeat lost')
        self.assert_released()

    def test_gui_process_exit_releases(self):
        self.commands = ['EXIT']
        self.own()
        self.assert_released()

    def test_session_end_releases(self):
        self.guard.alive.side_effect = [True, True, False]
        self.own()
        self.assert_released()
        self.assertIn('session ended', self.events[-1]['reason'])

    def test_inactive_session_never_grabs(self):
        self.guard.alive.return_value = False
        with self.assertRaises(helper.UnsafeDevice):
            self.own()
        self.ioctl.assert_not_called()
        self.close.assert_called_once_with(55)

    def test_suspend_resume_releases_without_regrab(self):
        self.commands = [b'KEEP\n', 'SUSPEND']
        self.own()
        self.assert_released()
        self.assertEqual(self.events[-1]['reason'], 'suspend/resume detected')
        self.assertEqual(sum(call.args[-1] == 1 for call in self.ioctl.call_args_list), 1)

    def test_disconnect_releases_and_reports_error(self):
        self.commands = ['DEVICE']
        self.device_data = b''
        with self.assertRaises(OSError):
            self.own()
        self.assert_released()

    def test_drains_events_and_remains_responsive_to_release(self):
        self.commands = ['DEVICE', 'DEVICE', b'RELEASE\n']
        self.own()
        self.assert_released()
        self.assertNotIn('input events', repr(self.events))

    def test_ungrab_failure_still_closes_descriptor(self):
        self.commands = [b'RELEASE\n']
        self.ioctl.side_effect = [None, OSError(errno.ENODEV, 'unplugged')]
        self.own()
        self.assert_released()

    def test_termination_and_protocol_errors_release(self):
        self.poller = Mock(side_effect=InterruptedError('terminated'))
        with self.assertRaises(InterruptedError):
            self.own()
        self.assert_released()

    def test_rejects_arbitrary_commands_and_paths(self):
        for command in (b'/dev/input/event8\n', b'RUN something\n', b'OPEN /etc/passwd\n'):
            with self.subTest(command=command):
                self.commands = [command]
                self.close.reset_mock()
                with self.assertRaises(helper.UnsafeDevice):
                    self.own()
                self.assert_released()


class Client(unittest.TestCase):
    @patch('touchswitch.wayland.installation_error', return_value='')
    def test_only_token_and_gui_pid_passed_to_fixed_helper(self, _):
        device = Device('Wacom HID 48CA Finger', '/dev/input/event42', '/sys/example')
        argv = helper_command(device)
        self.assertEqual(argv[:3], ['/usr/bin/pkexec', '--disable-internal-agent', '/usr/libexec/touchswitch-helper'])
        self.assertEqual(argv[3], identity_token(device))
        self.assertNotIn(device.node, argv)
        self.assertEqual(argv[4], str(os.getpid()))

    def test_client_rejects_unrecognized_messages(self):
        with self.assertRaises(ValueError):
            send(Mock(), b'OPEN /etc/shadow\n')


class SessionAuthentication(unittest.TestCase):
    def test_other_uid_rejected_and_pidfd_closed(self):
        with patch.object(helper.os, 'pidfd_open', return_value=99), patch.object(helper.os, 'stat', return_value=SimpleNamespace(st_uid=2000)), patch.object(helper.os, 'close') as close:
            with self.assertRaisesRegex(helper.UnsafeDevice, 'does not belong'):
                helper.SessionGuard(1000, 123)
            close.assert_called_once_with(99)

    def test_user_manager_scope_uses_logind_graphical_session(self):
        library = Mock()
        def get_uid(session, output):
            output._obj.value = 1000
            return 0
        library.sd_session_get_uid.side_effect = get_uid
        library.sd_session_is_active.return_value = 1
        with patch.object(helper.os, 'pidfd_open', return_value=99), patch.object(helper.os, 'stat', return_value=SimpleNamespace(st_uid=1000)), patch.object(helper.ctypes, 'CDLL', return_value=library), patch.object(helper.SessionGuard, 'text', side_effect=[helper.UnsafeDevice('not a session scope'), 'c2', 'wayland', 'seat0']) as text, patch.object(helper.select, 'select', return_value=([], [], [])), patch.object(helper.os, 'close'):
            guard = helper.SessionGuard(1000, 123)
            self.assertEqual(guard.seat, 'seat0')
            self.assertEqual(text.call_args_list[1].args, ('sd_uid_get_display', 1000))
            guard.close()

    def test_non_wayland_session_rejected(self):
        library = Mock()
        def get_uid(session, output):
            output._obj.value = 1000
            return 0
        library.sd_session_get_uid.side_effect = get_uid
        with patch.object(helper.os, 'pidfd_open', return_value=99), patch.object(helper.os, 'stat', return_value=SimpleNamespace(st_uid=1000)), patch.object(helper.ctypes, 'CDLL', return_value=library), patch.object(helper.SessionGuard, 'text', side_effect=['c2', 'x11']), patch.object(helper.os, 'close') as close:
            with self.assertRaisesRegex(helper.UnsafeDevice, 'restricted to a Wayland'):
                helper.SessionGuard(1000, 123)
            close.assert_called_once_with(99)


class VerifiedOpen(unittest.TestCase):
    def test_fd_capabilities_verified_and_failed_validation_closes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            event = root / 'event42'
            (event / 'device').mkdir(parents=True)
            (event / 'device/name').write_text('Wacom HID 48CA Finger')
            (event / 'dev').write_text('13:42')
            token = helper.token_for(str(event), 'Wacom HID 48CA Finger')
            props = {'DEVNAME': '/dev/input/event42', 'ID_INPUT_TOUCHSCREEN': '1'}
            info = SimpleNamespace(st_mode=stat.S_IFCHR, st_rdev=os.makedev(13, 42))
            original_resolve = Path.resolve
            def resolve(path, *args, **kwargs):
                if str(path) == '/sys/dev/char/13:42':
                    return event
                return original_resolve(path, *args, **kwargs)
            with patch.object(helper, 'udev_properties', return_value=props) as udev, patch.object(helper.os, 'open', return_value=55), patch.object(helper.os, 'fstat', return_value=info), patch.object(helper.os, 'close') as close, patch.object(Path, 'resolve', resolve), patch.object(helper, 'read_bits', side_effect=[{0, 1, 3}, {330}, {0x35, 0x36}, {1}]):
                self.assertEqual(helper.open_verified(token, 'seat0', root), 55)
                close.assert_not_called()
                self.assertEqual(udev.call_count, 2)
            with patch.object(helper, 'udev_properties', return_value=props), patch.object(helper.os, 'open', return_value=55), patch.object(helper.os, 'fstat', return_value=info), patch.object(helper.os, 'close') as close, patch.object(Path, 'resolve', resolve), patch.object(helper, 'read_bits', side_effect=[{0, 1, 3}, {30, 330}, {0x35, 0x36}, {1}]):
                with self.assertRaisesRegex(helper.UnsafeDevice, 'Keyboard'):
                    helper.open_verified(token, 'seat0', root)
                close.assert_called_once_with(55)


class PersistentBlocking(unittest.TestCase):
    def test_default_grab_stays_blocked_beyond_30_seconds_without_keep(self):
        now = [0.0]
        command = [b'']
        events = []
        ioctl, close = Mock(), Mock()
        def poll(fds, writes, errors, timeout):
            now[0] += timeout
            if now[0] > 30:
                ioctl.assert_called_once_with(55, helper.EVIOCGRAB, 1)
                close.assert_not_called()
                command[0] = b'RELEASE\n'
            else:
                command[0] = b'PING\n'
            return [0], [], []
        with patch.object(helper.time, 'monotonic', side_effect=lambda: now[0]):
            helper.own_grab(55, Mock(pidfd=99), send=events.append,
                            clock=lambda: now[0], poll=poll,
                            read=lambda fd, size: command[0], ioctl=ioctl, close=close)
        self.assertGreater(now[0], 30)
        self.assertTrue(events[0]['confirmed'])
        self.assertEqual(events[0]['seconds'], 0)
        self.assertTrue(all(e.get('trial_remaining') is None for e in events))
        self.assertEqual(events[-1]['reason'], 'enabled by user')
        close.assert_called_once_with(55)
