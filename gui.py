import io
import importlib.metadata
import os
import sys
from contextlib import redirect_stdout

import yaml
from PyQt5.QtCore import QObject, QThread, Qt, pyqtSignal
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

try:
    from tool_manager_gui import dependency, installer
except ImportError:
    import dependency
    import installer


class WorkerSignals(QObject):
    log = pyqtSignal(str)
    error = pyqtSignal(str)
    finished = pyqtSignal()


class BackgroundWorker(QObject):
    finished = pyqtSignal()

    def __init__(self, task, signals):
        super().__init__()
        self.task = task
        self.signals = signals

    def run(self):
        try:
            self.task()
        except Exception as exc:
            self.signals.error.emit(str(exc))
        finally:
            self.signals.finished.emit()
            self.finished.emit()


class ToolManagerGUI(QMainWindow):
    def __init__(self):
        super().__init__()

        self.worker_thread = None
        self.worker = None

        self.setWindowTitle(f"eSim Tool Manager - v{self.show_version()}")
        self.setGeometry(400, 200, 900, 550)

        self.tools_data = self.load_tools_yaml()

        self.init_ui()
        self.update_dependency_status()

    def load_tools_yaml(self):
        try:
            path = os.path.join(os.path.dirname(__file__), "tools.yml")
            with open(path, "r", encoding="utf-8") as handle:
                data = yaml.safe_load(handle) or {}

            tools = data.get("tools", {})
            if not isinstance(tools, dict):
                print("Invalid YAML format: 'tools' must be a dictionary")
                return {}

            return tools
        except Exception as exc:
            print("Error loading tools.yml:", exc)
            return {}

    def init_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        layout = QVBoxLayout()

        title_layout = QHBoxLayout()
        title = QLabel("eSim Tool Manager")
        title.setFont(QFont("Arial", 18, QFont.Bold))
        title.setAlignment(Qt.AlignCenter)
        title_layout.addStretch()
        title_layout.addWidget(title)
        title_layout.addStretch()
        layout.addLayout(title_layout)

        self.table = QTableWidget()
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(
            ["Tool", "Version", "Description", "Installed Version", "Status"]
        )
        self.table.setRowCount(len(self.tools_data))

        for row, (tool, info) in enumerate(self.tools_data.items()):
            if not isinstance(info, dict):
                description = ""
                versions = []
            else:
                description = info.get("description", "")
                versions = info.get("versions", [])

            checkbox = QCheckBox(tool)
            self.table.setCellWidget(row, 0, checkbox)

            combo = QComboBox()
            combo.addItems(["latest"] + versions)
            self.table.setCellWidget(row, 1, combo)

            desc_item = QTableWidgetItem(description)
            desc_item.setFlags(desc_item.flags() & ~Qt.ItemIsEditable)
            self.table.setItem(row, 2, desc_item)

            installed = QTableWidgetItem("-")
            installed.setFlags(installed.flags() & ~Qt.ItemIsEditable)
            self.table.setItem(row, 3, installed)

            status = QTableWidgetItem("Checking...")
            status.setFlags(status.flags() & ~Qt.ItemIsEditable)
            self.table.setItem(row, 4, status)

        layout.addWidget(self.table)

        btn_layout = QHBoxLayout()
        self.install_btn = QPushButton("Install Selected")
        self.install_btn.clicked.connect(self.install_tool)
        btn_layout.addWidget(self.install_btn)

        self.update_btn = QPushButton("Update Selected")
        self.update_btn.clicked.connect(self.update_tool)
        btn_layout.addWidget(self.update_btn)

        self.uninstall_btn = QPushButton("Uninstall Selected")
        self.uninstall_btn.clicked.connect(self.uninstall_tool)
        btn_layout.addWidget(self.uninstall_btn)
        layout.addLayout(btn_layout)

        sys_layout = QHBoxLayout()
        self.refresh_btn = QPushButton("Refresh Status")
        self.refresh_btn.clicked.connect(self.update_dependency_status)
        sys_layout.addWidget(self.refresh_btn)

        self.doctor_btn = QPushButton("Run Doctor")
        self.doctor_btn.clicked.connect(self.run_doctor)
        sys_layout.addWidget(self.doctor_btn)
        layout.addLayout(sys_layout)

        self.output = QTextEdit()
        self.output.setReadOnly(True)
        layout.addWidget(self.output)

        cmd_layout = QHBoxLayout()
        self.command_input = QLineEdit()
        self.command_input.setPlaceholderText(
            "install ngspice | update ghdl | doctor | list"
        )
        self.command_input.returnPressed.connect(self.execute_command)
        cmd_layout.addWidget(self.command_input)

        self.run_btn = QPushButton("Run")
        self.run_btn.clicked.connect(self.execute_command)
        cmd_layout.addWidget(self.run_btn)
        layout.addLayout(cmd_layout)

        central_widget.setLayout(layout)

    def update_dependency_status(self):
        try:
            results = dependency.check_dependencies()
            if not results:
                self.log("No dependency data received")
                return

            result_map = {tool.lower(): (status, version) for tool, status, version in results}

            for row in range(self.table.rowCount()):
                checkbox = self.table.cellWidget(row, 0)
                tool_name = checkbox.text().lower()
                status, version = result_map.get(tool_name, ("not installed", "-"))
                self.table.setItem(row, 3, QTableWidgetItem(version))
                self.table.setItem(row, 4, QTableWidgetItem(status))
        except Exception as exc:
            self.log(f"Error: {exc}")

    def log(self, text):
        self.output.append(text)

    def set_busy_state(self, busy):
        self.install_btn.setEnabled(not busy)
        self.update_btn.setEnabled(not busy)
        self.uninstall_btn.setEnabled(not busy)
        self.refresh_btn.setEnabled(not busy)
        self.doctor_btn.setEnabled(not busy)
        self.run_btn.setEnabled(not busy)
        self.command_input.setEnabled(not busy)
        self.table.setEnabled(not busy)

    def start_background_task(self, task, start_message=None):
        if self.worker_thread is not None:
            self.log("Another task is already running. Please wait for it to finish.")
            return False

        if start_message:
            self.log(start_message)

        self.set_busy_state(True)

        signals = WorkerSignals()
        thread = QThread(self)
        worker = BackgroundWorker(lambda: task(signals.log.emit), signals)
        worker.moveToThread(thread)

        signals.log.connect(self.log)
        signals.error.connect(lambda message: self.log(f"Error: {message}"))
        signals.finished.connect(self.on_background_task_finished)
        thread.started.connect(worker.run)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)

        self.worker_thread = thread
        self.worker = worker
        thread.start()
        return True

    def on_background_task_finished(self):
        self.update_dependency_status()
        self.set_busy_state(False)
        self.worker = None
        self.worker_thread = None

    def get_selected_tools(self):
        selected = []
        for row in range(self.table.rowCount()):
            checkbox = self.table.cellWidget(row, 0)
            if checkbox.isChecked():
                tool = checkbox.text()
                version = self.table.cellWidget(row, 1).currentText()
                selected.append((tool, version))
        return selected

    def install_tool(self):
        selected = self.get_selected_tools()
        if not selected:
            self.log("Select at least one tool to install.")
            return

        self.start_background_task(
            lambda log: self.run_selected_installs(selected, log),
            "Starting install task...",
        )

    def update_tool(self):
        selected = self.get_selected_tools()
        if not selected:
            self.log("Select at least one tool to update.")
            return

        self.start_background_task(
            lambda log: self.run_selected_updates(selected, log),
            "Starting update task...",
        )

    def uninstall_tool(self):
        selected = self.get_selected_tools()
        if not selected:
            self.log("Select at least one tool to uninstall.")
            return

        self.start_background_task(
            lambda log: self.run_selected_uninstalls(selected, log),
            "Starting uninstall task...",
        )

    def run_selected_installs(self, selected, log):
        for tool, version in selected:
            installer.install_tool(tool, version=version, log=log)

    def _update_one_tool(self, tool, log):
        """
        Update policy (button behavior):
        - If not installed: tell user to install first.
        - If installed and already latest: log up-to-date.
        - If installed but outdated: install latest via installer.py.
        """
        def _install_latest(canonical_name):
            """
            Use installer.py to install "latest", but gracefully handle tool installers
            that don't accept a `version=` kwarg (e.g. `install_python(log=...)`).
            """
            try:
                installer.install_tool(canonical_name, version="latest", log=log)
                return
            except TypeError:
                pass

            fn = getattr(installer, "INSTALLERS", {}).get(canonical_name)
            if not fn:
                raise
            fn(log=log)

        tools_cfg = dependency.load_tools()

        # Find tool config by normalized key.
        canonical = installer.normalize_tool_name(tool)
        info = None
        display_name = tool
        for raw_name, raw_info in tools_cfg.items():
            if installer.normalize_tool_name(raw_name) == canonical:
                info = raw_info if isinstance(raw_info, dict) else {}
                display_name = raw_name
                break

        if not info:
            log(f"{tool}: tool config not found; cannot update.")
            return

        if not dependency.is_installed(info):
            log(f"{display_name} is not installed. Install it first.")
            return

        installed_version = dependency.get_installed_version(info)
        target = dependency.get_latest_target_version(info)

        # If we can't compare versions, fall back to installer update behavior.
        if not installed_version or not target:
            log(f"{display_name}: unable to determine version; running latest install.")
            _install_latest(canonical)
            return

        cmp = dependency.compare_versions(installed_version, target)
        if cmp == 0 or cmp == 1:
            log(f"{display_name} is already updated (v{installed_version}).")
            return

        # Outdated (or comparison failed): install latest.
        log(f"Updating {display_name}: v{installed_version} → v{target}")
        _install_latest(canonical)

    def run_selected_updates(self, selected, log):
        for tool, _version in selected:
            self._update_one_tool(tool, log)

    def run_selected_uninstalls(self, selected, log):
        for tool, _ in selected:
            installer.uninstall_tool(tool, log=log)

    def execute_command(self):
        command = self.command_input.text().strip()
        self.log(f"> {command}")

        parts = command.split()
        if not parts:
            return

        try:
            if parts[0] == "install":
                if len(parts) < 2:
                    self.log("Usage: install <tool> [version]")
                else:
                    version = parts[2] if len(parts) > 2 else "latest"
                    self.start_background_task(
                        lambda log: installer.install_tool(parts[1], version=version, log=log),
                        f"Starting install for {parts[1]}...",
                    )
            elif parts[0] == "update":
                if len(parts) < 2:
                    self.log("Usage: update <tool|all>")
                elif parts[1] == "all":
                    self.start_background_task(
                        lambda log: installer.update_all(log=log),
                        "Starting update for all managed tools...",
                    )
                else:
                    self.start_background_task(
                        lambda log: self._update_one_tool(parts[1], log),
                        f"Starting update for {parts[1]}...",
                    )
            elif parts[0] == "uninstall":
                if len(parts) < 2:
                    self.log("Usage: uninstall <tool>")
                else:
                    self.start_background_task(
                        lambda log: installer.uninstall_tool(parts[1], log=log),
                        f"Starting uninstall for {parts[1]}...",
                    )
            elif parts[0] == "list":
                self.update_dependency_status()
                for tool, status, version in dependency.check_dependencies():
                    self.log(f"{tool}: {status} ({version})")
            elif parts[0] == "doctor":
                self.run_doctor()
            elif parts[0] == "help":
                self.log(
                    "Commands: install <tool> [version], update <tool|all>, uninstall <tool>, list, doctor"
                )
            else:
                self.log("Unknown command")
        except Exception as exc:
            self.log(f"Error: {exc}")

        self.command_input.clear()

    def list_tools(self):
        self.update_dependency_status()

    def run_doctor(self):
        def task(log):
            buffer = io.StringIO()
            with redirect_stdout(buffer):
                dependency.run_doctor()
            for line in buffer.getvalue().splitlines():
                log(line)

        self.start_background_task(task, "Running system diagnostics...")

    def show_version(self):
        try:
            return importlib.metadata.version("esim-tools-manager")
        except importlib.metadata.PackageNotFoundError:
            return "0.2"


def main():
    app = QApplication(sys.argv)
    window = ToolManagerGUI()
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()

tool