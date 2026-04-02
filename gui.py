import io
import importlib.metadata
import os
import sys
from contextlib import redirect_stdout

import yaml
from PyQt5.QtCore import QObject, QThread, Qt, pyqtSignal
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import *

try:
    from tool_manager_gui import dependency, installer
except ImportError:
    import dependency
    import installer


# ---------------- SIGNALS ----------------
class WorkerSignals(QObject):
    log = pyqtSignal(str)
    error = pyqtSignal(str)
    finished = pyqtSignal()


# ---------------- WORKER ----------------
class BackgroundWorker(QObject):
    finished = pyqtSignal()

    def __init__(self, task, signals):
        super().__init__()
        self.task = task
        self.signals = signals

    def run(self):
        try:
            self.task(self.signals.log.emit)
        except Exception as e:
            self.signals.error.emit(str(e))
        finally:
            self.signals.finished.emit()
            self.finished.emit()


# ---------------- GUI ----------------
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

    # ---------- YAML ----------
    def load_tools_yaml(self):
        try:
            path = os.path.join(os.path.dirname(__file__), "tools.yml")
            with open(path, encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            return data.get("tools", {})
        except Exception as e:
            print("YAML Error:", e)
            return {}

    # ---------- UI ----------
    def init_ui(self):
        central = QWidget()
        self.setCentralWidget(central)

        layout = QVBoxLayout()

        title = QLabel("eSim Tool Manager")
        title.setFont(QFont("Arial", 18, QFont.Bold))
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)

        self.table = QTableWidget()
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(
            ["Tool", "Version", "Description", "Installed", "Status"]
        )
        self.table.setRowCount(len(self.tools_data))

        for row, (tool, info) in enumerate(self.tools_data.items()):
            checkbox = QCheckBox(tool)
            self.table.setCellWidget(row, 0, checkbox)

            combo = QComboBox()
            combo.addItems(["latest"] + info.get("versions", []))
            self.table.setCellWidget(row, 1, combo)

            self.table.setItem(row, 2, QTableWidgetItem(info.get("description", "")))
            self.table.setItem(row, 3, QTableWidgetItem("-"))
            self.table.setItem(row, 4, QTableWidgetItem("Checking..."))

        layout.addWidget(self.table)

        # Buttons
        btn_layout = QHBoxLayout()

        self.install_btn = QPushButton("Install")
        self.install_btn.clicked.connect(self.install_tool)
        btn_layout.addWidget(self.install_btn)

        self.update_btn = QPushButton("Update")
        self.update_btn.clicked.connect(self.update_tool)
        btn_layout.addWidget(self.update_btn)

        self.uninstall_btn = QPushButton("Uninstall")
        self.uninstall_btn.clicked.connect(self.uninstall_tool)
        btn_layout.addWidget(self.uninstall_btn)

        layout.addLayout(btn_layout)

        # System buttons
        sys_layout = QHBoxLayout()

        self.refresh_btn = QPushButton("Refresh")
        self.refresh_btn.clicked.connect(self.update_dependency_status)
        sys_layout.addWidget(self.refresh_btn)


        layout.addLayout(sys_layout)

        # Output
        self.output = QTextEdit()
        self.output.setReadOnly(True)
        layout.addWidget(self.output)

        # Command
        cmd_layout = QHBoxLayout()

        self.command_input = QLineEdit()
        self.command_input.returnPressed.connect(self.execute_command)
        cmd_layout.addWidget(self.command_input)

        run_btn = QPushButton("Run")
        run_btn.clicked.connect(self.execute_command)
        cmd_layout.addWidget(run_btn)

        layout.addLayout(cmd_layout)

        central.setLayout(layout)

    # ---------- LOG ----------
    def log(self, text):
        self.output.append(text)

    # ---------- BUSY ----------
    def set_busy(self, state):
        for w in [
            self.install_btn,
            self.update_btn,
            self.uninstall_btn,
            self.refresh_btn,
            self.doctor_btn,
            self.table,
        ]:
            w.setEnabled(not state)

    # ---------- THREAD ----------
    def start_task(self, task, msg=None):
        if self.worker_thread:
            self.log("Task already running...")
            return

        if msg:
            self.log(msg)

        self.set_busy(True)

        signals = WorkerSignals()
        thread = QThread()
        worker = BackgroundWorker(task, signals)

        worker.moveToThread(thread)

        thread.started.connect(worker.run)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)

        signals.log.connect(self.log)
        signals.error.connect(lambda e: self.log(f"Error: {e}"))
        signals.finished.connect(self.task_done)

        self.worker_thread = thread
        self.worker = worker

        thread.start()

    def task_done(self):
        self.update_dependency_status()
        self.set_busy(False)
        self.worker = None
        self.worker_thread = None

    # ---------- SELECT ----------
    def get_selected(self):
        selected = []
        for row in range(self.table.rowCount()):
            if self.table.cellWidget(row, 0).isChecked():
                tool = self.table.cellWidget(row, 0).text()
                version = self.table.cellWidget(row, 1).currentText()
                selected.append((tool, version))
        return selected

    # ---------- ACTIONS ----------
    def install_tool(self):
        selected = self.get_selected()
        if not selected:
            self.log("Select tools first")
            return

        def task(log):
            for t, v in selected:
                log(f"Installing {t} ({v})...")
                installer.install_tool(t, version=v, log=log)

        self.start_task(task, "Starting install...")

    def update_tool(self):
        selected = self.get_selected()

        def task(log):
            for t, _ in selected:
                log(f"Updating {t}...")
                installer.install_tool(t, version="latest", log=log)

        self.start_task(task, "Starting update...")

    def uninstall_tool(self):
        selected = self.get_selected()

        def task(log):
            for t, _ in selected:
                log(f"Uninstalling {t}...")
                installer.uninstall_tool(t, log=log)

        self.start_task(task, "Starting uninstall...")

    # ---------- STATUS ----------
    def update_dependency_status(self):
        try:
            results = dependency.check_dependencies()
            data = {t.lower(): (s, v) for t, s, v in results}

            for row in range(self.table.rowCount()):
                tool = self.table.cellWidget(row, 0).text().lower()
                status, version = data.get(tool, ("not installed", "-"))
                self.table.setItem(row, 3, QTableWidgetItem(version))
                self.table.setItem(row, 4, QTableWidgetItem(status))
        except Exception as e:
            self.log(str(e))

    # ---------- DOCTOR ----------
    def run_doctor(self):
        def task(log):
            buffer = io.StringIO()
            with redirect_stdout(buffer):
                dependency.run_doctor()
            for line in buffer.getvalue().splitlines():
                log(line)

        self.start_task(task, "Running doctor...")

    # ---------- COMMAND ----------
    def execute_command(self):
        cmd = self.command_input.text().strip()
        self.command_input.clear()
        self.log(f"> {cmd}")

    # ---------- VERSION ----------
    def show_version(self):
        try:
            return importlib.metadata.version("esim-tools-manager")
        except:
            return "0.2"


# ---------- MAIN ----------
def main():
    app = QApplication(sys.argv)
    win = ToolManagerGUI()
    win.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
