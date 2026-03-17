import Cairo from 'gi://cairo';
import Gio from 'gi://Gio';
import St from 'gi://St';

import * as Main from 'resource:///org/gnome/shell/ui/main.js';

const DBUS_IFACE = `
<node>
  <interface name="org.dorso.Overlay">
    <method name="SetOverlay">
      <arg name="intensity" type="d" direction="in"/>
      <arg name="r" type="d" direction="in"/>
      <arg name="g" type="d" direction="in"/>
      <arg name="b" type="d" direction="in"/>
      <arg name="mode" type="s" direction="in"/>
    </method>
    <method name="Clear"/>
  </interface>
</node>`;

let _widgets = [];
let _dbusId = null;
let _nameId = 0;

// Current overlay state — shared with repaint callbacks
let _intensity = 0;
let _r = 0, _g = 0, _b = 0;
let _mode = 'glow';

function _drawGlow(cr, w, h, r, g, b, intensity) {
    const cx = w / 2, cy = h / 2;
    const maxR = Math.sqrt(cx * cx + cy * cy);
    const innerR = maxR * (1.0 - intensity * 0.6);

    const pat = new Cairo.RadialGradient(cx, cy, innerR, cx, cy, maxR);
    pat.addColorStopRGBA(0, r, g, b, 0.0);
    pat.addColorStopRGBA(1, r, g, b, intensity * 0.6);

    cr.setSource(pat);
    cr.rectangle(0, 0, w, h);
    cr.fill();
}

function _drawBorder(cr, w, h, r, g, b, intensity) {
    const border = Math.max(1, Math.floor(Math.min(w, h) * 0.08 * intensity));
    const alpha = intensity * 0.7;

    let p = new Cairo.LinearGradient(0, 0, 0, border);
    p.addColorStopRGBA(0, r, g, b, alpha);
    p.addColorStopRGBA(1, r, g, b, 0.0);
    cr.setSource(p);
    cr.rectangle(0, 0, w, border);
    cr.fill();

    p = new Cairo.LinearGradient(0, h, 0, h - border);
    p.addColorStopRGBA(0, r, g, b, alpha);
    p.addColorStopRGBA(1, r, g, b, 0.0);
    cr.setSource(p);
    cr.rectangle(0, h - border, w, border);
    cr.fill();

    p = new Cairo.LinearGradient(0, 0, border, 0);
    p.addColorStopRGBA(0, r, g, b, alpha);
    p.addColorStopRGBA(1, r, g, b, 0.0);
    cr.setSource(p);
    cr.rectangle(0, 0, border, h);
    cr.fill();

    p = new Cairo.LinearGradient(w, 0, w - border, 0);
    p.addColorStopRGBA(0, r, g, b, alpha);
    p.addColorStopRGBA(1, r, g, b, 0.0);
    cr.setSource(p);
    cr.rectangle(w - border, 0, border, h);
    cr.fill();
}

function _drawSolid(cr, w, h, r, g, b, intensity) {
    cr.setSourceRGBA(r, g, b, intensity * 0.4);
    cr.rectangle(0, 0, w, h);
    cr.fill();
}

function _ensureWidgets() {
    const monitors = Main.layoutManager.monitors;
    if (_widgets.length === monitors.length)
        return;

    _destroyWidgets();

    for (let i = 0; i < monitors.length; i++) {
        const mon = monitors[i];
        const widget = new St.DrawingArea({
            x: mon.x,
            y: mon.y,
            width: mon.width,
            height: mon.height,
            reactive: false,
        });
        widget.connect('repaint', (area) => {
            const cr = area.get_context();
            cr.setOperator(Cairo.Operator.CLEAR);
            cr.paint();
            cr.setOperator(Cairo.Operator.OVER);

            if (_intensity > 0) {
                if (_mode === 'border')
                    _drawBorder(cr, mon.width, mon.height, _r, _g, _b, _intensity);
                else if (_mode === 'solid')
                    _drawSolid(cr, mon.width, mon.height, _r, _g, _b, _intensity);
                else
                    _drawGlow(cr, mon.width, mon.height, _r, _g, _b, _intensity);
            }

            cr.$dispose();
        });
        widget.visible = false;
        Main.layoutManager.addTopChrome(widget, {
            affectsStruts: false,
            trackFullscreen: false,
        });
        _widgets.push(widget);
    }
}

function _destroyWidgets() {
    for (const w of _widgets) {
        w.get_parent()?.remove_child(w);
        w.destroy();
    }
    _widgets = [];
}

function _setOverlay(intensity, r, g, b, mode) {
    _intensity = intensity;
    _r = r;
    _g = g;
    _b = b;
    _mode = mode;

    if (intensity <= 0) {
        for (const w of _widgets)
            w.visible = false;
        return;
    }

    _ensureWidgets();
    for (const w of _widgets) {
        w.visible = true;
        w.queue_repaint();
    }
}

function _clear() {
    _intensity = 0;
    for (const w of _widgets)
        w.visible = false;
}

function _onDbusCall(connection, sender, path, ifaceName, methodName, params, invocation) {
    if (methodName === 'SetOverlay') {
        const [intensity, r, g, b, mode] = params.deepUnpack();
        _setOverlay(intensity, r, g, b, mode);
        invocation.return_value(null);
    } else if (methodName === 'Clear') {
        _clear();
        invocation.return_value(null);
    }
}

export default class DorsoOverlayExtension {
    enable() {
        const nodeInfo = Gio.DBusNodeInfo.new_for_xml(DBUS_IFACE);
        _dbusId = Gio.DBus.session.register_object(
            '/org/dorso/Overlay',
            nodeInfo.interfaces[0],
            _onDbusCall,
            null,
            null
        );
        _nameId = Gio.bus_own_name_on_connection(
            Gio.DBus.session,
            'org.dorso.Overlay',
            Gio.BusNameOwnerFlags.NONE,
            null,
            null
        );
    }

    disable() {
        _clear();
        _destroyWidgets();
        if (_dbusId) {
            Gio.DBus.session.unregister_object(_dbusId);
            _dbusId = null;
        }
        if (_nameId) {
            Gio.bus_unown_name(_nameId);
            _nameId = 0;
        }
    }
}
