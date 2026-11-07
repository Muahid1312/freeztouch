# Validation — Wayland backend, 2026-11-07

Development host: Debian GNU/Linux 13 (cloud), amd64, Python 3, GTK 3.24. No physical touchscreen, Ubuntu Wayland session, or usable privileged installation/polkit flow is available here.

## Passed

- **64 tests passed, none skipped**, in 15.307 seconds using:
  `DISPLAY=:97 XDG_SESSION_TYPE=x11 /usr/bin/python3 -m unittest discover -s tests -v`.
  The display was an isolated Xorg dummy server, not a real Wayland desktop. Wayland session, hardware, helper and polkit responses were mocked in GTK tests.
- **29 focused helper/client tests** cover udev classification, dedicated direct-touch capabilities, rejection of keyboard/mouse/touchpad/pen/mixed inputs, seat matching, identity tokens, changing event numbers, fd identity mismatch, verified open, failed-validation cleanup, authenticated caller uid/session fallback, inactive sessions, and fixed/bounded commands.
- Helper lifecycle tests cover `EBUSY` and permission failures, success notification after grab, draining/discarding events, release, ungrab failures, helper-side 15-second timeout despite continuing heartbeats, confirmed lifetime, GUI EOF/pid death, heartbeat loss, session end, suspend/resume detection, disconnection, and termination exceptions. All kernel operations are mocked; no host input fd was opened or grabbed.
- **Seven GTK checks** cover X11 regression behavior, missing-helper instructions, ready Wayland controls, block/confirm/release transitions over the same helper connection, and visible authorization denial without reporting a grab.
- Existing X11 command-failure, selection, installer, and independent-watchdog tests pass. The old watchdog's real subprocess/pipe tests include an actual 15-second timeout using a fake backend.
- System helper/policy syntax parsed, all Python sources compiled, launcher shell syntax and Git whitespace checks passed. The system installer refuses an unprivileged invocation with the exact installation command.
- A small C check against this host's Linux headers produced `EVIOCGRAB=0x40044590`, `EVIOCGBIT(EV_KEY,96)=0x80604521`, and `EVIOCGPROP(8)=0x80084509`, matching the standalone helper's ioctl encoding on amd64. The ABI is limited to amd64/arm64; other architectures are refused.
- The Wayland terminal recovery command printed the scoped emergency release instructions. Upstream Linux, polkit, and systemd sources listed in README were retrieved and inspected during implementation.

## Requires testing on your Ubuntu laptop

No claim is made that Wacom HID 48CA Finger has passed the helper's validation or been grabbed successfully. `/dev/input/event8` was supplied as an observation, not used as a fixed target.

Check these on the real Ubuntu 26.04.1 Wayland session:

1. Install the root-owned helper/policy with the README commands. Confirm the desktop polkit dialog appears and authorization cancellation leaves touch unaffected.
2. Select the Wacom Finger panel. Confirm its actual udev/capability data passes the strict helper checks. A rejection must be investigated, not bypassed with broader permissions.
3. Verify only touch is blocked; keyboard, touchpad and mouse continue working. Let the first trial expire, then test explicit confirmation and Enable.
4. Test closing/crashing the GUI, the emergency helper-only termination command, session logout/switch, hotplug and suspend/resume. Confirm restoration and accurate errors; no automatic re-grab should occur after disconnect/resume.
5. Verify the installed helper remains root:root 0755 and its policy root:root 0644, with root-owned non-writable parent directories.

The cloud environment lacks sudo, so no real root installation was performed. No system polkit files or input permissions were changed here. No real evdev grab, real polkit authentication, kernel event drain, physical input-device isolation, or Ubuntu hardware operation was tested. Mocked validation demonstrates control flow and fail-safe behavior, not hardware compatibility.
