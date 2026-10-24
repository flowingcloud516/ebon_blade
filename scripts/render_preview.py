"""Render our own Qt widget to an image, using temporary fictional workspace data."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QFontDatabase
from frostmourne.models import Environment
from frostmourne.storage import WorkspaceStore
from frostmourne.ui import MainWindow

app = QApplication([])
app.setStyle("Fusion")
# Qt's offscreen plugin does not enumerate Windows system fonts.
for font in (Path("C:/Windows/Fonts/msyh.ttc"), Path("C:/Windows/Fonts/segoeui.ttf")):
    if font.is_file():
        QFontDatabase.addApplicationFont(str(font))
with TemporaryDirectory() as temporary:
    root = Path(temporary)
    store = WorkspaceStore.create(root / "示例工作空间")
    for env in [Environment("E001", "EVB", "EVB 示例环境", firmware="v1002"),
                Environment("D001", "DV", "DV 内部环境"),
                Environment("S001", "SERVER", "服务器示例环境")]:
        store.data.upsert(env)
    store.data.active_kind = "EVB"
    store.save(store.data)
    window = MainWindow(root / "state", store.root)
    # Fictional display path only; no developer/user path in the public screenshot.
    window.workspace_path.setText("D:/LabWorkspaces/我的测试工作空间")
    window.status.setText("配置已保存 · 环境状态待检查")
    window.log.setPlainText("工作空间已打开，已恢复 3 个环境档案。\n真实初始化尚未接入；可选择离线演示查看进度和日志。")
    window.show()
    app.processEvents()
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("assets/client-preview.png")
    target.parent.mkdir(parents=True, exist_ok=True)
    if not window.grab().save(str(target)):
        raise SystemExit("Could not save preview")
    window.close()
    print(target)
