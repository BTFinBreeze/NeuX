import argparse
import sys
from pathlib import Path

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from app.bootstrap.startup import bootstrap_app
from app.ui.main_window import MainWindow

# from app.database.tool import connect_to_database

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="NeuX desktop app")
    parser.add_argument(
        "--workspace",
        type=str,
        default="./workspace_template",
        help="Path to workspace root",
    )
    return parser.parse_args()


def _set_windows_app_user_model_id() -> None:
    """Set the Windows AppUserModelID so the taskbar shows our icon instead of python.exe."""
    if sys.platform != "win32":
        return
    try:
        import ctypes

        set_app_id = ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID
        set_app_id.argtypes = [ctypes.c_wchar_p]
        set_app_id.restype = ctypes.c_ulong
        set_app_id("NeuX.NeuX.1")
    except Exception:
        pass


def main() -> int:
    args = parse_args()

    app_config, app_context = bootstrap_app(args.workspace)

    _set_windows_app_user_model_id()

    app = QApplication(sys.argv)
    app.setApplicationName(app_config.app_name)
    app.setOrganizationName(app_config.organization_name)

    icon_path = Path(__file__).resolve().parent / "app" / "ui" / "assets" / "NeuX_logo.png"
    if icon_path.exists():
        icon = QIcon(str(icon_path))
        app.setWindowIcon(icon)

    window = MainWindow(app_context)
    if icon_path.exists():
        window.setWindowIcon(QIcon(str(icon_path)))
    window.show()

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
