from __future__ import annotations

import argparse
from pathlib import Path
import sys


def main() -> int:
    parser = argparse.ArgumentParser(description="Ebon Blade 自动化测试客户端")
    parser.add_argument("--workspace", type=Path, help="打开已有工作空间，不自动执行")
    parser.add_argument("--state-dir", type=Path, help="客户端偏好存放位置，默认使用用户应用数据目录")
    args = parser.parse_args()
    try:
        from PySide6.QtCore import QStandardPaths
        from PySide6.QtWidgets import QApplication
        from .ui import MainWindow
    except ImportError as exc:
        print(f"缺少 GUI 依赖，请运行 python -m pip install -r requirements.txt\n{exc}", file=sys.stderr)
        return 1
    app = QApplication(sys.argv[:1])
    app.setOrganizationName("EbonBlade")
    app.setApplicationName("Ebon Blade")
    app.setStyle("Fusion")
    state_dir = args.state_dir or Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppConfigLocation))
    window = MainWindow(state_dir, args.workspace)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
