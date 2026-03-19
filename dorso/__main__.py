"""Entry point: python -m dorso"""

import logging
import os
import sys


def main() -> None:
    # Suppress noisy third-party warnings (MediaPipe/TFLite/absl/Mesa)
    os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "2")
    os.environ.setdefault("GLOG_minloglevel", "2")
    os.environ.setdefault("MESA_LOG_LEVEL", "error")

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    logging.getLogger("mediapipe").setLevel(logging.ERROR)
    logging.getLogger("absl").setLevel(logging.ERROR)

    # Hint about LD_PRELOAD for Wayland Layer Shell
    if "WAYLAND_DISPLAY" in os.environ and "libgtk4-layer-shell" not in os.environ.get("LD_PRELOAD", ""):
        logger = logging.getLogger("dorso")
        logger.info(
            "Tip: For best Wayland overlay support (Sway/Hyprland), run with: "
            "LD_PRELOAD=/usr/lib64/libgtk4-layer-shell.so.1.3.0 python -m dorso"
        )

    from dorso.app import DorsoApp

    app = DorsoApp()
    # Pass minimal argv to GTK (it needs at least argv[0])
    app.run(sys.argv[:1])


if __name__ == "__main__":
    main()
