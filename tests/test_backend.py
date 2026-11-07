import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch
from touchswitch.backend import Backend, ControlError, Session, run
from touchswitch.watchdog import trial


class Devices(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.props = {}
        self.nodes = {'12': '/dev/input/event3'}
        self.enabled = True
        self.direct = True
        self.key_class = False
        self.mutation = None
        self.commands = []
        self.backend = Backend(Session('Ubuntu 24.04 LTS', 'x11'), self.command, self.root)
        self.env = patch.dict(os.environ, {'DISPLAY': ':99'}, clear=True)
        self.env.start()
        self.addCleanup(self.env.stop)
        self.add_device('event3', 'Panel', ID_INPUT_TOUCHSCREEN='1')

    def add_device(self, event, name, **props):
        entry = self.root / event / 'device'
        entry.mkdir(parents=True)
        (entry / 'name').write_text(name)
        self.props[event] = {'DEVNAME': '/dev/input/' + event, **props}

    def command(self, args):
        self.commands.append(args)
        if args[0] == 'udevadm':
            return '\n'.join(f'{k}={v}' for k, v in self.props[Path(args[-1]).name].items())
        if args[1:] == ['list', '--id-only']:
            return '\n'.join(self.nodes)
        if args[1] == 'list-props':
            return f'Device Node (123): "{self.nodes[args[-1]]}"\nDevice Enabled (124): {int(self.enabled)}\n'
        if args[1:3] == ['list', '--long']:
            return (f'Panel id={args[-1]} [slave pointer (2)]\nXITouchClass\nTouch mode: ' +
                    ('direct' if self.direct else 'dependent') + ('\nXIKeyClass' if self.key_class else ''))
        if args[1] == 'set-prop':
            if self.mutation:
                return self.mutation(args)
            self.enabled = args[-1] == '1'
            return ''
        raise AssertionError(args)

    def device(self):
        return self.backend.discover()[0]

    def test_selection_excludes_unrelated_and_combined_devices(self):
        for i, kind in enumerate(('MOUSE', 'TOUCHPAD', 'KEYBOARD', 'TABLET', 'TABLET_PAD', 'JOYSTICK', 'POINTINGSTICK', 'ACCELEROMETER'), 10):
            self.add_device(f'event{i}', kind, ID_INPUT_TOUCHSCREEN='1', **{'ID_INPUT_' + kind: '1'})
        self.add_device('event1', 'Mouse', ID_INPUT_MOUSE='1')
        self.add_device('event2', 'Misleading touchscreen name')
        self.assertEqual([d.name for d in self.backend.discover()], ['Panel'])

    def test_multiple_touchscreens_are_independent(self):
        self.add_device('event4', 'External', ID_INPUT_TOUCHSCREEN='1')
        self.nodes['14'] = '/dev/input/event4'
        selected = next(d for d in self.backend.discover() if d.name == 'External')
        self.backend.set_enabled(selected, False)
        writes = [c for c in self.commands if c[1:2] == ['set-prop']]
        self.assertEqual(writes, [['xinput', 'set-prop', '14', 'Device Enabled', '0']])

    def test_never_selects_by_display_name(self):
        self.nodes['12'] = '/dev/input/event99'
        with self.assertRaisesRegex(ControlError, 'uniquely match'):
            self.backend.set_enabled(self.device(), False)
        self.assertFalse(any('set-prop' in c for c in self.commands))

    def test_indirect_touch_is_rejected(self):
        self.direct = False
        with self.assertRaises(ControlError):
            self.backend.set_enabled(self.device(), False)

    def test_keyboard_class_is_rejected(self):
        self.key_class = True
        with self.assertRaises(ControlError):
            self.backend.set_enabled(self.device(), False)

    def test_duplicate_mapping_is_rejected(self):
        self.nodes['14'] = '/dev/input/event3'
        with self.assertRaises(ControlError):
            self.backend.set_enabled(self.device(), False)

    def test_recycled_xinput_id_is_not_cached(self):
        device = self.device()
        self.assertTrue(self.backend.status(device))
        self.nodes = {'12': '/dev/input/event99', '18': device.node}
        self.backend.set_enabled(device, False)
        self.assertIn(['xinput', 'set-prop', '18', 'Device Enabled', '0'], self.commands)

    def test_disconnection_blocks_mutation(self):
        device = self.device()
        self.props['event3']['ID_INPUT_TOUCHSCREEN'] = '0'
        with self.assertRaisesRegex(ControlError, 'disconnected'):
            self.backend.set_enabled(device, False)

    def test_command_success_without_status_change_is_error(self):
        self.mutation = lambda args: ''
        with self.assertRaisesRegex(ControlError, 'did not change'):
            self.backend.set_enabled(self.device(), False)

    def test_permission_failure_is_reported(self):
        def deny(args):
            raise ControlError('Permission denied')
        self.mutation = deny
        with self.assertRaisesRegex(ControlError, 'Permission denied'):
            self.backend.set_enabled(self.device(), False)

    def test_wayland_never_issues_xinput(self):
        self.backend.session = Session('Ubuntu', 'wayland')
        with self.assertRaisesRegex(ControlError, 'Wayland'):
            self.backend.set_enabled(self.device(), False)
        self.assertFalse(any(c[0] == 'xinput' for c in self.commands))

    def test_status_rechecked_after_enable_and_disable(self):
        device = self.device()
        self.assertFalse(self.backend.set_enabled(device, False))
        self.assertTrue(self.backend.set_enabled(device, True))
        self.assertGreaterEqual(sum(c[1:2] == ['list-props'] for c in self.commands), 4)


class CommandFailures(unittest.TestCase):
    @patch('touchswitch.backend.shutil.which', return_value=None)
    def test_missing_command(self, _):
        with self.assertRaisesRegex(ControlError, 'Missing command'):
            run(['xinput', 'list'])

    @patch('touchswitch.backend.shutil.which', return_value='/usr/bin/xinput')
    @patch('touchswitch.backend.subprocess.run', side_effect=subprocess.TimeoutExpired('xinput', 4))
    def test_deadline(self, *_):
        with self.assertRaisesRegex(ControlError, 'could not complete'):
            run(['xinput', 'list'])

    @patch('touchswitch.backend.shutil.which', return_value='/usr/bin/xinput')
    @patch('touchswitch.backend.subprocess.run', return_value=subprocess.CompletedProcess([], 1, '', 'Permission denied'))
    def test_nonzero_exit(self, *_):
        with self.assertRaisesRegex(ControlError, 'Permission denied'):
            run(['xinput', 'list'])

    def test_wayland_overrides_xwayland_display(self):
        with patch.dict(os.environ, {'XDG_SESSION_TYPE': 'x11', 'WAYLAND_DISPLAY': 'wayland-0', 'DISPLAY': ':0'}, clear=True):
            self.assertEqual(Session.detect().kind, 'wayland')

    def test_display_alone_does_not_prove_x11(self):
        with patch.dict(os.environ, {'DISPLAY': ':0'}, clear=True):
            self.assertEqual(Session.detect().kind, 'unknown')


class Recovery(unittest.TestCase):
    def setUp(self):
        self.backend = Mock()
        self.backend.status.return_value = False
        self.events = []

    def test_timeout_or_eof_restores(self):
        trial(self.backend, 'panel', lambda deadline: False, self.events.append)
        self.assertEqual(self.backend.set_enabled.call_args_list, [unittest.mock.call('panel', False), unittest.mock.call('panel', True)])
        self.assertEqual(self.events[-1]['event'], 'restored')

    def test_explicit_confirmation_keeps_disabled(self):
        trial(self.backend, 'panel', lambda deadline: True, self.events.append)
        self.backend.set_enabled.assert_called_once_with('panel', False)
        self.assertEqual(self.events[-1]['event'], 'kept')

    def test_exception_restores(self):
        def broken(deadline):
            raise RuntimeError('GUI pipe failed')
        with self.assertRaises(RuntimeError):
            trial(self.backend, 'panel', broken, self.events.append)
        self.assertEqual(self.backend.set_enabled.call_args_list[-1], unittest.mock.call('panel', True))

    def test_failed_disable_still_attempts_recovery(self):
        self.backend.set_enabled.side_effect = [ControlError('verify failed'), True]
        with self.assertRaises(ControlError):
            trial(self.backend, 'panel', lambda deadline: False, self.events.append)
        self.assertEqual(self.backend.set_enabled.call_count, 2)

    def test_recovery_failure_is_not_success(self):
        self.backend.set_enabled.side_effect = [False, ControlError('device unplugged')]
        with self.assertRaisesRegex(ControlError, 'unplugged'):
            trial(self.backend, 'panel', lambda deadline: False, self.events.append)
        self.assertNotIn('restored', [e['event'] for e in self.events])

    def test_confirmation_rechecks_status(self):
        self.backend.status.side_effect = ControlError('lost device')
        with self.assertRaises(ControlError):
            trial(self.backend, 'panel', lambda deadline: True, self.events.append)
        self.assertEqual(self.backend.set_enabled.call_args_list[-1], unittest.mock.call('panel', True))


if __name__ == '__main__':
    unittest.main()
