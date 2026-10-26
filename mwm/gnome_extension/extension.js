// SPDX-License-Identifier: MIT
import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';

export default class MwmLiteFullscreen extends Extension {
    enable() {
        const base = GLib.getenv('XDG_STATE_HOME') || GLib.build_filenamev([GLib.get_home_dir(), '.local', 'state']);
        this._marker = Gio.File.new_for_path(GLib.build_filenamev([base, 'mwm-lite', 'display.json']));
        this._source = GLib.timeout_add_seconds(GLib.PRIORITY_DEFAULT, 1, () => {
            this._update();
            return GLib.SOURCE_CONTINUE;
        });
    }

    _sessionAlive() {
        try {
            const [ok, bytes] = this._marker.load_contents(null);
            if (!ok)
                return false;
            const session = JSON.parse(new TextDecoder().decode(bytes));
            if (!Number.isSafeInteger(session.pid) || session.pid <= 0 || !/^\d+$/.test(session.start))
                return false;
            const file = Gio.File.new_for_path(`/proc/${session.pid}/stat`);
            const [read, data] = file.load_contents(null);
            const stat = new TextDecoder().decode(data);
            const fields = stat.slice(stat.lastIndexOf(')') + 1).trim().split(/\s+/);
            return read && fields[0] !== 'Z' && fields[19] === session.start;
        } catch (_) {
            return false;
        }
    }

    _update() {
        if (!this._sessionAlive())
            return;
        const monitor = global.display.get_primary_monitor();
        const rectangle = global.display.get_monitor_geometry(monitor);
        for (const actor of global.get_window_actors()) {
            const window = actor.meta_window;
            const name = (window.get_wm_class() || '').toLowerCase();
            if (name === 'waydroid' || name.startsWith('waydroid.')) {
                if (window.get_monitor() !== monitor)
                    window.move_to_monitor(monitor);
                if (!window.is_fullscreen())
                    window.make_fullscreen();
            } else if (window.get_title() === 'MWM Lite FPS') {
                window.make_above();
                window.move_frame(false, rectangle.x + 12, rectangle.y + 12);
            }
        }
    }

    disable() {
        if (this._source)
            GLib.Source.remove(this._source);
        this._source = null;
        this._marker = null;
    }
}
