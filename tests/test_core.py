import json
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event
import unittest
from unittest.mock import patch

from ebon_blade.adapters import AdapterResult
from ebon_blade.models import (
    Environment,
    TargetSelection,
    ValidationError,
    VersionRepositoryConfig,
    WorkspaceData,
)
from ebon_blade.runner import execute, execute_plan
from ebon_blade.storage import WorkspaceStore, atomic_json


class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.store = WorkspaceStore.create(self.root)

    def tearDown(self):
        self.temp.cleanup()

    def test_roundtrip_and_rename_updates_selection(self):
        data = self.store.data
        data.upsert(Environment("E001", "EVB", "实验室 A", firmware="v1002"))
        data.set_target_environment("target-1", "E001")
        self.store.save(data)
        reopened = WorkspaceStore.open(self.root)
        self.assertEqual(reopened.data.resolved_targets()[0].firmware, "v1002")
        reopened.data.upsert(Environment("E002", "EVB", "已更名"), "E001")
        reopened.save(reopened.data)
        self.assertEqual(WorkspaceStore.open(self.root).data.resolved_targets()[0].id, "E002")

    def test_test_type_display_name_roundtrip_and_validation(self):
        self.store.data.rename_test_type("稳定性测试")
        self.store.save(self.store.data)
        self.assertEqual(WorkspaceStore.open(self.root).data.test_type_name, "稳定性测试")
        for invalid in ("", "x" * 41, "line\nbreak", None):
            with self.subTest(invalid=invalid), self.assertRaises(ValidationError):
                self.store.data.rename_test_type(invalid)

    def test_version_repository_roundtrip_and_validation(self):
        repository = VersionRepositoryConfig(
            "192.0.2.10", 2222, "reader", "plain-password", "/data/versions"
        )
        self.store.data.version_repository = repository
        self.store.save(self.store.data)

        reopened = WorkspaceStore.open(self.root).data.version_repository
        self.assertTrue(reopened.configured)
        self.assertEqual(reopened.host, "192.0.2.10")
        self.assertEqual(reopened.port, 2222)
        self.assertEqual(reopened.username, "reader")
        self.assertEqual(reopened.password, "plain-password")
        self.assertEqual(reopened.base_repo_dir, "/data/versions")
        self.assertNotIn("plain-password", repr(reopened))

        for fields in (
            {"host": "192.0.2.10"},
            {"host": "192.0.2.10", "port": 0, "username": "u", "password": "p", "base_repo_dir": "/repo"},
            {"host": "192.0.2.10", "username": "u", "password": "p", "base_repo_dir": "relative"},
        ):
            with self.subTest(fields=fields), self.assertRaises(ValidationError):
                VersionRepositoryConfig(**fields).validate()

    def test_conflicting_windows_cannot_overwrite(self):
        other = WorkspaceStore.open(self.root)
        self.store.data.name = "窗口一"
        self.store.save(self.store.data)
        other.data.name = "窗口二"
        with self.assertRaisesRegex(ValidationError, "其他窗口"):
            other.save(other.data)
        self.assertEqual(WorkspaceStore.open(self.root).data.name, "窗口一")
        self.assertFalse((self.root / ".save.lock").exists())

    def test_invalid_file_is_never_overwritten_on_open(self):
        path = self.root / "workspace.json"
        path.write_text("{broken", encoding="utf-8")
        with self.assertRaises(ValidationError):
            WorkspaceStore.open(self.root)
        self.assertEqual(path.read_text(), "{broken")

    def test_failed_replace_preserves_previous_file(self):
        path = self.root / "workspace.json"
        previous = path.read_bytes()
        with patch("ebon_blade.storage.os.replace", side_effect=OSError("disk failure")):
            with self.assertRaises(OSError):
                atomic_json(path, {"new": True})
        self.assertEqual(path.read_bytes(), previous)
        self.assertEqual(list(self.root.glob(".save-*.tmp")), [])

    def test_create_existing_refuses_overwrite(self):
        previous = self.store.path.read_bytes()
        with self.assertRaises(ValidationError):
            WorkspaceStore.create(self.root)
        self.assertEqual(self.store.path.read_bytes(), previous)

    def test_schema_and_unknown_fields_rejected(self):
        for update in [{"schema_version": 99}, {"future_secret_field": "value"},
                       {"targets": [{"id": "target-1", "kind": "EVB", "environment_id": "missing"}]},
                       {"environments": "not a list"}]:
            with self.subTest(update=update), self.assertRaises(ValidationError):
                WorkspaceData.from_dict({**WorkspaceData().to_dict(), **update})

    def test_environment_validation(self):
        for fields in [{"id": "../escape"}, {"bmc_port": 0}, {"expected_mac": "00:01"},
                       {"endpoints": {"endpoint_1": 123}}, {"parameters": []},
                       {"parameters": {"invalid": float("nan")}}]:
            with self.subTest(fields=fields), self.assertRaises(ValidationError):
                Environment.from_dict({"id": "E001", "kind": "EVB", "name": "Demo", **fields})

    def test_two_workspaces_are_isolated(self):
        other = WorkspaceStore.create(self.root / "other")
        self.store.data.upsert(Environment("E001", "EVB", "Private"))
        self.store.save(self.store.data)
        self.assertEqual(WorkspaceStore.open(other.root).data.environments, [])

    def test_duplicate_ids_case_insensitive(self):
        data = WorkspaceData()
        data.upsert(Environment("E001", "EVB", "A"))
        with self.assertRaises(ValidationError):
            data.upsert(Environment("e001", "DV", "B"))

    def test_multiple_targets_support_same_kind_and_mixed_kinds(self):
        data = WorkspaceData()
        data.environments = [
            Environment("E001", "EVB", "EVB A"),
            Environment("E002", "EVB", "EVB B"),
            Environment("S001", "SERVER", "Server"),
        ]
        data.targets = [
            TargetSelection("target-1", "EVB", "E001"),
            TargetSelection("target-2", "EVB", "E002"),
            TargetSelection("target-3", "SERVER", "S001"),
        ]
        data.validate()
        self.assertEqual([e.id for e in data.resolved_targets()], ["E001", "E002", "S001"])

    def test_duplicate_physical_environment_rejected(self):
        data = WorkspaceData(environments=[Environment("E001", "EVB", "EVB A")], targets=[
            TargetSelection("target-1", "EVB", "E001"),
            TargetSelection("target-2", "EVB", "E001"),
        ])
        with self.assertRaisesRegex(ValidationError, "重复使用"):
            data.validate()

    def test_v1_workspace_migrates_to_target_list(self):
        old = {
            "schema_version": 1,
            "name": "旧工作空间",
            "environments": [
                {"id": "E001", "kind": "EVB", "name": "EVB"},
                {"id": "S001", "kind": "SERVER", "name": "Server"},
            ],
            "selections": {"EVB": "E001", "SERVER": "S001"},
            "active_kind": "EVB",
            "settings": {},
        }
        migrated = WorkspaceData.from_dict(old)
        self.assertEqual(migrated.schema_version, 3)
        self.assertEqual([env.id for env in migrated.resolved_targets()], ["E001", "S001"])
        self.assertFalse(migrated.version_repository.configured)

    def test_v2_workspace_adds_empty_version_repository(self):
        old = WorkspaceData().to_dict()
        old["schema_version"] = 2
        old.pop("version_repository")

        migrated = WorkspaceData.from_dict(old)

        self.assertEqual(migrated.schema_version, 3)
        self.assertFalse(migrated.version_repository.configured)


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.env = Environment("E001", "EVB", "Demo")
        self.events = []

    def tearDown(self):
        self.temp.cleanup()

    def run_job(self, demo=False, adapters=None, cancel=None):
        return execute(self.root, self.env, {}, demo, cancel or Event(),
                       lambda p, m: self.events.append((p, m)), adapters=adapters, demo_delay=0)

    def test_demo_is_never_ready_and_never_calls_device(self):
        class NeverCall:
            def initialize(self, *args):
                raise AssertionError("device called by demo")
        result = self.run_job(True, {"EVB": NeverCall()})
        self.assertEqual(result["status"], "demo_completed")
        self.assertFalse(result["ready"])
        saved = json.loads((Path(result["directory"]) / "result.json").read_text(encoding="utf-8"))
        self.assertEqual(saved["status"], "demo_completed")
        self.assertFalse((self.root / ".run.lock").exists())

    def test_missing_adapter_is_blocked(self):
        result = self.run_job()
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["action_state"], "not_started")
        self.assertFalse(result["ready"])

    def test_cancelled_demo(self):
        cancel = Event()
        cancel.set()
        self.assertEqual(self.run_job(True, cancel=cancel)["status"], "cancelled")

    def test_adapter_exception_keeps_lock_and_unknown_state(self):
        class Broken:
            def initialize(self, *args):
                raise RuntimeError("token=never-log-this")
        result = self.run_job(adapters={"EVB": Broken()})
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["action_state"], "unknown")
        self.assertTrue((self.root / ".run.lock").exists())
        self.assertNotIn("never-log-this", (Path(result["directory"]) / "execution.log").read_text(encoding="utf-8"))
        with self.assertRaises(ValidationError):
            self.run_job(True)

    def test_internal_adapter_can_report_checked_readiness(self):
        class Good:
            def initialize(self, environment, settings, emit, cancel):
                emit(100, "Final readiness verified")
                return AdapterResult(True, "ready")
        result = self.run_job(adapters={"EVB": Good()})
        self.assertTrue(result["ready"])
        self.assertEqual(result["status"], "succeeded")

    def test_unknown_action_cannot_be_ready(self):
        class Wrong:
            def initialize(self, *args):
                return AdapterResult(True, "bad", "unknown")
        result = self.run_job(adapters={"EVB": Wrong()})
        self.assertFalse(result["ready"])
        self.assertEqual(result["status"], "failed")

    def test_snapshot_redacts_nested_credentials(self):
        self.env.parameters = {"password": "abc", "nested": [{"api_token": "xyz"}], "timeout": 30}
        result = self.run_job(True)
        snapshot = json.loads((Path(result["directory"]) / "snapshot.json").read_text(encoding="utf-8"))
        params = snapshot["environments"][0]["parameters"]
        self.assertEqual(params["password"], "<redacted>")
        self.assertEqual(params["nested"][0]["api_token"], "<redacted>")
        self.assertEqual(params["timeout"], 30)

    def test_plan_preflights_all_adapters_before_any_device_action(self):
        calls = []
        class Adapter:
            def initialize(self, environment, settings, emit, cancel):
                calls.append(environment.id)
                return AdapterResult(True, "ready")
        environments = [self.env, Environment("D001", "DV", "Private")]
        result = execute_plan(self.root, environments, {}, False, Event(),
                              lambda p, m: None, adapters={"EVB": Adapter()}, demo_delay=0)
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(calls, [])

    def test_plan_initializes_multiple_targets_in_order(self):
        calls = []
        class Adapter:
            def initialize(self, environment, settings, emit, cancel):
                calls.append(environment.id)
                return AdapterResult(True, "ready")
        environments = [self.env, Environment("E002", "EVB", "Demo 2")]
        result = execute_plan(self.root, environments, {}, False, Event(),
                              lambda p, m: None, adapters={"EVB": Adapter()}, demo_delay=0)
        self.assertEqual(calls, ["E001", "E002"])
        self.assertTrue(result["ready"])
        self.assertEqual(len(result["targets"]), 2)


if __name__ == "__main__":
    unittest.main()
