"""Offscreen integration tests exercise real Qt widgets and worker event delivery."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path
from tempfile import TemporaryDirectory
import time
import unittest

from PySide6.QtWidgets import QApplication
from frostmourne.models import Environment
from frostmourne.storage import WorkspaceStore
from frostmourne.ui import EnvironmentDialog, MainWindow

APP = QApplication.instance() or QApplication([])


class GuiTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.window = MainWindow(self.root / "state")
        self.window.show()
        APP.processEvents()

    def tearDown(self):
        if self.window.worker:
            self.window.worker.cancel.set()
            self.wait_for_run()
        self.window.close()
        self.window.deleteLater()
        APP.processEvents()
        self.temp.cleanup()

    def wait_for_run(self):
        deadline = time.monotonic() + 8
        while self.window.busy and time.monotonic() < deadline:
            APP.processEvents()
            time.sleep(0.01)
        self.assertFalse(self.window.busy, "worker did not finish")

    def prepare(self):
        self.assertTrue(self.window.open_workspace(self.root / "lab", create=True))
        self.assertTrue(self.window.commit(lambda d: d.upsert(Environment("E001", "EVB", "Sample"))))

    def test_empty_then_create_and_restore(self):
        self.assertFalse(self.window.init_button.isEnabled())
        self.assertFalse(self.window.test_button.isEnabled())
        self.prepare()
        self.assertTrue(self.window.init_button.isEnabled())
        restored = MainWindow(self.root / "state")
        self.assertEqual(restored.store.data.selected().id, "E001")
        self.assertFalse(restored.ready)
        restored.close()

    def test_dialog_validates_json_and_saves(self):
        dialog = EnvironmentDialog("DV", parent=self.window)
        dialog.fields["id"].setText("D001")
        dialog.fields["name"].setText("特殊环境")
        dialog.parameters.setPlainText("[]")
        dialog.accept()
        self.assertIsNone(dialog.value)
        self.assertIn("JSON 对象", dialog.error.text())
        dialog.parameters.setPlainText('{"profile": "internal"}')
        dialog.accept()
        self.assertEqual(dialog.value.kind, "DV")
        self.assertEqual(dialog.value.parameters["profile"], "internal")

    def test_demo_worker_keeps_ui_locked_and_never_ready(self):
        self.prepare()
        self.window.demo_box.setChecked(True)
        self.window.start_run()
        self.assertFalse(self.window.open_button.isEnabled())
        self.assertFalse(self.window.init_button.isEnabled())
        self.assertFalse(self.window.open_workspace(self.root / "other", create=True))
        self.wait_for_run()
        self.assertEqual(self.window.last_result["status"], "demo_completed")
        self.assertFalse(self.window.ready)
        self.assertTrue(self.window.init_button.isEnabled())
        self.assertFalse(self.window.test_button.isEnabled())

    def test_real_run_stops_at_missing_adapter(self):
        self.prepare()
        self.window.start_run()
        self.wait_for_run()
        self.assertEqual(self.window.last_result["status"], "blocked")
        self.assertIn("尚未接入", self.window.status.text())

    def test_workspace_switch_clears_environment_and_logs(self):
        self.prepare()
        self.window.log.appendPlainText("old workspace log")
        self.assertTrue(self.window.open_workspace(self.root / "other", create=True))
        self.assertIsNone(self.window.store.data.selected())
        self.assertEqual(self.window.log.toPlainText(), "")
        self.assertFalse(self.window.init_button.isEnabled())

    def test_external_edit_prevents_dispatch(self):
        self.prepare()
        other = WorkspaceStore.open(self.window.store.root)
        other.data.name = "changed elsewhere"
        other.save(other.data)
        self.window.start_run()
        self.assertFalse(self.window.busy)
        self.assertIn("其他窗口", self.window.status.text())


if __name__ == "__main__":
    unittest.main()
