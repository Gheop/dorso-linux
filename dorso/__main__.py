"""Entry point: python -m dorso"""

import os

# Suppress noisy native warnings from MediaPipe/TFLite/absl/Mesa.
# Must be set before any import that loads the native libraries.
os.environ["TF_CPP_MIN_LOG_LEVEL"] = os.environ.get("TF_CPP_MIN_LOG_LEVEL", "2")
os.environ["GLOG_minloglevel"] = os.environ.get("GLOG_minloglevel", "2")
os.environ["MESA_LOG_LEVEL"] = os.environ.get("MESA_LOG_LEVEL", "error")

import logging
import sys


def _suppress_native_stderr() -> None:
    """Redirect native C stderr (fd 2) to /dev/null.

    MediaPipe/TFLite/absl emit warnings via C++ logging directly to fd 2,
    bypassing Python's logging. We redirect the native fd so only Python
    logging (which uses its own buffered stream) remains visible.
    """
    try:
        devnull = os.open(os.devnull, os.O_WRONLY)
        os.dup2(devnull, 2)
        os.close(devnull)
    except OSError:
        pass


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    logging.getLogger("mediapipe").setLevel(logging.ERROR)
    logging.getLogger("absl").setLevel(logging.ERROR)

    _suppress_native_stderr()

    from dorso.app import DorsoApp

    app = DorsoApp()
    # Pass minimal argv to GTK (it needs at least argv[0])
    app.run(sys.argv[:1])


if __name__ == "__main__":
    main()
