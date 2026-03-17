"""Application orchestrator — wires all components together."""

from __future__ import annotations

import logging
import signal

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gio, GLib, Gtk

from dorso.analytics import Analytics
from dorso.analytics_window import AnalyticsWindow
from dorso.calibration import CalibrationDialog
from dorso.camera_detector import CameraDetector
from dorso.models import AppState, CalibrationData, PostureReading
from dorso.onboarding import OnboardingWindow
from dorso.overlay import OverlayManager
from dorso.posture_engine import Effect, MonitoringState, process_reading, process_screen_lock
from dorso.screen_lock_observer import ScreenLockObserver
from dorso.settings import Settings, is_first_launch
from dorso.settings_window import SettingsWindow
from dorso.tray import TrayIcon

logger = logging.getLogger(__name__)


class DorsoApp(Gtk.Application):
    """Main application class."""

    def __init__(self) -> None:
        super().__init__(application_id="io.github.dorso")
        self._first_launch = is_first_launch()
        self._settings = Settings.load()
        self._analytics = Analytics()
        self._state = AppState.DISABLED
        self._engine_state = MonitoringState()
        self._detector: CameraDetector | None = None
        self._overlay: OverlayManager | None = None
        self._tray: TrayIcon | None = None
        self._lock_observer: ScreenLockObserver | None = None
        self._screen_locked = False
        self._settings_window: SettingsWindow | None = None
        self._analytics_window: AnalyticsWindow | None = None
        self._was_slouching = False

    def do_activate(self) -> None:
        self.hold()

        # Overlay
        self._overlay = OverlayManager()
        self._overlay.setup()
        self._overlay.set_warning_mode(self._settings.warning_mode)
        self._overlay.set_color(self._settings.warning_color)

        # Camera detector
        self._detector = CameraDetector(
            camera_id=self._settings.camera_id,
            sensitivity=self._settings.slouch_sensitivity,
        )
        self._detector.on_reading = self._on_posture_reading

        # Tray
        self._tray = TrayIcon(
            on_toggle=self._on_toggle,
            on_calibrate=self._on_calibrate,
            on_settings=self._on_settings,
            on_analytics=self._on_analytics,
            on_quit=self._on_quit,
        )
        self._tray.start()

        # Screen lock observer
        self._lock_observer = ScreenLockObserver(self._on_lock_changed)
        self._lock_observer.start()

        # Periodic analytics tick (every 60s)
        GLib.timeout_add_seconds(60, self._analytics_tick)

        # D-Bus toggle service
        self._register_dbus_toggle()

        # SIGINT
        GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGINT, self._on_quit)

        # Start
        if not self._detector.is_available():
            logger.error("No camera available (camera_id=%s)", self._settings.camera_id)
            self._update_state(AppState.PAUSED)
            return

        if self._first_launch:
            self._start_onboarding()
        elif self._settings.calibration and self._settings.calibration.is_valid:
            self._detector.calibration = self._settings.calibration
            self._start_monitoring()
        else:
            self._start_calibration()

    # -- D-Bus toggle --

    _DBUS_IFACE = """
    <node>
      <interface name="org.dorso.App">
        <method name="Toggle"/>
      </interface>
    </node>"""

    def _register_dbus_toggle(self) -> None:
        try:
            bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
            node = Gio.DBusNodeInfo.new_for_xml(self._DBUS_IFACE)
            bus.register_object(
                "/org/dorso/App",
                node.interfaces[0],
                self._on_dbus_call,
                None,
                None,
            )
            Gio.bus_own_name_on_connection(
                bus, "org.dorso.App", Gio.BusNameOwnerFlags.NONE, None, None
            )
        except Exception as e:
            logger.warning("D-Bus toggle registration failed: %s", e)

    def _on_dbus_call(self, connection, sender, path, iface, method, params, invocation):
        if method == "Toggle":
            self._on_toggle()
            invocation.return_value(None)

    # -- Onboarding --

    def _start_onboarding(self) -> None:
        self._update_state(AppState.CALIBRATING)
        if self._detector is None:
            return
        self._onboarding = OnboardingWindow(
            detector=self._detector,
            camera_id=self._settings.camera_id,
            on_complete=self._on_onboarding_complete,
        )
        self._onboarding.show()

    def _on_onboarding_complete(self, data: CalibrationData | None) -> None:
        self._on_calibration_complete(data)
        if data and data.is_valid:
            self._show_settings()

    # -- Calibration --

    def _start_calibration(self) -> None:
        if self._state == AppState.MONITORING:
            self._stop_monitoring()
        self._update_state(AppState.CALIBRATING)
        if self._detector is None:
            return
        dialog = CalibrationDialog(
            detector=self._detector,
            on_complete=self._on_calibration_complete,
        )
        dialog.show()

    def _on_calibration_complete(self, data: CalibrationData | None) -> None:
        if data is None or not data.is_valid:
            logger.warning("Calibration failed or cancelled")
            self._update_state(AppState.PAUSED)
            return
        self._settings.calibration = data
        self._settings.save()
        if self._detector:
            self._detector.calibration = data
        self._start_monitoring()

    # -- Monitoring --

    def _start_monitoring(self) -> None:
        self._engine_state = MonitoringState()
        self._was_slouching = False
        self._update_state(AppState.MONITORING)
        self._analytics.start_monitoring()
        if self._detector:
            self._detector.set_interval(self._settings.detection_mode.base_interval)
            self._detector.start()
        logger.info("Monitoring started")

    def _stop_monitoring(self) -> None:
        if self._detector:
            self._detector.stop()
        if self._overlay:
            self._overlay.clear()
        self._analytics.stop_monitoring()
        self._engine_state = MonitoringState()
        self._was_slouching = False

    # -- Posture readings --

    def _on_posture_reading(self, reading: PostureReading) -> None:
        GLib.idle_add(self._handle_reading, reading)

    def _handle_reading(self, reading: PostureReading) -> bool:
        if self._state != AppState.MONITORING or self._screen_locked:
            return False

        config = self._settings.to_posture_config()
        new_state, effects = process_reading(self._engine_state, config, reading)
        self._engine_state = new_state

        for effect in effects:
            if effect == Effect.UPDATE_OVERLAY:
                if self._overlay:
                    self._overlay.set_intensity(new_state.warning_intensity)
                if self._detector and new_state.is_slouching:
                    self._detector.set_interval(
                        self._settings.detection_mode.slouch_interval
                    )
                # Track slouch start
                if new_state.is_slouching and not self._was_slouching:
                    self._analytics.on_slouch_start()
                    self._was_slouching = True
            elif effect == Effect.CLEAR_OVERLAY:
                if self._overlay:
                    self._overlay.clear()
                if self._detector:
                    self._detector.set_interval(
                        self._settings.detection_mode.base_interval
                    )
                # Track slouch end
                if self._was_slouching:
                    self._analytics.on_slouch_end()
                    self._was_slouching = False
            elif effect == Effect.UPDATE_TRAY:
                self._update_tray_from_engine()

        return False

    # -- Analytics --

    def _analytics_tick(self) -> bool:
        if self._state == AppState.MONITORING:
            self._analytics.tick()
        return True  # keep timer alive

    # -- Screen lock --

    def _on_lock_changed(self, is_locked: bool) -> None:
        GLib.idle_add(self._handle_lock_change, is_locked)

    def _handle_lock_change(self, is_locked: bool) -> bool:
        self._screen_locked = is_locked
        new_state, effects = process_screen_lock(self._engine_state, is_locked)
        self._engine_state = new_state
        for effect in effects:
            if effect == Effect.CLEAR_OVERLAY and self._overlay:
                self._overlay.clear()
            elif effect == Effect.UPDATE_TRAY:
                self._update_tray_from_engine()
        return False

    # -- Tray callbacks --

    def _on_toggle(self) -> None:
        GLib.idle_add(self._handle_toggle)

    def _handle_toggle(self) -> bool:
        if self._state == AppState.MONITORING:
            self._stop_monitoring()
            self._update_state(AppState.DISABLED)
        elif self._state in (AppState.DISABLED, AppState.PAUSED):
            if self._settings.calibration and self._settings.calibration.is_valid:
                self._start_monitoring()
            else:
                self._start_calibration()
        return False

    def _on_calibrate(self) -> None:
        GLib.idle_add(self._start_calibration)

    def _on_settings(self) -> None:
        GLib.idle_add(self._show_settings)

    def _show_settings(self) -> bool:
        self._settings_window = SettingsWindow(
            settings=self._settings,
            on_changed=self._on_settings_changed,
            on_recalibrate=lambda: GLib.idle_add(self._start_calibration),
        )
        self._settings_window.show()
        return False

    def _on_settings_changed(self, settings: Settings) -> None:
        self._settings = settings
        if self._overlay:
            self._overlay.set_warning_mode(settings.warning_mode)
            self._overlay.set_color(settings.warning_color)
        if self._detector:
            self._detector._sensitivity = settings.slouch_sensitivity
            if self._state == AppState.MONITORING:
                self._detector.set_interval(settings.detection_mode.base_interval)
        logger.info("Settings updated: mode=%s, intensity=%.1f",
                     settings.warning_mode.value, settings.intensity)

    def _on_analytics(self) -> None:
        GLib.idle_add(self._show_analytics)

    def _show_analytics(self) -> bool:
        # Save current data before showing
        if self._state == AppState.MONITORING:
            self._analytics.tick()
        self._analytics_window = AnalyticsWindow(self._analytics)
        self._analytics_window.show()
        return False

    # -- Quit --

    def _on_quit(self, *args) -> None:
        GLib.idle_add(self._handle_quit)

    def _handle_quit(self) -> bool:
        self._stop_monitoring()
        if self._tray:
            self._tray.stop()
        if self._overlay:
            self._overlay.destroy()
        self.release()
        self.quit()
        return False

    # -- State --

    def _update_state(self, state: AppState) -> None:
        self._state = state
        if self._tray:
            tray_state = {
                AppState.DISABLED: "disabled",
                AppState.CALIBRATING: "calibrating",
                AppState.MONITORING: "good",
                AppState.PAUSED: "paused",
            }.get(state, "disabled")
            self._tray.update_state(tray_state)

    def _update_tray_from_engine(self) -> None:
        if not self._tray or self._state != AppState.MONITORING:
            return
        if self._screen_locked:
            self._tray.update_state("paused")
        elif self._engine_state.is_away:
            self._tray.update_state("away")
        elif self._engine_state.is_slouching:
            self._tray.update_state("bad")
        else:
            self._tray.update_state("good")
