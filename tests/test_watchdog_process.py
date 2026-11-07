"""Real child/pipe/deadline checks; fake backend never touches host input devices."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

CHILD = '''
import json, sys
from pathlib import Path
from unittest.mock import patch
from touchswitch import watchdog
class FakeBackend:
    def set_enabled(self, device, enabled):
        with open(sys.argv[1], 'a') as log:
            log.write(str(enabled) + '\\n')
    def status(self, device):
        return False
state = sys.argv[1]
sys.argv = ['watchdog', json.dumps(dict(name='Fake', node='/dev/input/event999', syspath='/sys/fake'))]
# Keep the state path separately, as the production CLI consumes argv[1].
class Backend(FakeBackend):
    def set_enabled(self, device, enabled):
        with open(state, 'a') as log:
            log.write(str(enabled) + '\\n')
with patch.object(watchdog, 'Backend', Backend):
    sys.exit(watchdog.main())
'''


@unittest.skipIf(os.geteuid() == 0, 'Production helper refuses root')
class RecoveryProcess(unittest.TestCase):
    def start_helper(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        state = Path(temp.name) / 'state'
        process = subprocess.Popen([sys.executable, '-c', CHILD, str(state)],
                                   stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   text=True, cwd=str(Path(__file__).resolve().parent.parent))
        def cleanup():
            if process.poll() is None:
                process.kill()
            process.wait()
            for stream in (process.stdin, process.stdout, process.stderr):
                if not stream.closed:
                    stream.close()
        self.addCleanup(cleanup)
        # readline is bounded by the helper's outer unittest process timeout in CI;
        # select explicitly guards against a broken helper that never starts.
        import select
        self.assertTrue(select.select([process.stdout], [], [], 5)[0])
        first = json.loads(process.stdout.readline())
        self.assertEqual(first['event'], 'disabled')
        self.assertEqual(state.read_text(), 'False\n')
        return process, state

    def test_closed_gui_pipe_restores(self):
        process, state = self.start_helper()
        process.stdin.close()
        process.wait(timeout=5)
        self.assertEqual(process.returncode, 0, process.stderr.read())
        self.assertEqual(state.read_text(), 'False\nTrue\n')
        self.assertEqual(json.loads(process.stdout.readline())['event'], 'restored')

    def test_real_fifteen_second_deadline_restores(self):
        process, state = self.start_helper()
        started = time.monotonic()
        process.wait(timeout=20)
        elapsed = time.monotonic() - started
        self.assertGreaterEqual(elapsed, 14.5)
        self.assertEqual(process.returncode, 0, process.stderr.read())
        self.assertEqual(state.read_text(), 'False\nTrue\n')

    def test_confirmation_keeps_disabled(self):
        process, state = self.start_helper()
        process.stdin.write('KEEP\n')
        process.stdin.flush()
        process.wait(timeout=5)
        self.assertEqual(process.returncode, 0, process.stderr.read())
        self.assertEqual(state.read_text(), 'False\n')
        self.assertEqual(json.loads(process.stdout.readline())['event'], 'kept')
