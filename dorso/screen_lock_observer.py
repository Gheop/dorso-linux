"""Observe screen lock/unlock via D-Bus (logind + screensaver interfaces)."""

from __future__ import annotations

import logging
import os
from typing import Callable

logger = logging.getLogger(__name__)


class ScreenLockObserver:
    """Listens for screen lock/unlock events via D-Bus."""

    def __init__(self, on_lock_changed: Callable[[bool], None]) -> None:
        self._on_lock_changed = on_lock_changed
        self._bus = None

    def start(self) -> None:
        try:
            import dbus
            from dbus.mainloop.glib import DBusGMainLoop

            DBusGMainLoop(set_as_default=True)
            self._bus = dbus.SessionBus()

            # GNOME screensaver
            self._bus.add_signal_receiver(
                self._on_screensaver_changed,
                signal_name="ActiveChanged",
                dbus_interface="org.gnome.ScreenSaver",
            )

            # freedesktop screensaver (KDE, XFCE, etc.)
            self._bus.add_signal_receiver(
                self._on_screensaver_changed,
                signal_name="ActiveChanged",
                dbus_interface="org.freedesktop.ScreenSaver",
            )

            # logind Lock/Unlock (most universal)
            system_bus = dbus.SystemBus()
            session_path = self._get_session_path(system_bus)
            if session_path:
                system_bus.add_signal_receiver(
                    lambda: self._on_lock_changed(True),
                    signal_name="Lock",
                    dbus_interface="org.freedesktop.login1.Session",
                    path=session_path,
                )
                system_bus.add_signal_receiver(
                    lambda: self._on_lock_changed(False),
                    signal_name="Unlock",
                    dbus_interface="org.freedesktop.login1.Session",
                    path=session_path,
                )

            logger.info("Screen lock observer started")

        except ImportError:
            logger.warning("dbus-python not available, screen lock detection disabled")
        except Exception as e:
            logger.warning("Failed to start screen lock observer: %s", e)

    def _on_screensaver_changed(self, active: bool) -> None:
        self._on_lock_changed(bool(active))

    @staticmethod
    def _get_session_path(system_bus) -> str | None:
        """Get the logind session object path for the current session."""
        try:
            import dbus

            manager = system_bus.get_object(
                "org.freedesktop.login1", "/org/freedesktop/login1"
            )
            iface = dbus.Interface(manager, "org.freedesktop.login1.Manager")

            xdg_session = os.environ.get("XDG_SESSION_ID")
            if xdg_session:
                return str(iface.GetSession(xdg_session))

            # Fallback: get session for current PID
            sessions = iface.ListSessions()
            uid = os.getuid()
            for session_id, user_id, user_name, seat_id, path in sessions:
                if int(user_id) == uid:
                    return str(path)
        except Exception as e:
            logger.debug("Could not get logind session path: %s", e)
        return None
