# Validation — persistent Wayland blocking, 2026-11-08

**67 tests passed, none skipped**, in 15.415 seconds on the cloud host with GTK on an isolated virtual X11 display (`DISPLAY=:95`). The kernel input operations and Wayland session/polkit interactions were mocked; no physical touchscreen was used.

The default Wayland helper is now tested holding its exclusive grab beyond **30 simulated seconds without any KEEP request**, then releasing only on RELEASE. GUI tests verify immediate acknowledged blocking with no confirmation button, plus automatic cancellation of an older installed helper’s trial. Existing connection-loss, GUI exit, helper termination, heartbeat loss, disconnection and session recovery tests pass. Optional/legacy trial tests and the X11 watchdog’s actual 15-second subprocess test still pass.

Python compilation, standalone helper syntax and Git whitespace checks passed. Real Wacom touchscreen operation and installation/polkit behavior still require testing on the Ubuntu laptop. Close the old GUI and rerun `sudo /usr/bin/python3 -I install-system.py` from the updated source before launching.
