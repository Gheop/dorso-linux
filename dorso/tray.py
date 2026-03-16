"""System tray icon using Gio.DBusConnection (StatusNotifierItem).

Works with GTK4 without conflicting with GTK3. Uses the freedesktop
StatusNotifierItem / DBusMenu protocol supported by KDE, GNOME (with
extension), Sway, etc.

Fallback: if SNI is not available, logs a warning and runs without tray.
"""

from __future__ import annotations

import io
import logging
import struct
import tempfile
from pathlib import Path
from typing import Callable

from PIL import Image, ImageDraw

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gio, GLib

logger = logging.getLogger(__name__)


def _make_icon_png(color: str, size: int = 22) -> bytes:
    """Create a colored circle icon as PNG bytes."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    margin = 2
    draw.ellipse([margin, margin, size - margin, size - margin], fill=color)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _make_icon_pixmap(color: str, size: int = 22) -> tuple[int, int, bytes]:
    """Create icon as ARGB pixmap data for StatusNotifierItem.

    Returns (width, height, argb_bytes).
    """
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    margin = 2
    draw.ellipse([margin, margin, size - margin, size - margin], fill=color)
    # Convert RGBA to ARGB (network byte order)
    pixels = img.tobytes("raw", "RGBA")
    argb = bytearray(len(pixels))
    for i in range(0, len(pixels), 4):
        r, g, b, a = pixels[i], pixels[i + 1], pixels[i + 2], pixels[i + 3]
        argb[i] = a
        argb[i + 1] = r
        argb[i + 2] = g
        argb[i + 3] = b
    return size, size, bytes(argb)


# Save icons to temp files for icon path approach
_icon_dir: Path | None = None

ICON_COLORS = {
    "good": "#4CAF50",
    "bad": "#F44336",
    "away": "#9E9E9E",
    "paused": "#FF9800",
    "calibrating": "#2196F3",
    "disabled": "#616161",
}


def _ensure_icon_files() -> Path:
    """Save icon PNGs to a temp dir and return the dir path."""
    global _icon_dir
    if _icon_dir and _icon_dir.exists():
        return _icon_dir
    _icon_dir = Path(tempfile.mkdtemp(prefix="dorso-icons-"))
    for name, color in ICON_COLORS.items():
        (_icon_dir / f"dorso-{name}.png").write_bytes(_make_icon_png(color, 22))
    return _icon_dir


# DBusMenu XML interface (minimal subset)
DBUSMENU_INTERFACE = "com.canonical.dbusmenu"
DBUSMENU_PATH = "/MenuBar"

SNI_INTERFACE = "org.kde.StatusNotifierItem"
SNI_PATH = "/StatusNotifierItem"

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
    <signal name="NewTitle"/>
    <signal name="NewStatus">
      <arg type="s"/>
    </signal>
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
  </interface>
</node>
"""


