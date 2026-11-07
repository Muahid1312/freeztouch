#!/usr/bin/python3
"""One-time root installation of the standalone helper and its narrow polkit action."""
import os
from pathlib import Path
import stat
import tempfile

ROOT = Path(__file__).resolve().parent
FILES = {
    ROOT / 'privileged/touchswitch-helper': ('/usr/libexec/touchswitch-helper', 0o755),
    ROOT / 'privileged/org.touchswitch.block.policy': ('/usr/share/polkit-1/actions/org.touchswitch.block.policy', 0o644),
}


def install(source, target, mode):
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o755)
    for path in (target.parent, *target.parent.parents):
        info = path.lstat()
        if stat.S_ISLNK(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
            raise SystemExit(f'Refusing unsafe installation directory: {path}')
    fd, temporary = tempfile.mkstemp(prefix='.touchswitch-', dir=target.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(source.read_bytes())
            os.fchown(stream.fileno(), 0, 0)
            os.fchmod(stream.fileno(), mode)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)  # Replace a symlink itself; never follow it.
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def main():
    if os.geteuid() != 0:
        raise SystemExit('Install only the helper with: sudo /usr/bin/python3 -I install-system.py')
    for source, (target, mode) in FILES.items():
        install(source, target, mode)
        print(f'Installed root:root {mode:o} {target}')
    print('Launch ./launch.sh as your normal user. No input permissions were changed.')


if __name__ == '__main__':
    main()
