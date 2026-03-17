"""System tray icon using StatusNotifierItem + DBusMenu.

Uses ItemIsMenu=True so GNOME's AppIndicator extension shows the
menu positioned under the tray icon on left click.
"""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path
from typing import Callable

from PIL import Image, ImageDraw

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gio, GLib

logger = logging.getLogger(__name__)


def _icon_dir() -> Path:
    """Return path to bundled icons in assets/icons/."""
    # Look relative to this source file
    here = Path(__file__).resolve().parent.parent / "assets" / "icons"
    if here.is_dir():
        return here
    # Fallback: generate simple circles in a temp dir
    return _generate_fallback_icons()


def _generate_fallback_icons() -> Path:
    d = Path(tempfile.mkdtemp(prefix="dorso-icons-"))
    colors = {
        "good": "#4CAF50", "bad": "#F44336", "away": "#9E9E9E",
        "paused": "#FF9800", "calibrating": "#2196F3", "disabled": "#616161",
    }
    for name, color in colors.items():
        img = Image.new("RGBA", (22, 22), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        draw.ellipse([2, 2, 20, 20], fill=color)
        img.save(d / f"dorso-{name}.png")
    return d


SNI_PATH = "/StatusNotifierItem"
SNI_INTERFACE = "org.kde.StatusNotifierItem"
DBUSMENU_PATH = "/MenuBar"
DBUSMENU_INTERFACE = "com.canonical.dbusmenu"

SNI_XML = """
<node>
  <interface name="org.kde.StatusNotifierItem">
    <method name="Activate">
      <arg name="x" type="i" direction="in"/>
      <arg name="y" type="i" direction="in"/>
    </method>
    <method name="SecondaryActivate">
      <arg name="x" type="i" direction="in"/>
      <arg name="y" type="i" direction="in"/>
    </method>
    <method name="ContextMenu">
      <arg name="x" type="i" direction="in"/>
      <arg name="y" type="i" direction="in"/>
    </method>
    <signal name="NewIcon"/>
    <signal name="NewStatus"><arg type="s"/></signal>
    <property name="Category" type="s" access="read"/>
    <property name="Id" type="s" access="read"/>
    <property name="Title" type="s" access="read"/>
    <property name="Status" type="s" access="read"/>
    <property name="IconName" type="s" access="read"/>
    <property name="IconThemePath" type="s" access="read"/>
    <property name="Menu" type="o" access="read"/>
    <property name="ItemIsMenu" type="b" access="read"/>
  </interface>
</node>
"""

DBUSMENU_XML = """
<node>
  <interface name="com.canonical.dbusmenu">
    <method name="GetLayout">
      <arg name="parentId" type="i" direction="in"/>
      <arg name="recursionDepth" type="i" direction="in"/>
      <arg name="propertyNames" type="as" direction="in"/>
      <arg name="revision" type="u" direction="out"/>
      <arg name="layout" type="(ia{sv}av)" direction="out"/>
    </method>
    <method name="GetGroupProperties">
      <arg name="ids" type="ai" direction="in"/>
      <arg name="propertyNames" type="as" direction="in"/>
      <arg name="properties" type="a(ia{sv})" direction="out"/>
    </method>
    <method name="Event">
      <arg name="id" type="i" direction="in"/>
      <arg name="eventId" type="s" direction="in"/>
      <arg name="data" type="v" direction="in"/>
      <arg name="timestamp" type="u" direction="in"/>
    </method>
    <method name="AboutToShow">
      <arg name="id" type="i" direction="in"/>
      <arg name="needUpdate" type="b" direction="out"/>
    </method>
    <signal name="LayoutUpdated">
      <arg name="revision" type="u"/>
      <arg name="parent" type="i"/>
    </signal>
    <property name="Version" type="u" access="read"/>
    <property name="TextDirection" type="s" access="read"/>
    <property name="Status" type="s" access="read"/>
    <property name="IconThemePath" type="as" access="read"/>
  </interface>
</node>
"""

_STATUS_LABELS = {
    "good": "Bonne posture",
    "bad": "Mauvaise posture",
    "away": "Absent",
    "paused": "En pause",
    "calibrating": "Calibration…",
    "disabled": "Désactivé",
}


class TrayIcon:
    """System tray icon with DBusMenu."""

    def __init__(
        self,
        on_toggle: Callable[[], None],
        on_calibrate: Callable[[], None],
        on_settings: Callable[[], None],
        on_analytics: Callable[[], None],
        on_quit: Callable[[], None],
    ) -> None:
        self._on_toggle = on_toggle
        self._on_calibrate = on_calibrate
        self._on_settings = on_settings
        self._on_analytics = on_analytics
        self._on_quit = on_quit
        self._current_state = "disabled"
        self._bus: Gio.DBusConnection | None = None
        self._sni_reg_id = 0
        self._menu_reg_id = 0
        self._bus_name_id = 0
        self._icons = _icon_dir()
        self._revision = 1

    def start(self) -> None:
        try:
            self._bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        except Exception as e:
            logger.warning("Cannot connect to session bus: %s", e)
            return

        # Register SNI object
        sni_info = Gio.DBusNodeInfo.new_for_xml(SNI_XML)
        self._sni_reg_id = self._bus.register_object(
            SNI_PATH, sni_info.interfaces[0],
            self._on_sni_method, self._on_sni_prop, None,
        )

        # Register DBusMenu object (with property handler for Version etc.)
        menu_info = Gio.DBusNodeInfo.new_for_xml(DBUSMENU_XML)
        self._menu_reg_id = self._bus.register_object(
            DBUSMENU_PATH, menu_info.interfaces[0],
            self._on_menu_method, self._on_menu_prop, None,
        )

        self._bus_name_id = Gio.bus_own_name_on_connection(
            self._bus, "org.kde.StatusNotifierItem-dorso",
            Gio.BusNameOwnerFlags.NONE, None, None,
        )

        try:
            self._bus.call_sync(
                "org.kde.StatusNotifierWatcher",
                "/StatusNotifierWatcher",
                "org.kde.StatusNotifierWatcher",
                "RegisterStatusNotifierItem",
                GLib.Variant("(s)", ("org.kde.StatusNotifierItem-dorso",)),
                None, Gio.DBusCallFlags.NONE, 1000, None,
            )
            logger.info("Registered with StatusNotifierWatcher")
        except Exception as e:
            logger.warning("Could not register with watcher: %s", e)

    def update_state(self, state: str) -> None:
        _valid = ("good", "bad", "away", "paused", "calibrating", "disabled")
        if state not in _valid:
            return
        old = self._current_state
        self._current_state = state
        if self._bus and self._sni_reg_id:
            try:
                self._bus.emit_signal(None, SNI_PATH, SNI_INTERFACE, "NewIcon", None)
            except Exception:
                pass
            # Update menu revision so status line refreshes
            if old != state:
                self._revision += 1
                try:
                    self._bus.emit_signal(
                        None, DBUSMENU_PATH, DBUSMENU_INTERFACE,
                        "LayoutUpdated",
                        GLib.Variant("(ui)", (self._revision, 0)),
                    )
                except Exception:
                    pass

    def stop(self) -> None:
        if self._bus:
            if self._sni_reg_id:
                self._bus.unregister_object(self._sni_reg_id)
            if self._menu_reg_id:
                self._bus.unregister_object(self._menu_reg_id)
            if self._bus_name_id:
                Gio.bus_unown_name(self._bus_name_id)

    # -- SNI interface --

    def _on_sni_method(self, conn, sender, path, iface, method, params, inv):
        inv.return_value(None)

    def _on_sni_prop(self, conn, sender, path, iface, prop):
        props = {
            "Category": GLib.Variant("s", "ApplicationStatus"),
            "Id": GLib.Variant("s", "dorso"),
            "Title": GLib.Variant("s", "Dorso — Posture Monitor"),
            "Status": GLib.Variant("s", "Active"),
            "IconName": GLib.Variant("s", f"dorso-{self._current_state}"),
            "IconThemePath": GLib.Variant("s", str(self._icons)),
            "Menu": GLib.Variant("o", DBUSMENU_PATH),
            "ItemIsMenu": GLib.Variant("b", True),
        }
        return props.get(prop)

    # -- DBusMenu interface --

    def _on_menu_prop(self, conn, sender, path, iface, prop):
        """DBusMenu properties required by GNOME's AppIndicator extension."""
        props = {
            "Version": GLib.Variant("u", 4),
            "TextDirection": GLib.Variant("s", "ltr"),
            "Status": GLib.Variant("s", "normal"),
            "IconThemePath": GLib.Variant("as", []),
        }
        return props.get(prop)

    def _on_menu_method(self, conn, sender, path, iface, method, params, inv):
        if method == "GetLayout":
            inv.return_value(GLib.Variant("(u(ia{sv}av))", (
                self._revision, self._build_layout(),
            )))
        elif method == "GetGroupProperties":
            inv.return_value(GLib.Variant.new_tuple(
                GLib.Variant.new_array(GLib.VariantType("(ia{sv})"), []),
            ))
        elif method == "Event":
            args = params.unpack()
            item_id = args[0]
            event_id = args[1]
            if event_id == "clicked":
                self._handle_click(item_id)
            inv.return_value(None)
        elif method == "AboutToShow":
            # Return True to signal the menu may have changed
            inv.return_value(GLib.Variant("(b)", (True,)))
        else:
            inv.return_dbus_error("org.freedesktop.DBus.Error.UnknownMethod", "")

    def _build_layout(self) -> tuple:
        """Build the DBusMenu layout (matching Telegram's format)."""
        status = _STATUS_LABELS.get(self._current_state, "—")

        def item(id, label, enabled=True, visible=True):
            return GLib.Variant("(ia{sv}av)", (id, {
                "label": GLib.Variant("s", label),
                "enabled": GLib.Variant("b", enabled),
                "visible": GLib.Variant("b", visible),
            }, []))

        def sep(id):
            return GLib.Variant("(ia{sv}av)", (id, {
                "type": GLib.Variant("s", "separator"),
                "visible": GLib.Variant("b", True),
            }, []))

        children = [
            item(10, f"Status: {status}", enabled=False),
            sep(11),
            item(1, "Activer/Désactiver"),
            item(2, "Recalibrer"),
            sep(12),
            item(3, "Analytiques"),
            item(4, "Paramètres"),
            sep(13),
            item(5, "Quitter"),
        ]
        return (0, {"children-display": GLib.Variant("s", "submenu")}, children)

    def _handle_click(self, item_id: int) -> None:
        actions = {
            1: self._on_toggle,
            2: self._on_calibrate,
            3: self._on_analytics,
            4: self._on_settings,
            5: self._on_quit,
        }
        cb = actions.get(item_id)
        if cb:
            cb()
