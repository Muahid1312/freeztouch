#!/usr/bin/python3
"""Install only this user's launcher and icon. Keep the checkout in place."""
import os
from pathlib import Path
import shlex
import shutil


def main():
    if os.geteuid() == 0:
        raise SystemExit('Run without sudo: this installer is per-user only.')
    root = Path(__file__).resolve().parent
    data = Path(os.environ.get('XDG_DATA_HOME', Path.home() / '.local/share'))
    bin_dir = Path.home() / '.local/bin'
    apps = data / 'applications'
    icons = data / 'icons/hicolor/scalable/apps'
    for folder in (apps, icons, bin_dir):
        folder.mkdir(parents=True, exist_ok=True)
    launcher = bin_dir / 'touchswitch'
    desktop = apps / 'TouchSwitch.desktop'
    icon = icons / 'touchswitch.svg'
    for target in (launcher, desktop, icon):
        if target.exists() or target.is_symlink():
            raise SystemExit(f'{target} already exists. Remove it explicitly before reinstalling.')
    launcher.write_text('#!/bin/sh\nexec ' + shlex.quote(str(root / 'launch.sh')) + ' "$@"\n')
    launcher.chmod(0o755)
    # Desktop Entry Exec has its own quoting rules, distinct from shell quoting.
    executable = str(root / 'launch.sh')
    executable = executable.replace('\\', '\\\\').replace('"', '\\"').replace('`', '\\`').replace('$', '\\$')
    executable = executable.replace('%', '%%')
    text = (root / 'TouchSwitch.desktop').read_text().replace('Exec=touchswitch', f'Exec="{executable}"')
    desktop.write_text(text)
    shutil.copyfile(root / 'assets/touchswitch.svg', icon)
    print(f'Installed {desktop}\nKeep the checkout at {root}. Search applications for TouchSwitch.')


if __name__ == '__main__':
    main()
