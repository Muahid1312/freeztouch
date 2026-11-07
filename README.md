# TouchSwitch

A compact GTK desktop app for enabling and disabling **dedicated touchscreens** in the current X11 session. Multiple panels are selectable. Large controls, visible status, keyboard mnemonics, and a protected 15-second trial prioritize getting touch back.

## Install on Ubuntu

Use Ubuntu's system Python, not a pip virtual environment:

```sh
sudo apt update
sudo apt install python3 python3-gi gir1.2-gtk-3.0 xinput udev
cd /path/to/freeztouch
./launch.sh
```

`requirements.txt` documents these system dependencies; there are no pip packages. GTK 3 is intentionally used for its availability on Ubuntu 22.04 and later. Those Ubuntu releases are intended targets, **not hardware-certified platforms**.

Optional application-menu installation, as your normal user:

```sh
./install-launcher.py
```

This installs a launcher in `~/.local/share/applications`, an SVG icon in the user icon theme, and a command wrapper in `~/.local/bin`. `XDG_DATA_HOME` is respected. Keep this checkout in its current location. The generated desktop launcher uses an absolute path, so it does not depend on your desktop's PATH. Existing installation files are preserved: remove them explicitly before reinstalling. The checked-in `TouchSwitch.desktop` is a template for installations where `touchswitch` is on PATH.

To uninstall the default per-user launcher:

```sh
rm ~/.local/share/applications/TouchSwitch.desktop
rm ~/.local/share/icons/hicolor/scalable/apps/touchswitch.svg
rm ~/.local/bin/touchswitch
```

Do not launch the app, installer, or recovery tool with sudo. No privileged helper is used. An X11 authorization or permission failure is reported instead of requesting broad access to input devices.

## Supported environments and safety

- **X11:** requires a verified `XDG_SESSION_TYPE=x11`, a display connection, udev, and XInput. The app changes only the selected XInput device's `Device Enabled` property. It checks status again after writes, including failed writes. A successful command with unchanged status is an error.
- **Wayland:** discovery only. Controls are unavailable, with an explanation in the window. Xwayland's `DISPLAY` never enables the X11 backend. Choose “Ubuntu on Xorg” at login if your Ubuntu installation offers it; the app does not change login or system settings.
- **Unknown sessions:** control is refused. `DISPLAY` alone is insufficient proof of X11.
- **Strict device selection:** udev must mark the exact event node `ID_INPUT_TOUCHSCREEN=1`; mouse, touchpad, keyboard, tablet, tablet pad, joystick, pointing stick, and accelerometer classifications are rejected. On X11, the node must map uniquely to a slave pointer with a direct `TouchClass`, no `KeyClass`, and a boolean `Device Enabled` property. Names are for display only. Combined/ambiguous devices are deliberately excluded, even if they include a touchscreen.
- Device identity and XInput IDs are resolved again before every change; cached IDs are never used for writes. Disconnections, missing commands, nonzero exits, command timeouts, and failed readback are surfaced. Device IDs may change after hotplug, so refresh the selector after connecting or reconnecting a panel.
- No boot settings, driver blacklists, udev rules, persistent input configuration, or input-device permissions are changed. A confirmed disable lasts until the device/server resets, another tool changes it, or you enable it. Logging out of the X11 session normally resets it.

### Recovery trial and keyboard access

Every disable (including the first) offers an explanatory confirmation, then starts a **15-second trial**. An independent Python process owns the disable and restoration. “Keep disabled” accepts only a mouse or keyboard event, not a touch event. The helper verifies disabled status before accepting confirmation. An unconfirmed timeout, a closed GUI pipe, or a normally closed/crashed GUI causes an attempt to re-enable the same verified device. “Enable touchscreen” cancels an active trial.

Use **Tab / Shift+Tab**, arrow keys in the selector, and **Space / Enter** on buttons. **Alt+T** focuses the touchscreen selector; **Alt+E** enables; **Alt+D** starts the trial; **Alt+K** confirms keeping touch disabled; **Alt+R** refreshes. Keep a working mouse or keyboard available before testing.

Recovery starts at the deadline but command execution/readback can take additional time. It cannot be guaranteed if the device disconnects, the X server stops responding, the machine suspends, or the recovery process itself is forcibly killed. Errors are never reported as successful restoration. Once you explicitly keep touch disabled, exiting the app leaves that session setting in place.

## Re-enable manually

Use a keyboard to open a terminal **in the same desktop session**, without sudo:

```sh
cd /path/to/freeztouch
/usr/bin/python3 -m touchswitch.recover
# Choose the exact node printed above (example only):
/usr/bin/python3 -m touchswitch.recover --node /dev/input/event3
```

This recovery command only enables; it applies the same touchscreen and identity checks as the GUI and verifies the result. There is no command-line disable shortcut that bypasses the trial.

If the app's files are unavailable, `xinput list` and `xinput list-props ID` can identify the panel's current `Device Node` and `Device Enabled` property. Verify that the device is your touchscreen (not a mouse/touchpad/keyboard), then run `xinput enable ID` and check `xinput list-props ID` again. Never copy an old numeric ID blindly. Logging out and back into the desktop is another recovery option. These XInput commands do not control physical touchscreens on Wayland.

## Wayland investigation

Reviewed upstream documentation/source on 2026-11-07:

- [Wayland core protocol, upstream mirror](https://github.com/wayland-mirror/wayland/blob/main/protocol/wayland.xml): `wl_seat` capabilities and `wl_touch` describe input delivery to clients. They expose no general client request to disable a physical touchscreen.
- [GNOME desktop peripheral schemas](https://github.com/GNOME/gsettings-desktop-schemas/blob/master/schemas/org.gnome.desktop.peripherals.gschema.xml.in): the touchscreen schema provides output mapping; `send-events` belongs to the **touchpad** schema. Using it would affect the wrong device.
- [XInput manual](https://www.x.org/releases/current/doc/man/man1/xinput.1.xhtml), also available as `man xinput` on installed systems: property inspection and device enable/disable operations. TouchSwitch additionally requires udev identity and direct-touch capabilities before changing the enabled property.

The Wayland and GNOME sources were retrieved during implementation. The libinput documentation site was inaccessible from this environment, so no method from it was assumed to work. Compositor-specific APIs may exist elsewhere; none is claimed supported or used here. Kernel unbinding, device permission changes, privileged input grabbing, and persistent settings are intentionally outside this app's session-only method.

## Tests and validation

```sh
/usr/bin/python3 -m unittest discover -s tests -v
```

Backend tests mock system commands and exercise strict selection, multiple panels, recycled IDs, disconnections, unsupported sessions, permission failures, timeouts, readback failures, and watchdog recovery/confirmation. GTK tests execute when GTK and a display are available; otherwise they are explicitly skipped. No tests write real input properties.

For optional GUI testing on a machine with Xvfb:

```sh
xvfb-run -a env XDG_SESSION_TYPE=x11 /usr/bin/python3 -m unittest discover -s tests -v
```

Validation in this development environment: Debian 13, Python 3, GTK 3.24, an isolated Xorg dummy display, and **no physical touchscreen**. Automated backend/GTK results are recorded in `VALIDATION.md`. No Ubuntu hardware, real XInput touchscreen toggle, real Wayland touchscreen, or physical mouse/keyboard recovery trial has been tested. Verify on your laptop using the trial before relying on this app.

Source: `touchswitch/backend.py` handles discovery and verified changes; `app.py` is the GUI; `watchdog.py` owns the independent trial; `recover.py` provides enable-only terminal recovery. All commands use argument lists with bounded execution time; none runs through a shell.
