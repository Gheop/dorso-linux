# dorso-linux

Posture monitoring for Linux. Uses your webcam to detect slouching and overlays a progressive red glow on your screen as a reminder to sit straight.

<p align="center">
  <img src="https://raw.githubusercontent.com/Gheop/dorso-linux/main/assets/screenshot-calibration.png" width="260" alt="Calibration">
  <img src="https://raw.githubusercontent.com/Gheop/dorso-linux/main/assets/screenshot-settings.png" width="260" alt="Settings">
  <img src="https://raw.githubusercontent.com/Gheop/dorso-linux/main/assets/screenshot-analytics.png" width="260" alt="Analytics">
</p>

## Installation

```bash
pip install dorso-linux
```

### System dependencies

GTK4 and PyGObject are required:

```bash
# Fedora / RHEL
sudo dnf install gtk4-devel python3-gobject

# Ubuntu / Debian
sudo apt install libgtk-4-dev python3-gi gir1.2-gtk-4.0
```

## Usage

```bash
dorso
```

On first launch, sit in your best posture and click **Calibrate**. Monitoring starts automatically.

When you slouch, a red glow appears on your screen edges. Sit straight and it fades away.

## Features

- **Real-time posture detection** via webcam (MediaPipe PoseLandmarker)
- **Progressive screen overlay** — glow, border, or solid color, with adjustable intensity
- **Click-through** — keyboard and mouse work normally through the overlay
- **System tray** with posture status and quick controls
- **Analytics dashboard** — daily score, 7-day chart, slouch stats
- **Auto-pause** on screen lock
- **Dark/light theme** support
- Works on **GNOME Wayland**, **X11**, **Sway**, and **Hyprland**

## Configuration

Settings UI is accessible from the tray icon. Config stored in `~/.config/dorso/config.toml`:

```toml
warning_mode = "glow"         # glow, border, solid, none
detection_mode = "responsive" # responsive (~10fps), balanced (~4fps), performance (~2fps)
intensity = 1.0               # 0.5 = gentle, 2.0 = harsh
slouch_sensitivity = 0.03     # lower = more sensitive
warning_onset_delay = 0.0     # seconds before warning appears
camera_id = 0                 # camera device index
```

## How it works

1. OpenCV captures webcam frames at adaptive rates
2. MediaPipe PoseLandmarker extracts nose position and face width
3. Slouch detection compares nose Y to your calibrated baseline (5-frame smoothing)
4. A pure-function posture engine applies hysteresis to avoid flicker
5. The overlay renders via GNOME Shell extension, Layer Shell, or transparent GTK4 window

## Requirements

- Python 3.11+
- Linux with GTK4
- Webcam

## Links

- [Source code](https://github.com/Gheop/dorso-linux)
- [Issue tracker](https://github.com/Gheop/dorso-linux/issues)
- [GNOME Shell extension](https://github.com/Gheop/dorso-linux/tree/main/gnome-extension) (recommended for multi-monitor GNOME)

## License

MIT
