"""System boundary. All commands use argument lists, deadlines and checked results."""
from dataclasses import dataclass
import os
from pathlib import Path
import re
import shutil
import subprocess


class ControlError(RuntimeError):
    pass


def run(args):
    if not shutil.which(args[0]):
        raise ControlError(f"Missing command: {args[0]}. Install the Ubuntu dependency listed in README.")
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=4,
                                env={**os.environ, 'LC_ALL': 'C'})
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ControlError(f"{args[0]} could not complete: {exc}") from exc
    if result.returncode:
        detail = (result.stderr or result.stdout).strip()[:400]
        raise ControlError(f"{args[0]} failed ({result.returncode}): {detail or 'no diagnostic output'}")
    return result.stdout


@dataclass(frozen=True)
class Session:
    os_name: str
    kind: str

    @classmethod
    def detect(cls):
        try:
            data = dict(line.split('=', 1) for line in Path('/etc/os-release').read_text().splitlines()
                        if '=' in line)
            name = data.get('PRETTY_NAME', 'Unknown Linux').strip('"')
        except OSError:
            name = 'Unknown Linux'
        kind = os.environ.get('XDG_SESSION_TYPE', '').lower()
        if os.environ.get('WAYLAND_DISPLAY'):
            kind = 'wayland'  # Never mistake Xwayland's DISPLAY for a real X11 session.
        if kind not in ('x11', 'wayland'):
            kind = 'unknown'
        return cls(name, kind)

    @property
    def limitation(self):
        if self.kind == 'wayland':
            return ('Wayland: touchscreen control is unavailable. XInput controls Xwayland devices, '
                    'not the compositor’s physical touchscreen. No verified safe per-device method '
                    'is implemented. Log out and choose “Ubuntu on Xorg” if available.')
        if self.kind != 'x11':
            return 'Session type could not be verified. Control is unavailable; start in a verified X11 session.'
        if not os.environ.get('DISPLAY'):
            return 'X11 display is missing. Start TouchSwitch inside your desktop session.'
        return ''


@dataclass(frozen=True)
class Device:
    name: str
    node: str
    syspath: str

    @property
    def key(self):
        return self.syspath


class Backend:
    def __init__(self, session=None, command=run, input_root='/sys/class/input'):
        self.session = session or Session.detect()
        self.command = command
        self.input_root = Path(input_root)

    def discover(self):
        devices = []
        for entry in sorted(self.input_root.glob('event*')):
            try:
                syspath = str(entry.resolve(strict=True))
            except OSError:
                continue
            raw = self.command(['udevadm', 'info', '--query=property', '--path', syspath])
            props = dict(line.split('=', 1) for line in raw.splitlines() if '=' in line)
            if props.get('ID_INPUT_TOUCHSCREEN') != '1':
                continue
            if any(props.get('ID_INPUT_' + kind) == '1' for kind in
                   ('MOUSE', 'TOUCHPAD', 'KEYBOARD', 'TABLET', 'TABLET_PAD', 'JOYSTICK', 'POINTINGSTICK', 'ACCELEROMETER')):
                continue
            node = props.get('DEVNAME', '')
            if node != '/dev/input/' + entry.name:
                continue
            try:
                name = (entry / 'device/name').read_text().strip()
            except OSError:
                name = 'Touchscreen'
            devices.append(Device(name, node, syspath))
        return devices

    def resolve(self, device):
        if self.session.limitation:
            raise ControlError(self.session.limitation)
        current = [d for d in self.discover() if d == device]
        if len(current) != 1:
            raise ControlError('The selected touchscreen disconnected or changed. Refresh and select it again.')
        ids = self.command(['xinput', 'list', '--id-only']).splitlines()
        matches = []
        for xid in dict.fromkeys(i.strip() for i in ids):
            if not xid.isdigit():
                continue
            props = self.command(['xinput', 'list-props', xid])
            nodes = re.findall(r'^\s*Device Node \(\d+\):\s*"([^"]+)"\s*$', props, re.M)
            if nodes != [device.node]:
                continue
            info = self.command(['xinput', 'list', '--long', xid])
            if not re.search(r'\[slave\s+pointer\s+\(\d+\)\]', info):
                continue
            if not re.search(r'Touch mode:\s*direct\b', info, re.I) or 'TouchClass' not in info:
                continue
            if 'KeyClass' in info:
                continue
            enabled = re.findall(r'^\s*Device Enabled \(\d+\):\s*([01])\s*$', props, re.M)
            if len(enabled) != 1:
                raise ControlError('The touchscreen has no unambiguous writable Device Enabled property.')
            matches.append((xid, enabled[0] == '1'))
        if len(matches) != 1:
            raise ControlError('Cannot uniquely match this physical touchscreen to a supported XInput direct-touch device.')
        return matches[0]

    def status(self, device):
        return self.resolve(device)[1]

    def set_enabled(self, device, enabled):
        xid, before = self.resolve(device)  # Revalidate physical identity on every operation.
        if before != enabled:
            try:
                self.command(['xinput', 'set-prop', xid, 'Device Enabled', '1' if enabled else '0'])
            except ControlError as exc:
                try:
                    actual = 'enabled' if self.status(device) else 'disabled'
                except ControlError as check_error:
                    raise ControlError(f'{exc} Status recheck also failed: {check_error}') from exc
                raise ControlError(f'{exc} Rechecked status: {actual}.') from exc
        actual = self.status(device)  # Never trust exit status alone.
        if actual != enabled:
            raise ControlError('The command completed, but the touchscreen status did not change as requested.')
        return actual
