# dorso-linux

Posture monitoring tool for Linux, inspired by [dorso](https://github.com/tldev/dorso) for macOS.

Uses your webcam to detect slouching in real-time and overlays a progressive red glow on your screen as a gentle reminder to sit straight.

## Features

- Real-time posture detection via webcam (MediaPipe PoseLandmarker)
- Transparent red glow overlay that intensifies with slouch severity
- Click-through overlay — keyboard and mouse work normally
- System tray icon with status indication (good/bad/away/paused)
- Auto-pause on screen lock
- Calibration flow on first launch
- TOML configuration in `~/.config/dorso/`
- Works on GNOME Wayland, X11, and Wayland compositors with Layer Shell (Sway, Hyprland)

## Requirements

- Python 3.11+
- Webcam
- GTK4 (`libgtk-4-dev` / `gtk4-devel`)
- PyGObject (`python3-gi`)
- Optional: `gtk4-layer-shell` for Sway/Hyprland overlay support

### Fedora / RHEL

```bash
sudo dnf install gtk4-devel python3-gobject gtk4-layer-shell-devel
```

### Ubuntu / Debian

```bash
sudo apt install libgtk-4-dev python3-gi gir1.2-gtk-4.0
```

## Installation

```bash
pip install -e .
```

## Usage

```bash
python -m dorso
```

On first launch, a calibration window will appear. Sit in your best posture and click **Calibrer**. After calibration, monitoring starts automatically.

When you slouch, a red glow appears on the edges of your screen. Sit straight and it fades away.

### System tray

The tray icon changes color based on your posture state:
- Green: good posture
- Red: slouching
- Grey: away (no face detected)
- Orange: paused
- Blue: calibrating

Right-click for options: toggle monitoring, recalibrate, quit.

## Configuration

Settings are stored in `~/.config/dorso/config.toml`:

```toml
warning_mode = "glow"        # glow, border, solid
detection_mode = "responsive" # responsive (~10fps), balanced (~4fps), performance (~2fps)
intensity = 1.0              # Warning intensity (0.5 = gentle, 2.0 = harsh)
slouch_sensitivity = 0.03    # Lower = more sensitive
warning_onset_delay = 0.0    # Seconds before warning appears
camera_id = 0                # Camera device index

[calibration]
nose_y = 0.45
face_width = 0.12
timestamp = 1234567890.0
```

## How it works

1. **Camera capture**: OpenCV grabs frames from your webcam at adaptive rates
2. **Pose detection**: MediaPipe PoseLandmarker extracts nose position and face width
3. **Slouch detection**: Compares current nose Y position to calibrated baseline with smoothing over 5 frames
4. **Posture engine**: Pure logic state machine with hysteresis (8 bad frames to trigger, 5 good frames to clear)
5. **Overlay**: Transparent GTK4 window with Cairo-drawn red glow, click-through via empty input region

## Architecture

```
Camera (OpenCV) → Detector (MediaPipe) → PostureEngine (pure logic) → Overlay (GTK4)
                                                                     → Tray icon (D-Bus SNI)
```

The posture engine is a pure function with no side effects — it takes state + reading and returns new state + effects. This makes it fully testable.

## Tests

```bash
pip install -e ".[dev]"
pytest
```

## AirPods

The macOS version supports AirPods motion sensors for posture detection. On Linux, AirPods connect as standard Bluetooth audio devices (A2DP/HFP) via BlueZ, but motion sensor data uses Apple's proprietary protocol and is not accessible. Camera-based detection is the primary method.

## License

MIT
