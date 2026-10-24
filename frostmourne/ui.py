"""Qt desktop shell. All device work stays behind the adapter boundary."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict
import json
from pathlib import Path
from threading import Event

from PySide6.QtCore import QThread, QUrl, Signal, Qt
from PySide6.QtGui import QCloseEvent, QDesktopServices
from PySide6.QtWidgets import (
    QButtonGroup, QCheckBox, QComboBox, QDialog, QDialogButtonBox,
    QFileDialog, QFormLayout, QFrame, QHBoxLayout, QLabel, QLineEdit,
    QMainWindow, QMessageBox, QPlainTextEdit, QProgressBar, QPushButton,
    QRadioButton, QScrollArea, QSpinBox, QTabWidget, QVBoxLayout, QWidget,
)

from . import __version__
from .models import Environment, KINDS, ValidationError
from .runner import execute
from .storage import WorkspaceStore, atomic_json, read_json


STYLE = """
QWidget { font-family: 'Microsoft YaHei UI', 'Segoe UI', sans-serif; font-size: 13px; color: #233747; }
QMainWindow, QWidget#page { background: #f3f6f8; }
QFrame#sidebar { background: #152b37; }
QLabel#brand { color: #ffffff; font-size: 17px; font-weight: 700; }
QLabel#sideMuted { color: #94aab7; font-size: 12px; }
QLabel#sideTitle { color: #7d98a7; font-size: 11px; }
QLabel#sideActive { color: #ccf8ef; background: #24454f; border-radius: 7px; padding: 13px; font-weight: 600; }
QLabel#sideFuture { color: #718b99; padding: 13px; }
QLabel#title { font-size: 25px; font-weight: 700; color: #173240; }
QLabel#subtitle, QLabel#muted { color: #71818c; font-size: 12px; }
QLabel#section { font-size: 15px; font-weight: 700; }
QLabel#badge { color: #16806d; background: #e5f5ef; border-radius: 5px; padding: 5px 10px; font-size: 11px; }
QLabel#status { font-weight: 600; color: #316b75; }
QFrame#card { background: #ffffff; border: 1px solid #dde5e9; border-radius: 10px; }
QLineEdit, QComboBox, QSpinBox, QPlainTextEdit { background: #ffffff; border: 1px solid #d5dfe4; border-radius: 5px; padding: 7px; selection-background-color: #d5eee8; }
QLineEdit:focus, QComboBox:focus, QPlainTextEdit:focus { border-color: #22a28a; }
QLineEdit:read-only { background: #f7f9fa; color: #637986; }
QComboBox { min-height: 22px; }
QComboBox::drop-down { width: 24px; border: none; }
QPushButton { background: #ffffff; border: 1px solid #d2dfe5; border-radius: 6px; padding: 8px 15px; font-weight: 500; }
QPushButton:hover { background: #edf5f3; border-color: #85b9ad; }
QPushButton:pressed { background: #dceee8; }
QPushButton#primary { background: #148776; border-color: #148776; color: white; font-weight: 600; padding: 11px 22px; }
QPushButton#primary:hover { background: #107665; }
QPushButton#primary:disabled { background: #d8e5e1; border-color: #d8e5e1; color: #7e9690; }
QPushButton:disabled { color: #9aabb4; background: #f1f4f6; border-color: #e0e7eb; }
QProgressBar { border: none; border-radius: 3px; background: #e9eff1; height: 6px; max-height: 6px; }
QProgressBar::chunk { background: #22a28a; border-radius: 3px; }
QPlainTextEdit#log { background: #182f3b; color: #c4dce2; border: none; font-family: 'Cascadia Mono', 'Consolas', 'Microsoft YaHei UI'; font-size: 12px; }
QScrollArea { border: none; background: transparent; }
QRadioButton { spacing: 8px; font-weight: 600; }
QRadioButton::indicator { width: 14px; height: 14px; }
QTabWidget::pane { border: 1px solid #dbe3e8; background: white; }
QTabBar::tab { padding: 9px 15px; background: #edf2f4; }
QTabBar::tab:selected { background: #ffffff; color: #148776; }
"""


def label(text: str, name: str = "", wrap: bool = False) -> QLabel:
    widget = QLabel(text)
    if name:
        widget.setObjectName(name)
    widget.setWordWrap(wrap)
    return widget


def button(text, callback, name="") -> QPushButton:
    widget = QPushButton(text)
    widget.clicked.connect(callback)
    if name:
        widget.setObjectName(name)
    return widget


def card(title: str, description: str = "") -> tuple[QFrame, QVBoxLayout]:
    frame = QFrame()
    frame.setObjectName("card")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(20, 16, 20, 16)
    layout.setSpacing(12)
    layout.addWidget(label(title, "section"))
    if description:
        layout.addWidget(label(description, "muted", True))
    return frame, layout


class EnvironmentDialog(QDialog):
    def __init__(self, kind: str, environment: Environment | None = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"{KINDS[kind]} · 环境详情")
        self.resize(660, 610)
        self.kind = kind
        self.original = environment
        self.value: Environment | None = None
        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 20, 20, 20)
        outer.addWidget(label("环境配置", "title"))
        outer.addWidget(label("保存在当前工作空间。仅填写凭据引用，不填写密码或密钥。", "muted", True))
        tabs = QTabWidget()
        outer.addWidget(tabs, 1)
        self.fields: dict[str, QLineEdit | QSpinBox] = {}
        general = QWidget()
        form = QFormLayout(general)
        form.setContentsMargins(18, 18, 18, 18)
        form.setSpacing(12)
        for key, title, placeholder in [
            ("id", "环境编号 *", "例如 E001 / D001 / S001"),
            ("name", "显示名称 *", "例如 实验室 A · EVB"),
            ("firmware", "版本标识", "例如 v1002 或个人编译版本"),
            ("credential_ref", "凭据引用", "内部凭据名称，非密码"),
        ]:
            entry = QLineEdit()
            entry.setObjectName(f"field_{key}")
            entry.setPlaceholderText(placeholder)
            form.addRow(title, entry)
            self.fields[key] = entry
        if kind == "SERVER":
            self.fields["firmware"].setPlaceholderText("软件组合版本（不包含服务器固件更新）")
        self.notes = QPlainTextEdit()
        self.notes.setMaximumHeight(120)
        self.notes.setPlaceholderText("环境说明，可留空")
        form.addRow("备注", self.notes)
        tabs.addTab(general, "基本信息")

        if kind != "DV":
            connections = QWidget()
            links = QFormLayout(connections)
            links.setContentsMargins(18, 18, 18, 18)
            links.setSpacing(10)
            for key, title in [("bmc_host", "BMC 地址"), ("bmc_port", "BMC SSH 端口"),
                               ("expected_mac", "预期完整 MAC"), ("ssh_host", "目标 SSH 地址"),
                               ("ssh_port", "目标 SSH 端口")]:
                if key.endswith("port"):
                    entry = QSpinBox()
                    entry.setRange(1, 65535)
                    entry.setValue(22)
                else:
                    entry = QLineEdit()
                entry.setObjectName(f"field_{key}")
                self.fields[key] = entry
                links.addRow(title, entry)
            tabs.addTab(connections, "连接信息")

        advanced = QWidget()
        advanced_layout = QVBoxLayout(advanced)
        advanced_layout.addWidget(label("内部扩展参数 · JSON 对象", "section"))
        advanced_layout.addWidget(label(
            "DV 的配置由内部定义。EVB / 服务器可填写内部初始化参数。此处不会执行代码。", "muted", True))
        self.parameters = QPlainTextEdit("{}")
        self.parameters.setObjectName("parameters_json")
        advanced_layout.addWidget(self.parameters)
        tabs.addTab(advanced, "扩展参数")
        self.endpoints = QPlainTextEdit("{}")
        if kind == "EVB":
            ports = QWidget()
            ports_layout = QVBoxLayout(ports)
            ports_layout.addWidget(label("端点名称与地址（JSON 对象）", "section"))
            ports_layout.addWidget(label("例如 endpoint_1…endpoint_5；具体角色由内部适配定义。", "muted", True))
            self.endpoints.setPlaceholderText('{"endpoint_1": "host:port"}')
            ports_layout.addWidget(self.endpoints)
            tabs.addTab(ports, "串口端点")

        self.error = label("", "status", True)
        outer.addWidget(self.error)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("保存环境")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        outer.addWidget(buttons)
        if environment:
            for key, widget in self.fields.items():
                value = getattr(environment, key)
                if isinstance(widget, QSpinBox):
                    widget.setValue(value)
                else:
                    widget.setText(value)
            self.notes.setPlainText(environment.notes)
            self.parameters.setPlainText(json.dumps(environment.parameters, ensure_ascii=False, indent=2))
            self.endpoints.setPlainText(json.dumps(environment.endpoints, ensure_ascii=False, indent=2))

    def accept(self):
        try:
            data = asdict(self.original) if self.original else {"kind": self.kind}
            for key, widget in self.fields.items():
                data[key] = widget.value() if isinstance(widget, QSpinBox) else widget.text().strip()
            data["notes"] = self.notes.toPlainText().strip()
            data["parameters"] = json.loads(self.parameters.toPlainText())
            data["endpoints"] = json.loads(self.endpoints.toPlainText())
            # Forbid nonstandard JSON constants before writing the workspace.
            json.dumps(data, allow_nan=False)
            self.value = Environment.from_dict(data)
        except (ValueError, TypeError) as exc:
            self.error.setText(f"请检查输入：{exc}")
            return
        super().accept()


class SettingsDialog(QDialog):
    def __init__(self, settings: dict[str, str], parent=None):
        super().__init__(parent)
        self.setWindowTitle("工作空间 · 本机设置")
        self.resize(680, 340)
        self.value = None
        self.fields = {}
        layout = QVBoxLayout(self)
        layout.addWidget(label("本机路径", "title"))
        layout.addWidget(label("路径只保存为配置；当前公开骨架不会启动脚本或操作 FTP。", "muted", True))
        form = QFormLayout()
        layout.addLayout(form)
        for key, text, directory in [("firmware_root", "版本总目录", True), ("ftp_root", "FTP 服务目录", True),
                                     ("launcher_path", "启动框架入口", False), ("python_path", "Python 路径", False)]:
            row = QHBoxLayout()
            field = QLineEdit(settings.get(key, ""))
            row.addWidget(field)
            browse = button("浏览", lambda checked=False, e=field, d=directory: self.browse(e, d))
            row.addWidget(browse)
            form.addRow(text, row)
            self.fields[key] = field
        layout.addStretch()
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("保存")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def browse(self, field, directory):
        path = QFileDialog.getExistingDirectory(self, "选择目录") if directory else QFileDialog.getOpenFileName(self, "选择文件")[0]
        if path:
            field.setText(path)

    def accept(self):
        self.value = {key: field.text().strip() for key, field in self.fields.items()}
        super().accept()


class RunWorker(QThread):
    progress = Signal(int, str)
    completed = Signal(dict)

    def __init__(self, root, environment, settings, demo, parent=None):
        super().__init__(parent)
        self.root = root
        self.environment = deepcopy(environment)
        self.settings = deepcopy(settings)
        self.demo = demo
        self.cancel = Event()

    def run(self):
        try:
            result = execute(self.root, self.environment, self.settings, self.demo,
                             self.cancel, self.progress.emit)
        except Exception as exc:
            # Validation and file errors are local, before or while persisting run evidence.
            result = {"ready": False, "status": "failed", "summary": f"未完成运行记录：{exc}", "demo": self.demo}
        self.completed.emit(result)


class MainWindow(QMainWindow):
    def __init__(self, state_dir: Path, workspace: Path | None = None):
        super().__init__()
        self.state_dir = state_dir
        self.store: WorkspaceStore | None = None
        self.worker: RunWorker | None = None
        self.ready = False
        self.last_run: Path | None = None
        self.last_result: dict | None = None
        self.setWindowTitle("Frostmourne · 自动化测试平台")
        self.resize(1200, 880)
        self.setMinimumSize(960, 720)
        self.setStyleSheet(STYLE)
        self._build()
        self._refresh()
        if workspace is not None:
            self.open_workspace(workspace)
        else:
            preferences = state_dir / "preferences.json"
            if preferences.exists():
                try:
                    saved = read_json(preferences)
                    if isinstance(saved, dict) and saved.get("last_workspace"):
                        self.open_workspace(Path(saved["last_workspace"]))
                except (OSError, ValueError, TypeError) as exc:
                    self.status.setText(f"最近工作空间未恢复：{exc}")

    @property
    def busy(self) -> bool:
        return self.worker is not None

    def _build(self):
        shell = QWidget()
        self.setCentralWidget(shell)
        horizontal = QHBoxLayout(shell)
        horizontal.setContentsMargins(0, 0, 0, 0)
        horizontal.setSpacing(0)
        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(190)
        nav = QVBoxLayout(sidebar)
        nav.setContentsMargins(20, 30, 20, 22)
        nav.setSpacing(10)
        nav.addWidget(label("FROSTMOURNE", "brand"))
        nav.addWidget(label("自动化测试平台", "sideMuted"))
        nav.addSpacing(36)
        nav.addWidget(label("测试类型", "sideTitle"))
        nav.addWidget(label("环境准备", "sideActive"))
        nav.addWidget(label("更多测试类型\n后续扩展", "sideFuture"))
        nav.addStretch()
        nav.addWidget(label("LOCAL CLIENT", "sideTitle"))
        nav.addWidget(label(f"v{__version__}  /  GUI 框架", "sideMuted"))
        horizontal.addWidget(sidebar)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        horizontal.addWidget(scroll, 1)
        page = QWidget()
        page.setObjectName("page")
        scroll.setWidget(page)
        content = QVBoxLayout(page)
        content.setContentsMargins(28, 24, 28, 20)
        content.setSpacing(14)
        heading = QHBoxLayout()
        titles = QVBoxLayout()
        titles.addWidget(label("环境准备", "title"))
        titles.addWidget(label("选择工作空间，配置目标环境，在这里开始初始化。", "subtitle"))
        heading.addLayout(titles)
        heading.addStretch()
        heading.addWidget(label("GUI 框架 · 设备待接入", "badge"))
        content.addLayout(heading)

        space_card, space_layout = card("01  工作空间")
        content.addWidget(space_card)
        space_row = QHBoxLayout()
        self.workspace_path = QLineEdit()
        self.workspace_path.setReadOnly(True)
        self.workspace_path.setPlaceholderText("选择本地目录，保存环境配置与运行记录")
        space_row.addWidget(self.workspace_path, 1)
        self.open_button = button("打开", lambda: self.choose_workspace(False))
        self.new_button = button("新建", lambda: self.choose_workspace(True))
        self.settings_button = button("本机设置", self.edit_settings)
        for widget in (self.open_button, self.new_button, self.settings_button):
            space_row.addWidget(widget)
        space_layout.addLayout(space_row)
        self.workspace_hint = label("未打开工作空间 · 首次使用请点击“新建”", "muted")
        space_layout.addWidget(self.workspace_hint)

        env_card, env_layout = card("02  环境选择", "选择一项作为本次初始化目标；各类型配置独立保存，组合关系留给内部适配。")
        content.addWidget(env_card)
        self.group = QButtonGroup(self)
        self.rows = {}
        for kind, title in KINDS.items():
            row = QHBoxLayout()
            radio = QRadioButton(title)
            radio.setFixedWidth(120)
            radio.setObjectName(f"target_{kind}")
            self.group.addButton(radio)
            row.addWidget(radio)
            combo = QComboBox()
            combo.setObjectName(f"environment_{kind}")
            combo.setMinimumWidth(210)
            row.addWidget(combo, 1)
            details = button("配置详情", lambda checked=False, k=kind: self.edit_environment(k))
            add = button("＋ 新建", lambda checked=False, k=kind: self.edit_environment(k, True))
            row.addWidget(details)
            row.addWidget(add)
            env_layout.addLayout(row)
            self.rows[kind] = (radio, combo, details, add)
            radio.clicked.connect(lambda checked=False, k=kind: self.select_kind(k))
            combo.currentIndexChanged.connect(lambda index, k=kind: self.select_environment(k, index))
        self.target_hint = label("请先创建环境档案。", "muted", True)
        env_layout.addWidget(self.target_hint)

        benchmark, bench_layout = card("03  Benchmark 方案")
        content.addWidget(benchmark)
        bench_layout.addWidget(label("预留区域 · 第一版专注环境初始化，测试方案与实际执行后续接入。", "muted", True))

        actions = QHBoxLayout()
        self.init_button = button("环境初始化", self.start_run, "primary")
        self.init_button.setObjectName("primary")
        actions.addWidget(self.init_button)
        self.demo_box = QCheckBox("离线演示（不连接设备）")
        self.demo_box.setToolTip("只演示进度和日志，完成后不会标记环境已就绪。")
        actions.addWidget(self.demo_box)
        self.stop_button = button("请求停止", self.stop_run)
        actions.addWidget(self.stop_button)
        actions.addStretch()
        self.test_button = QPushButton("执行测试 · 暂未接入")
        self.test_button.setEnabled(False)
        self.test_button.setToolTip("后续接入；环境未就绪时会提示先初始化，不自动执行。")
        actions.addWidget(self.test_button)
        content.addLayout(actions)

        logs, log_layout = card("运行状态")
        content.addWidget(logs, 1)
        status_row = QHBoxLayout()
        self.status = label("等待打开工作空间", "status", True)
        status_row.addWidget(self.status, 1)
        self.log_button = button("打开日志目录", self.open_logs)
        status_row.addWidget(self.log_button)
        log_layout.addLayout(status_row)
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.setValue(0)
        log_layout.addWidget(self.progress)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setObjectName("log")
        self.log.setMinimumHeight(115)
        self.log.setMaximumHeight(220)
        self.log.setMaximumBlockCount(2000)
        self.log.setPlaceholderText("初始化过程与检查信息将显示在这里。")
        log_layout.addWidget(self.log)
        content.addWidget(label("配置在本地保存  ·  真实初始化需要内部适配器  ·  演示结果不代表设备就绪", "muted"))

    def _refresh(self):
        data = self.store.data if self.store else None
        for kind, (radio, combo, details, add) in self.rows.items():
            combo.blockSignals(True)
            combo.clear()
            combo.addItem("请选择环境…", None)
            if data:
                for env in data.environments:
                    if env.kind == kind:
                        combo.addItem(f"{env.id}  ·  {env.name}", env.id)
                combo.setCurrentIndex(max(0, combo.findData(data.selections.get(kind))))
            combo.blockSignals(False)
            radio.setChecked(kind == (data.active_kind if data else "EVB"))
            radio.setEnabled(bool(data) and not self.busy)
            combo.setEnabled(bool(data) and not self.busy)
            details.setEnabled(bool(data and data.selected(kind)) and not self.busy)
            add.setEnabled(bool(data) and not self.busy)
        self.workspace_path.setText(str(self.store.root) if self.store else "")
        if data:
            self.workspace_hint.setText(f"{data.name}  ·  {len(data.environments)} 个环境档案  ·  修改后自动保存")
        else:
            self.workspace_hint.setText("未打开工作空间 · 首次使用请点击“新建”")
        env = data.selected() if data else None
        self.target_hint.setText(
            f"本次目标：{env.id} / {KINDS[env.kind]}    版本：{env.firmware or '未设置'}    真实设备适配由内部实现"
            if env else "请选择本次初始化目标；未选择的类型不会执行。")
        self.open_button.setEnabled(not self.busy)
        self.new_button.setEnabled(not self.busy)
        self.settings_button.setEnabled(bool(data) and not self.busy)
        self.init_button.setEnabled(bool(env) and not self.busy)
        self.demo_box.setEnabled(not self.busy)
        self.stop_button.setEnabled(self.busy)
        self.log_button.setEnabled(bool(self.store))

    def choose_workspace(self, create: bool):
        if self.busy:
            return
        path = QFileDialog.getExistingDirectory(self, "新建工作空间：选择目录" if create else "打开工作空间")
        if path:
            self.open_workspace(Path(path), create)

    def open_workspace(self, path: Path, create=False) -> bool:
        if self.busy:
            return False
        try:
            store = WorkspaceStore.create(path) if create else WorkspaceStore.open(path)
        except (OSError, ValueError) as exc:
            self.status.setText(f"工作空间未打开：{exc}")
            return False
        self.store = store
        self.ready = False
        self.last_run = None
        self.last_result = None
        self.progress.setValue(0)
        self.log.clear()
        self.status.setText("配置已恢复 · 环境状态待检查")
        try:
            atomic_json(self.state_dir / "preferences.json", {"last_workspace": str(store.root)})
        except OSError:
            self.log.appendPlainText("无法记住最近工作空间；当前空间仍可使用。")
        self._refresh()
        return True

    def commit(self, change) -> bool:
        if not self.store or self.busy:
            return False
        data = deepcopy(self.store.data)
        try:
            change(data)
            self.store.save(data)
        except (OSError, ValueError, TypeError) as exc:
            self.status.setText(f"保存失败：{exc}")
            self._refresh()
            return False
        self.ready = False
        self.status.setText("配置已保存 · 环境状态待检查")
        self._refresh()
        return True

    def select_kind(self, kind: str):
        self.commit(lambda data: setattr(data, "active_kind", kind))

    def select_environment(self, kind: str, index: int):
        env_id = self.rows[kind][1].itemData(index)
        def change(data):
            if env_id:
                data.selections[kind] = env_id
            else:
                data.selections.pop(kind, None)
        self.commit(change)

    def edit_environment(self, kind: str, new=False):
        if not self.store or self.busy:
            return
        original = None if new else self.store.data.selected(kind)
        dialog = EnvironmentDialog(kind, original, self)
        if dialog.exec() == QDialog.DialogCode.Accepted and dialog.value:
            self.commit(lambda data: data.upsert(dialog.value, original.id if original else None))

    def edit_settings(self):
        if not self.store or self.busy:
            return
        dialog = SettingsDialog(self.store.data.settings, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.commit(lambda data: setattr(data, "settings", dialog.value))

    def start_run(self):
        if not self.store or self.busy:
            return
        environment = self.store.data.selected()
        if not environment:
            return
        # Recheck disk revision immediately before dispatching the captured config.
        try:
            self.store.save(deepcopy(self.store.data))
        except (OSError, ValueError) as exc:
            self.status.setText(f"初始化未启动：{exc}")
            return
        self.ready = False
        self.last_result = None
        self.last_run = None
        self.log.clear()
        self.progress.setValue(0)
        demo = self.demo_box.isChecked()
        self.status.setText("离线演示运行中 · 不会操作设备" if demo else "正在检查初始化能力…")
        self.worker = RunWorker(self.store.root, environment, self.store.data.settings, demo, self)
        self.worker.progress.connect(self.on_progress)
        self.worker.completed.connect(self.on_result)
        self.worker.finished.connect(self.on_finished)
        self._refresh()
        self.worker.start()

    def on_progress(self, progress: int, message: str):
        self.progress.setValue(max(0, min(100, progress)))
        self.log.appendPlainText(message)

    def on_result(self, result: dict):
        self.last_result = result
        self.ready = bool(result.get("ready") and not result.get("demo"))
        self.status.setText(result.get("summary", "运行结束"))
        self.last_run = Path(result["directory"]) if result.get("directory") else None
        if result.get("action_state") in {"running", "unknown"}:
            self.log.appendPlainText("设备动作未确认结束；已保留 .run.lock，请内部人员检查，勿直接重试。")

    def on_finished(self):
        worker = self.worker
        self.worker = None
        if worker:
            worker.deleteLater()
        self._refresh()

    def stop_run(self):
        if self.worker:
            self.worker.cancel.set()
            self.status.setText("已请求停止 · 等待当前步骤按适配器规则安全结束")
            self.stop_button.setEnabled(False)

    def open_logs(self):
        if self.store:
            path = self.last_run or self.store.root / "runs"
            try:
                path.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                self.status.setText(f"日志目录不可用：{exc}")
                return
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def closeEvent(self, event: QCloseEvent):
        if self.busy:
            self.status.setText("初始化尚未结束，请先请求停止并等待结果；窗口保持打开。")
            event.ignore()
            return
        event.accept()