class TrayIcon:
    """System tray icon using StatusNotifierItem over D-Bus."""

    def __init__(
        self,
        on_toggle: Callable[[], None],
        on_calibrate: Callable[[], None],
        on_quit: Callable[[], None],
    ) -> None:
        self._on_toggle = on_toggle
        self._on_calibrate = on_calibrate
        self._on_quit = on_quit
        self._current_state = "disabled"
        self._bus: Gio.DBusConnection | None = None
        self._sni_reg_id = 0
        self._menu_reg_id = 0
        self._bus_name_id = 0
        self._icon_dir = _ensure_icon_files()
        self._menu_revision = 1

    def start(self) -> None:
        """Register on the session bus as a StatusNotifierItem."""
        try:
            self._bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        except Exception as e:
            logger.warning("Cannot connect to session bus for tray: %s", e)
            return

        # Register SNI object
        sni_info = Gio.DBusNodeInfo.new_for_xml(SNI_XML)
        self._sni_reg_id = self._bus.register_object(
            SNI_PATH,
            sni_info.interfaces[0],
            self._on_sni_method_call,
            self._on_sni_get_property,
            None,
        )

        # Register DBusMenu object
        menu_info = Gio.DBusNodeInfo.new_for_xml(DBUSMENU_XML)
        self._menu_reg_id = self._bus.register_object(
            DBUSMENU_PATH,
            menu_info.interfaces[0],
            self._on_menu_method_call,
            None,
            None,
        )

        # Own a unique bus name
        self._bus_name_id = Gio.bus_own_name_on_connection(
            self._bus,
            "org.kde.StatusNotifierItem-dorso",
            Gio.BusNameOwnerFlags.NONE,
            None,
            None,
        )

        # Register with the StatusNotifierWatcher
        self._register_with_watcher()

    def _register_with_watcher(self) -> None:
        if not self._bus:
            return
        try:
            self._bus.call_sync(
                "org.kde.StatusNotifierWatcher",
                "/StatusNotifierWatcher",
                "org.kde.StatusNotifierWatcher",
                "RegisterStatusNotifierItem",
                GLib.Variant("(s)", ("org.kde.StatusNotifierItem-dorso",)),
                None,
                Gio.DBusCallFlags.NONE,
                1000,
                None,
            )
            logger.info("Registered with StatusNotifierWatcher")
        except Exception as e:
            logger.warning("Could not register with StatusNotifierWatcher: %s", e)

    def update_state(self, state: str) -> None:
        """Update tray icon state."""
        if state not in ICON_COLORS:
            return
        self._current_state = state
        if self._bus and self._sni_reg_id:
            try:
                self._bus.emit_signal(
                    None, SNI_PATH, SNI_INTERFACE, "NewIcon", None
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

    def _on_sni_method_call(
        self, connection, sender, path, interface, method, params, invocation
    ) -> None:
        if method == "Activate":
            self._on_toggle()
            invocation.return_value(None)
        elif method == "ContextMenu":
            # Context menu is handled via DBusMenu
            invocation.return_value(None)
        elif method == "SecondaryActivate":
            invocation.return_value(None)
        else:
            invocation.return_dbus_error("org.freedesktop.DBus.Error.UnknownMethod", "")

    def _on_sni_get_property(
        self, connection, sender, path, interface, prop_name
    ) -> GLib.Variant:
        if prop_name == "Category":
            return GLib.Variant("s", "ApplicationStatus")
        elif prop_name == "Id":
            return GLib.Variant("s", "dorso")
        elif prop_name == "Title":
            return GLib.Variant("s", "Dorso — Posture Monitor")
        elif prop_name == "Status":
            return GLib.Variant("s", "Active")
        elif prop_name == "IconName":
            return GLib.Variant("s", f"dorso-{self._current_state}")
        elif prop_name == "IconThemePath":
            return GLib.Variant("s", str(self._icon_dir))
        elif prop_name == "Menu":
            return GLib.Variant("o", DBUSMENU_PATH)
        elif prop_name == "ItemIsMenu":
            return GLib.Variant("b", False)
        return None

    def _on_menu_method_call(
        self, connection, sender, path, interface, method, params, invocation
    ) -> None:
        if method == "GetLayout":
            layout = self._build_menu_layout()
            invocation.return_value(GLib.Variant("(u(ia{sv}av))", (self._menu_revision, layout)))
        elif method == "Event":
            item_id, event_id, _data, _timestamp = params.unpack()
            if event_id == "clicked":
                self._handle_menu_click(item_id)
            invocation.return_value(None)
        elif method == "AboutToShow":
            invocation.return_value(GLib.Variant("(b)", (False,)))
        else:
            invocation.return_dbus_error("org.freedesktop.DBus.Error.UnknownMethod", "")

    def _build_menu_layout(self) -> tuple:
        """Build DBusMenu layout structure.

        Format: (id, {properties}, [children])
        """
        children = [
            GLib.Variant("v", GLib.Variant("(ia{sv}av)", (
                1,
                {"label": GLib.Variant("s", "Activer/Désactiver"), "enabled": GLib.Variant("b", True)},
                [],
            ))),
            GLib.Variant("v", GLib.Variant("(ia{sv}av)", (
                2,
                {"label": GLib.Variant("s", "Calibrer"), "enabled": GLib.Variant("b", True)},
                [],
            ))),
            GLib.Variant("v", GLib.Variant("(ia{sv}av)", (
                3,
                {"type": GLib.Variant("s", "separator")},
                [],
            ))),
            GLib.Variant("v", GLib.Variant("(ia{sv}av)", (
                4,
                {"label": GLib.Variant("s", "Quitter"), "enabled": GLib.Variant("b", True)},
                [],
            ))),
        ]
        return (0, {"children-display": GLib.Variant("s", "submenu")}, children)

    def _handle_menu_click(self, item_id: int) -> None:
        if item_id == 1:
            self._on_toggle()
        elif item_id == 2:
            self._on_calibrate()
        elif item_id == 4:
            self._on_quit()
