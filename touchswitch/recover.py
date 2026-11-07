"""Keyboard/terminal recovery. Enabling only; disabling requires the GUI trial."""
import argparse
import os
import sys
from .backend import Backend, ControlError


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--node', help='Exact /dev/input/eventN shown by the app; omit to list touchscreens')
    args = parser.parse_args()
    if os.geteuid() == 0:
        parser.error('Run as your normal desktop user, without sudo.')
    backend = Backend()
    try:
        devices = backend.discover()
        if not args.node:
            for device in devices:
                print(f'{device.node}\t{device.name}')
            if not devices:
                print('No dedicated touchscreens found.')
            return 0
        matches = [device for device in devices if device.node == args.node]
        if len(matches) != 1:
            raise ControlError('That node is not a uniquely verified dedicated touchscreen.')
        backend.set_enabled(matches[0], True)
        print('Touchscreen enabled; status verified.')
        return 0
    except ControlError as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
