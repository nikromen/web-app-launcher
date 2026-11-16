import subprocess
import sys
from pathlib import Path

QML_LOAD_TIMEOUT_SECONDS = 10
QML_DIR = Path(__file__).resolve().parent.parent.parent / "web_app_launcher" / "qml"
QML_CHECK = """
import sys
from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlComponent, QQmlEngine

app = QGuiApplication([])
engine = QQmlEngine()
qml_dir = Path(sys.argv[1])
for path in sorted(qml_dir.glob("*.qml")):
    component = QQmlComponent(engine, QUrl.fromLocalFile(str(path)))
    assert component.isReady(), (path.name, [error.toString() for error in component.errors()])

    if path.name == "HelpTip.qml":
        tip = component.createWithInitialProperties({"tipText": "Help"})
        assert tip is not None, component.errors()
        assert tip.property("implicitWidth") > 0
        assert tip.property("implicitHeight") == tip.property("implicitWidth")
        del tip
"""


def test_qml_components_load_with_shared_metrics():
    result = subprocess.run(
        [sys.executable, "-c", QML_CHECK, str(QML_DIR)],
        capture_output=True,
        text=True,
        timeout=QML_LOAD_TIMEOUT_SECONDS,
        check=False,
    )

    assert result.returncode == 0, result.stderr
