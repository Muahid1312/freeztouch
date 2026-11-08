"""GTK 3 interface. Blocking system commands never run on the GTK thread."""
from dataclasses import asdict
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time

import gi
gi.require_version('Gtk', '3.0')
gi.require_version('Gdk', '3.0')
from gi.repository import Gdk, GLib, Gtk
from .backend import Backend
from . import wayland

CSS = b'''
window { background: #f5f6fa; }
.title { font-size: 26px; font-weight: bold; color: #202638; }
.subtitle { color: #586174; }
.status { font-size: 22px; font-weight: bold; padding: 16px; border-radius: 12px; background: #e5e9f0; }
.enabled { color: #176347; background: #dcf3e7; }
.disabled { color: #8a4217; background: #ffead5; }
button { padding: 12px 16px; border-radius: 8px; }
.message { color: #4b5364; }
'''


class Window(Gtk.Window):
    def __init__(self):
        super().__init__(title='TouchSwitch')
        self.set_default_size(480, 530)
        self.set_border_width(24)
        self.set_icon_from_file(str(Path(__file__).resolve().parent.parent / 'assets/touchswitch.svg'))
        self.backend = Backend()
        self.devices = []
        self.busy = False
        self.process = None
        self.trial_device = None
        self.deadline = 0
        self.trial_outcome = False
        self.session_confirmed = False
        self.confirmation_pending = False
        self.helper_confirmed = False
        self.closed = False
        self.enabled = None
        provider = Gtk.CssProvider()
        provider.load_from_data(CSS)
        Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), provider, 600)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        self.add(box)
        box.pack_start(self.label('TouchSwitch', 'title'), False, False, 0)
        box.pack_start(self.label('Your screen. Your choice.', 'subtitle'), False, False, 0)
        session = self.backend.session
        box.pack_start(self.label(f'{session.os_name} · {session.kind.upper()}', 'subtitle'), False, False, 0)
        select_label = Gtk.Label.new_with_mnemonic('_Touchscreen')
        select_label.set_xalign(0)
        box.pack_start(select_label, False, False, 0)
        self.selector = Gtk.ComboBoxText()
        select_label.set_mnemonic_widget(self.selector)
        self.selector.connect('changed', self.selection_changed)
        box.pack_start(self.selector, False, False, 0)
        self.details = self.label('', 'subtitle')
        box.pack_start(self.details, False, False, 0)
        self.indicator = self.label('Checking devices…', 'status')
        box.pack_start(self.indicator, False, False, 0)
        self.message = self.label('Use Tab to navigate, Enter or Space to activate controls.', 'message')
        self.message.set_selectable(True)
        box.pack_start(self.message, True, True, 0)
        self.enable = Gtk.Button.new_with_mnemonic('_Enable touchscreen')
        self.enable.get_style_context().add_class('suggested-action')
        self.enable.connect('clicked', lambda *_: self.enable_selected())
        self.disable = Gtk.Button.new_with_mnemonic('_Disable touchscreen')
        self.disable.connect('clicked', lambda *_: self.start_trial())
        box.pack_start(self.enable, False, False, 0)
        box.pack_start(self.disable, False, False, 0)
        self.keep = Gtk.Button.new_with_mnemonic('_Keep touchscreen disabled')
        self.keep.connect('clicked', self.confirm)
        self.keep.connect('key-press-event', self.confirm_key)
        self.keep.connect('button-release-event', self.confirm_pointer)
        self.keep.connect('mnemonic-activate', self.confirm_mnemonic)
        box.pack_start(self.keep, False, False, 0)
        self.refresh_button = Gtk.Button.new_with_mnemonic('_Refresh devices')
        self.refresh_button.connect('clicked', lambda *_: self.refresh())
        box.pack_start(self.refresh_button, False, False, 0)
        self.connect('delete-event', self.close)
        self.show_all()
        self.keep.set_no_show_all(True)
        self.keep.hide()
        self.refresh()
        GLib.timeout_add_seconds(5, self.poll)
        GLib.timeout_add(200, self.tick)
        GLib.timeout_add_seconds(1, self.heartbeat)

    @staticmethod
    def label(text, style):
        widget = Gtk.Label(label=text, xalign=0)
        widget.set_line_wrap(True)
        widget.set_max_width_chars(52)
        widget.get_style_context().add_class(style)
        return widget

    def selected(self):
        index = self.selector.get_active()
        return self.devices[index] if 0 <= index < len(self.devices) else None

    def controls(self):
        available = not self.busy and self.selected() is not None and not self.backend.session.limitation
        self.enable.set_sensitive(available and self.enabled is not True)
        self.disable.set_sensitive(available and self.enabled is True and self.process is None)
        self.selector.set_sensitive(not self.busy and self.process is None)
        self.refresh_button.set_sensitive(not self.busy and self.process is None)

    def status(self, enabled):
        self.enabled = enabled
        if self.backend.session.kind == 'wayland':
            text = '●  Not blocked by TouchSwitch' if enabled is True else ('○  Touch input blocked' if self.helper_confirmed else '○  Touch input blocked — trial') if enabled is False else '—  Status unavailable'
        else:
            text = '●  Enabled' if enabled is True else '○  Disabled' if enabled is False else '—  Status unavailable'
        self.indicator.set_text(text)
        context = self.indicator.get_style_context()
        for style in ('enabled', 'disabled'):
            context.remove_class(style)
        if enabled is not None:
            context.add_class('enabled' if enabled else 'disabled')
        self.controls()

    def work(self, action, done):
        self.busy = True
        self.controls()
        def worker():
            try:
                result, error = action(), None
            except Exception as exc:
                result, error = None, str(exc)
            def complete():
                if not self.closed:
                    self.busy = False
                    done(result, error)
                    self.controls()
                return False
            GLib.idle_add(complete)
        threading.Thread(target=worker, daemon=True).start()

    def refresh(self):
        if self.busy or self.process:
            return
        previous = self.selected()
        def done(devices, error):
            self.devices = []
            self.selector.remove_all()
            self.devices = devices or []
            for device in self.devices:
                self.selector.append_text(f'{device.name} · {Path(device.node).name}')
            if self.devices:
                index = self.devices.index(previous) if previous in self.devices else 0
                self.selector.set_active(index)
            else:
                self.status(None)
                self.details.set_text('No verified touchscreen selected')
                self.message.set_text(error or self.backend.session.limitation or
                                      'No dedicated touchscreen found. Connect one and refresh. Ambiguous or mixed input devices are excluded for safety.')
        self.work(self.backend.discover, done)

    def selection_changed(self, *_):
        device = self.selected()
        self.enabled = None
        if device is None or self.busy:
            self.controls()
            return
        self.details.set_text(device.node)
        if self.backend.session.limitation:
            self.status(None)
            self.message.set_text(self.backend.session.limitation)
            return
        self.work(lambda: self.backend.status(device), self.checked)

    def checked(self, enabled, error):
        self.status(None if error else enabled)
        if error:
            self.message.set_text(error)
        elif self.process is None:
            self.message.set_text('Wayland: Disable blocks touch events, without powering off the device. Authorization opens only the selected touchscreen. Closing the app restores touch.' if self.backend.session.kind == 'wayland' else 'Changes last for this X11 session. Every disable starts a 15-second recovery trial.')

    def enable_selected(self):
        device = self.selected()
        if device and not self.busy:
            if self.process:
                self.cancel_trial()
                return
            self.work(lambda: self.backend.set_enabled(device, True), self.checked)

    def start_trial(self):
        device = self.selected()
        if not device or self.busy or self.process:
            return
        trial_required = self.backend.session.kind != 'wayland'
        if trial_required:
            dialog = Gtk.MessageDialog(transient_for=self, modal=True, message_type=Gtk.MessageType.QUESTION,
                                      buttons=Gtk.ButtonsType.OK_CANCEL, text='Try disabling touch for 15 seconds?')
            dialog.format_secondary_text('Have a mouse or keyboard ready. Touch will automatically return unless you choose “Keep touchscreen disabled” using your mouse or keyboard. On Wayland, closing this app releases touch even after confirmation.')
            dialog.set_default_response(Gtk.ResponseType.CANCEL)
            response = dialog.run()
            dialog.destroy()
            if response != Gtk.ResponseType.OK:
                return
        try:
            command = (wayland.helper_command(device) if self.backend.session.kind == 'wayland' else
                       [sys.executable, '-m', 'touchswitch.watchdog', json.dumps(asdict(device))])
            self.process = subprocess.Popen(command,
                                            cwd=str(Path(__file__).resolve().parent.parent),
                                            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                            stderr=subprocess.PIPE, text=True, start_new_session=True)
            if self.backend.session.kind == 'wayland':
                os.set_blocking(self.process.stdin.fileno(), False)
        except (OSError, RuntimeError) as exc:
            if self.process:
                self.process.stdin.close()
                threading.Thread(target=self.process.wait, daemon=True).start()
                self.process = None
            self.message.set_text(f'Could not start recovery process: {exc}')
            return
        self.trial_device = device
        self.trial_outcome = False
        self.confirmation_pending = False
        self.helper_confirmed = False
        self.busy = True
        self.controls()
        self.message.set_text('Starting protected trial…' if trial_required else 'Blocking touchscreen…')
        process = self.process
        def listen():
            try:
                for line in process.stdout:
                    event = json.loads(line)
                    GLib.idle_add(self.trial_event, event)
                stderr = process.stderr.read().strip()
                code = process.wait()
                GLib.idle_add(self.trial_finished, code, stderr)
            except Exception as exc:
                if process.stdin and not process.stdin.closed:
                    process.stdin.close()
                process.wait()  # Let recovery finish before allowing another operation.
                GLib.idle_add(self.trial_finished, 1, str(exc))
        threading.Thread(target=listen, daemon=True).start()

    def trial_event(self, event):
        if self.closed:
            return False
        kind = event.get('event')
        if kind in ('restored', 'kept', 'error'):
            self.trial_outcome = True
        if kind == 'state':
            if event.get('blocked') is True:
                self.backend.blocked_key = self.trial_device.key
                if 'trial_remaining' in event:
                    if event.get('confirmed') is True and event['trial_remaining'] is None:
                        self.accept_confirmation()
                    elif event['trial_remaining'] is not None:
                        self.helper_confirmed = False
                        self.deadline = time.monotonic() + max(0, event['trial_remaining'])
                self.status(False)
        elif kind == 'disabled':
            if self.backend.session.kind == 'wayland':
                self.backend.blocked_key = self.trial_device.key
            self.busy = False
            self.deadline = time.monotonic() + event['seconds']
            self.status(False)
            self.keep.set_sensitive(True)
            if self.backend.session.kind == 'wayland':
                if event.get('confirmed') is True:
                    self.accept_confirmation()
                else:
                    # Compatibility with an older installed helper: cancel its
                    # trial automatically, without requiring a second user action.
                    self.request_confirmation()
            else:
                self.keep.show()
                self.keep.grab_focus()
                self.tick()
        elif kind == 'restored':
            self.backend.blocked_key = None
            self.helper_confirmed = False
            self.confirmation_pending = False
            self.deadline = 0
            self.keep.hide()
            self.status(True)
            self.message.set_text(('Touch input released: ' + event.get('reason', 'enabled by user') + '. The helper closed its device descriptor.') if self.backend.session.kind == 'wayland' else 'Trial ended. Touchscreen was re-enabled and its status verified.')
        elif kind == 'kept':
            self.accept_confirmation()
        elif kind == 'error':
            self.backend.blocked_key = None
            self.helper_confirmed = False
            self.confirmation_pending = False
            self.deadline = 0
            self.keep.hide()
            self.status(None)
            self.message.set_text('Recovery/control error: ' + event.get('message', 'Unknown error') +
                                  ' Use Enable touchscreen or the manual recovery instructions in README.')
        return False

    def accept_confirmation(self):
        # Only the helper acknowledgement/state may mark the trial confirmed.
        self.session_confirmed = True
        self.helper_confirmed = True
        self.confirmation_pending = False
        self.deadline = 0
        self.keep.hide()
        self.status(False)
        self.message.set_text('Helper confirmed: touch stays blocked until Enable touchscreen or closing this app.' if self.backend.session.kind == 'wayland' else 'Touchscreen remains disabled for this session. Use Enable touchscreen to restore it.')

    def request_confirmation(self):
        if not self.process or self.confirmation_pending or self.deadline <= time.monotonic():
            return
        try:
            if self.backend.session.kind == 'wayland':
                wayland.send(self.process, b'KEEP\n')
            else:
                self.process.stdin.write('KEEP\n')
                self.process.stdin.flush()
            self.confirmation_pending = True
            self.keep.set_sensitive(False)
            self.message.set_text('Waiting for helper to confirm that its trial timeout is cancelled…')
        except (OSError, ValueError) as exc:
            self.message.set_text(f'Could not confirm: {exc}. The recovery trial remains active.')

    @staticmethod
    def pointer_confirmation(event):
        source = event.get_source_device() if event else None
        return bool(source and source.get_source() in (Gdk.InputSource.MOUSE, Gdk.InputSource.TOUCHPAD))

    def confirm_pointer(self, _button, event):
        if event.button == 1 and self.pointer_confirmation(event):
            self.request_confirmation()
            return False
        return True  # Never turn an emulated touch click into confirmation.

    def confirm_key(self, _button, event):
        if event.keyval in (Gdk.KEY_space, Gdk.KEY_Return, Gdk.KEY_KP_Enter):
            self.request_confirmation()
            return True
        return False

    def confirm_mnemonic(self, *_):
        self.request_confirmation()
        return True

    def confirm(self, *_):
        # GTK can emit clicked after its originating key event has finished.
        # Explicit key/mnemonic handlers above preserve keyboard activation.
        event = Gtk.get_current_event()
        keyboard = event and event.type in (Gdk.EventType.KEY_PRESS, Gdk.EventType.KEY_RELEASE)
        if keyboard or self.pointer_confirmation(event):
            self.request_confirmation()
        else:
            self.message.set_text('Confirm with a mouse or keyboard. Touch confirmation is not accepted.')

    def cancel_trial(self):
        if self.process and self.process.stdin and not self.process.stdin.closed:
            if self.backend.session.kind == 'wayland':
                try:
                    wayland.send(self.process, b'RELEASE\n')
                except OSError:
                    pass
            self.process.stdin.close()
        self.keep.set_sensitive(False)
        self.deadline = 0
        self.message.set_text('Restoring touchscreen…')

    def trial_finished(self, code, stderr):
        if self.closed:
            return False
        self.process = None
        self.backend.blocked_key = None
        self.helper_confirmed = False
        self.confirmation_pending = False
        self.trial_device = None
        self.busy = False
        self.deadline = 0
        self.keep.hide()
        self.keep.set_sensitive(True)
        if not self.trial_outcome or (code and stderr):
            detail = f'Recovery process exited unexpectedly ({code}). '
            if self.backend.session.kind == 'wayland':
                if code == 126:
                    detail = 'Touchscreen authorization was cancelled. '
                elif code == 127:
                    detail = 'Authorization failed. Check the desktop polkit agent and installed policy. '
            self.message.set_text(detail + stderr[:400] +
                                  ' Recheck status and use Enable touchscreen if needed.')
        self.controls()
        # Verify independently after every trial, including unexpected helper exits.
        device = self.selected()
        message = self.message.get_text()
        if device:
            def done(value, error):
                self.status(None if error else value)
                self.message.set_text((message + '\n' + error) if error else message)
            self.work(lambda: self.backend.status(device), done)
        return False

    def heartbeat(self):
        if (self.process and self.trial_device and self.backend.session.kind == 'wayland'
                and self.backend.blocked_key == self.trial_device.key):
            try:
                wayland.send(self.process, b'PING\n')
            except (OSError, ValueError):
                self.cancel_trial()
        return not self.closed

    def tick(self):
        if self.deadline:
            seconds = max(0, int(self.deadline - time.monotonic()) + 1)
            self.keep.set_label(f'_Keep touchscreen disabled ({seconds}s)')
            self.keep.set_use_underline(True)
            self.message.set_text(f'Waiting for helper confirmation ({seconds}s remaining)…' if self.confirmation_pending else f'Trial: restoring touch in {seconds}s. Choose Keep touchscreen disabled using a mouse or keyboard.')
        return not self.closed

    def poll(self):
        if not self.busy and not self.process:
            device = self.selected()
            if device and not self.backend.session.limitation:
                def done(value, error):
                    self.status(None if error else value)
                    if error:
                        self.message.set_text(error)
                self.work(lambda: self.backend.status(device), done)
        return not self.closed

    def close(self, *_):
        self.closed = True
        self.cancel_trial()
        Gtk.main_quit()
        return False


def main():
    if os.geteuid() == 0:
        print('Run TouchSwitch as your normal desktop user, never with sudo.', file=sys.stderr)
        return 1
    if not Gtk.init_check()[0]:
        print('No graphical display available. Launch inside your Ubuntu desktop session.', file=sys.stderr)
        return 1
    Window()
    Gtk.main()
    return 0
