"""Unprivileged client for the fixed polkit helper. No device node paths cross IPC."""
import hashlib
import os
from pathlib import Path
import stat

HELPER = '/usr/libexec/touchswitch-helper'
POLICY = '/usr/share/polkit-1/actions/org.touchswitch.block.policy'
PKEXEC = '/usr/bin/pkexec'


def identity_token(device):
    return hashlib.sha256((device.syspath + '\0' + device.name).encode()).hexdigest()


def installation_error():
    try:
        for filename in (HELPER, POLICY, PKEXEC):
            path = Path(filename)
            for item in (path, *path.parents):
                info = item.lstat()
                if stat.S_ISLNK(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
                    return f'Wayland helper installation is unsafe: {item}. Reinstall using install-system.py.'
        if not os.access(HELPER, os.X_OK) or not os.access(PKEXEC, os.X_OK):
            return 'Wayland helper or pkexec is not executable. Reinstall the system helper.'
    except OSError:
        return ('Wayland input blocking needs the polkit helper. Install it with '
                'sudo /usr/bin/python3 -I install-system.py (see README).')
    return ''


def helper_command(device):
    error = installation_error()
    if error:
        raise RuntimeError(error)
    return [PKEXEC, '--disable-internal-agent', HELPER, identity_token(device), str(os.getpid())]


def send(process, command):
    if command not in (b'PING\n', b'KEEP\n', b'RELEASE\n'):
        raise ValueError('Unsupported helper control message')
    os.write(process.stdin.fileno(), command)
