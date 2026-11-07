"""Independent trial owner. EOF, timeout, or GUI exit restores the selected device."""
import json
import os
import select
import signal
import sys
import time
from .backend import Backend, Device


def trial(backend, device, confirmed, emit, duration=15):
    """Always attempt recovery unless a timely explicit confirmation was received."""
    keep = False
    try:
        backend.set_enabled(device, False)
        emit({'event': 'disabled', 'seconds': duration})
        requested = confirmed(time.monotonic() + duration)
        if requested:
            if backend.status(device):
                raise RuntimeError('Touchscreen is already enabled; disable confirmation was not accepted.')
            keep = True
            emit({'event': 'kept'})
    finally:
        if not keep:
            backend.set_enabled(device, True)
            emit({'event': 'restored'})


def main():
    if os.geteuid() == 0:
        return 1
    device = Device(**json.loads(sys.argv[1]))
    signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(InterruptedError('Trial interrupted')))

    def emit(message):
        try:
            print(json.dumps(message), flush=True)
        except BrokenPipeError:
            pass  # A closed GUI must not prevent restoration.

    def confirmed(deadline):
        remaining = max(0, deadline - time.monotonic())
        readable, _, _ = select.select([sys.stdin], [], [], remaining)
        return bool(readable and os.read(sys.stdin.fileno(), 32) == b'KEEP\n'
                    and time.monotonic() < deadline)

    try:
        trial(Backend(), device, confirmed, emit)
        return 0
    except Exception as exc:
        emit({'event': 'error', 'message': str(exc)})
        return 1


if __name__ == '__main__':
    sys.exit(main())
