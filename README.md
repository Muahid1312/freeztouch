# TouchSwitch

A compact GTK application that temporarily blocks touchscreen input on Ubuntu Wayland, or changes a verified touchscreen's enabled property on X11. The GUI always runs as your normal user. It includes a device selector, keyboard-accessible controls, and a protected 15-second trial.

## Install and launch on Ubuntu 26.04

From the existing project directory:

```sh
sudo apt update
sudo apt install python3 python3-gi gir1.2-gtk-3.0 udev pkexec polkitd libsystemd0
sudo /usr/bin/python3 -I install-system.py
./launch.sh
```

The one-time privileged installer copies **only** the standalone helper and its polkit policy:

- `/usr/libexec/touchswitch-helper` — root:root, mode 0755
- `/usr/share/polkit-1/actions/org.touchswitch.block.policy` — root:root, mode 0644

It validates root-owned directories and refuses group/world-writable or symlinked installation directories. The GUI also checks the installed helper, policy, `pkexec`, and their parent directories before offering Wayland controls. Root runs the helper using Python isolated mode (`-I`); it never imports code from this checkout. The source helper is `privileged/touchswitch-helper`.

Run the GUI **without sudo**. No pip packages are needed. `requirements.txt` lists apt dependencies. An active local Wayland session managed by systemd-logind and a desktop polkit authentication agent are required; Ubuntu GNOME normally supplies both. The helper's ioctl ABI is supported on Linux **amd64 and arm64**. Missing or unsupported prerequisites are reported rather than bypassed.

Optional application-menu launcher, installed as your normal user:

```sh
./install-launcher.py
```

This installs the desktop launcher, SVG icon, and command wrapper under `~/.local` (`XDG_DATA_HOME` is respected). Keep this checkout in place. Existing launcher files are preserved; remove them explicitly before reinstalling. After updating TouchSwitch, rerun the privileged installer above to update the installed helper and policy.

For the existing X11 backend only, also install `xinput`:

```sh
sudo apt install xinput
```

## Wayland: what Disable and Enable mean

Select your touchscreen, for example **Wacom HID 48CA Finger**. TouchSwitch discovers event nodes each time; `/dev/input/event8` is not hardcoded. If the node or sysfs identity changes after reconnecting, refresh and select the panel again.

- **Disable touchscreen** requests polkit authorization for the fixed touchscreen helper. The helper opens one verified device read-only, obtains Linux evdev `EVIOCGRAB`, and continuously drains/discards its events. This **blocks touch input**; it does not power off the hardware or change compositor settings.
- **Touch input blocked** appears only after the helper confirms a successful exclusive grab. The helper stays alive to own that descriptor; another process cannot release its grab by opening a different descriptor.
- **Enable touchscreen** tells that same helper to release the grab and close its descriptor. It does not require a second authorization prompt.
- **Not blocked by TouchSwitch** means this application holds no grab. It does not claim that the hardware is powered on, that another application has not grabbed it, or that the compositor accepts touch.

Multiple dedicated touchscreens appear in the selector. This version holds one Wayland grab at a time; enable the selected panel before selecting another. No mouse, keyboard, or touchpad is intentionally grabbed.

The first disable starts a **15-second helper-side trial**. Choose **Keep touchscreen disabled** using a mouse or keyboard before its countdown reaches zero; touch confirmation is rejected. The GUI waits for the helper to acknowledge cancellation of its `CLOCK_BOOTTIME` trial deadline before showing confirmed blocking and clearing the countdown. If you do not confirm, touch returns automatically. After that acknowledgement, later Wayland disables in the same app session are automatically confirmed without another trial prompt or button. Restarting the app resets this session preference. Heartbeat, connection, process and desktop-session recovery remain active even after confirmation.

Touch is released on Enable, GUI exit/crash, EOF on its private control pipe, lost GUI heartbeat (at most four seconds), helper termination, or the desktop session ending/becoming inactive. A pinned GUI pidfd and logind session checks provide independent recovery. Normal termination explicitly ungrabs and closes; even SIGKILL causes the kernel to close the descriptor and release the grab. Failed grabs, including `EBUSY`, never report blocked status.

On disconnect, the helper closes the fd and reports the error. On suspend/resume it releases as soon as execution resumes, using boottime/monotonic divergence or heartbeat expiry, and **does not automatically re-grab**. Refresh and authorize another disable if needed (with a trial if this app session has not yet confirmed one). Device failures, a stalled kernel, or a powered-off/suspended machine cannot be fixed by a GUI timer. Closing the app releases even a confirmed Wayland block.

Use **Tab / Shift+Tab**, selector arrow keys, and **Space / Enter**. **Alt+T** selects the device; **Alt+E** enables/releases; **Alt+D** starts a trial; **Alt+K** keeps it blocked; **Alt+R** refreshes. Keep a working physical mouse or keyboard available for your first real-device trial.

## Device validation and privilege boundary

The unprivileged GUI sends a SHA-256 identity token (sysfs path plus device name) and its own PID to the fixed helper through `pkexec --disable-internal-agent`. It sends no device path, shell text, arbitrary command, or environment configuration to execute.

The root helper independently enumerates `/sys/class/input/event*`, resolves the token uniquely, and validates:

