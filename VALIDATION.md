# Validation — 2026-11-07

Environment: Debian GNU/Linux 13 (cloud), Python 3, GTK 3.24. No physical touchscreen. No Ubuntu laptop was available.

- **32 tests passed** in 15.274 seconds with `/usr/bin/python3 -m unittest discover -s tests -v`, `DISPLAY=:98`, and `XDG_SESSION_TYPE=x11`, using a temporary Xorg dummy display. None skipped in this run.
- 23 backend/recovery unit tests use mocked system commands and fake devices: strict device selection, multiple panels, ID reuse, permission errors, missing commands, deadlines, unsupported sessions, readback, and recovery exceptions.
- Four GTK tests exercise enabled-device controls, no-device controls, the Wayland limitation, and visible command errors. Device data is mocked.
- Two installer tests use a temporary home/data directory and verify generated launchers, icon installation, preservation of existing files, and root refusal.
- Three subprocess tests execute the real watchdog control flow with a fake backend. Closing its GUI pipe restores the fake device; explicit confirmation preserves the disabled state; an actual 15-second timeout restores it.
- The actual udev discovery path returned no touchscreen on this host. The actual GTK window was started on the dummy display, and its no-device state correctly disabled both actions. A rendered window with mocked panel data was visually inspected.
- Without a display, `./launch.sh` exits with a clear error. The enable-only recovery CLI lists no devices and exits normally on this host.
- Python compilation, shell syntax validation, and Git whitespace checks passed.

The cloud host has no `xinput` binary. Installing test packages globally was unavailable because `sudo` is absent; existing GTK/Xorg tools were sufficient for isolated GUI tests. No XInput touchscreen mutation was performed. XInput behavior is covered by mocked command responses, not hardware validation.

Not verified: Ubuntu installation on physical hardware, physical touchscreen enable/disable, real mouse/keyboard confirmation, compositor behavior on a real Wayland session, hotplug of real panels, and suspend/resume behavior. The Wayland refusal path was tested using mocked session/device data; upstream Wayland/GNOME sources were inspected as described in README.

No input permissions, boot settings, drivers, or persistent system input settings were changed. No global package installation succeeded or was required for these checks. The optional per-user launcher was tested in a temporary directory, not installed into the cloud user's home.