1. udev `ID_INPUT_TOUCHSCREEN=1`, the expected kernel-created node, and the active session's seat. Mouse, touchpad, keyboard, tablet, tablet pad, joystick, pointing-stick, accelerometer, or switch classifications reject the device.
2. The opened character fd's major/minor against sysfs, its `/sys/dev/char` identity, and a second udev/name/path check after opening. `O_NOFOLLOW` prevents following a device-node symlink.
3. Kernel capability ioctls on that exact fd: direct input, absolute X/Y touch coordinates, no relative motion, keyboard/mouse/pen buttons, switches, or unrelated axes. Only finger/touch/tool-count keys are permitted. Ambiguous/mixed devices are refused even if their name contains “Finger”.
4. The polkit-supplied `PKEXEC_UID`, GUI process owner/pidfd, local active Wayland session and seat from logind. GNOME apps launched in user-manager scopes use logind's graphical session for the authenticated uid when the PID has no session cgroup.

Communication uses inherited anonymous stdin/stdout pipes owned by the authenticated caller, with no named/public socket. The only GUI messages are bounded `PING`, `KEEP`, and `RELEASE`; malformed messages release the fd. Helper responses contain state/errors, never touchscreen events. A frozen GUI that stops consuming responses also cannot hold touch indefinitely.

The action uses `auth_admin` for active sessions and denies inactive/remote use. It does not retain authorization (`auth_admin_keep` is not used). Opening/grabbing each selected panel requires authorization. Releasing an already authorized grab uses its existing connection. No input group membership, global permissions, udev rules, boot settings, blacklists, or persistent input settings are changed.

## Emergency release

First use **Enable touchscreen** or close TouchSwitch. If the GUI is frozen, wait four seconds for the helper heartbeat to expire.

From a keyboard-accessible terminal, this administrator command terminates **only TouchSwitch's installed root helpers**, releasing their descriptors:

```sh
sudo /usr/bin/pkill -TERM -f '^/usr/bin/python3 -I /usr/libexec/touchswitch-helper '
```

It affects all TouchSwitch grabs on the machine, not other applications. If a helper fails to terminate normally, the same narrowly matched command with `-KILL` closes its fd through kernel process cleanup. A nonzero `pkill` result can mean no helper is running. You cannot release another process's EVIOCGRAB by issuing an ungrab on a newly opened fd.

`/usr/bin/python3 -m touchswitch.recover` prints these Wayland recovery instructions. On X11 it retains its enable-only recovery behavior:

```sh
/usr/bin/python3 -m touchswitch.recover
/usr/bin/python3 -m touchswitch.recover --node /dev/input/eventN
```

For X11, the app still requires a unique direct-touch XInput slave pointer, matching `Device Node`, no keyboard class, and a boolean `Device Enabled` property. It checks status after writes, including failures. A confirmed X11 disable follows the previous session-only behavior; unlike the Wayland grab, it can remain after GUI exit.

## Tests and real-device verification

```sh
/usr/bin/python3 -m unittest discover -s tests -v
```

Tests mock system commands, kernel ioctls, device fds, session metadata, and polkit/helper responses; they never grab host input devices. GTK tests run when a display is available and explicitly skip otherwise. The original X11 watchdog subprocess tests also exercise a real 15-second timeout against a fake backend.

See [VALIDATION.md](VALIDATION.md) for actual results and untested integration points. Automated tests do **not** establish compatibility with your Wacom HID 48CA Finger. Still required on your Ubuntu Wayland laptop: helper installation and polkit dialog, actual classification/capability acceptance, first trial expiration, explicit confirmation/release, preserved mouse/keyboard operation, app termination, disconnect, and suspend/resume. If safe validation rejects the panel, the app reports why and makes no grab; do not relax input-device permissions to work around it.

## API verification

Upstream sources retrieved and reviewed on 2026-11-07:

- [Linux input UAPI](https://github.com/torvalds/linux/blob/master/include/uapi/linux/input.h): `EVIOCGRAB`, `EVIOCGBIT`, and `EVIOCGPROP` definitions.
- [Linux evdev implementation](https://github.com/torvalds/linux/blob/master/drivers/input/evdev.c): exclusive event routing, `EBUSY` on existing grabs, explicit ungrab, and `evdev_release()` ungrabbing on fd close.
- [Linux input event documentation](https://github.com/torvalds/linux/blob/master/Documentation/input/event-codes.rst): direct/pointer properties and capability meanings.
- [pkexec documentation](https://github.com/polkit-org/polkit/blob/master/docs/man/pkexec.xml): sanitized environment, `PKEXEC_UID`, action executable annotation, internal-agent disabling, and the need to validate arguments in the invoked program.
- [systemd login API](https://github.com/systemd/systemd/blob/main/src/systemd/sd-login.h): authenticated session owner, graphical session fallback, type, seat, and active-session checks.

## Uninstall

Close TouchSwitch first, then remove its root-installed files:

```sh
sudo rm /usr/libexec/touchswitch-helper
sudo rm /usr/share/polkit-1/actions/org.touchswitch.block.policy
```

Optional per-user launcher files are `~/.local/share/applications/TouchSwitch.desktop`, `~/.local/share/icons/hicolor/scalable/apps/touchswitch.svg`, and `~/.local/bin/touchswitch` (adjust the data paths if using `XDG_DATA_HOME`). Removing the helper file alone does not terminate an already running process; close the GUI or use the emergency release first.
