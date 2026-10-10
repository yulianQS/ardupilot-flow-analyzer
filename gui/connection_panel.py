from PySide6.QtCore import Signal, QThread
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QComboBox, QPushButton
from mavlink.connection import scan_ports
import config

class PortScanner(QThread):
    ready = Signal(object)
    def run(self):
        try:
            self.ready.emit(scan_ports())
        except Exception as exception:
            self.ready.emit([{'error': str(exception)}])

class ConnectionPanel(QWidget):
    connect_requested = Signal(str, int)
    disconnect_requested = Signal()
    open_requested = Signal()
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        title = QLabel('连接与日志')
        title.setObjectName('sectionTitle')
        layout.addWidget(title)
        self.ports = QComboBox()
        self.ports.setEditable(True)
        self.ports.setEditText(config.DEFAULT_PORT)
        layout.addWidget(self.ports)
        self.details = QLabel('VID / PID / Manufacturer: N/A')
        self.details.setWordWrap(True)
        layout.addWidget(self.details)
        self.baud = QComboBox()
        self.baud.addItems(['115200','57600','230400','460800','921600'])
        layout.addWidget(self.baud)
        self.refresh_button = QPushButton('刷新串口')
        self.refresh_button.clicked.connect(self.scan)
        layout.addWidget(self.refresh_button)
        self.connect_button = QPushButton('连接飞控')
        self.connect_button.setObjectName('primary')
        self.connect_button.clicked.connect(lambda: self.connect_requested.emit(self.ports.currentText().strip(), int(self.baud.currentText())))
        layout.addWidget(self.connect_button)
        self.disconnect_button = QPushButton('断开')
        self.disconnect_button.setEnabled(False)
        self.disconnect_button.clicked.connect(self.disconnect_requested)
        layout.addWidget(self.disconnect_button)
        open_button = QPushButton('打开本地 BIN')
        open_button.clicked.connect(self.open_requested)
        layout.addWidget(open_button)
        hint = QLabel('只读诊断\nUSB / MAVLink\n\nMission Planner 需先断开 COM15。\n\nBody：X机头 / Y右 / Z下\nNED：X北 / Y东 / Z下')
        hint.setWordWrap(True)
        layout.addWidget(hint)
        layout.addStretch()
        self.ports.currentIndexChanged.connect(self.show_details)
        self.scanner = None
        self.scan()

    def scan(self):
        if self.scanner and self.scanner.isRunning():
            return
        self.refresh_button.setEnabled(False)
        self.scanner = PortScanner()
        self.scanner.ready.connect(self.scanned)
        self.scanner.finished.connect(lambda: self.refresh_button.setEnabled(True))
        self.scanner.start()

    def scanned(self, ports):
        previous = self.ports.currentText()
        self.ports.clear()
        for port in ports:
            if 'error' in port:
                self.details.setText(port['error'])
            else:
                self.ports.addItem(port['device'], port)
        index = self.ports.findText(previous)
        if index < 0:
            index = self.ports.findText(config.DEFAULT_PORT)
        if index >= 0:
            self.ports.setCurrentIndex(index)
        elif self.ports.count() == 0:
            self.ports.setEditText(config.DEFAULT_PORT)
            self.details.setText('未发现串口。可以手动填写端口。')
        self.show_details()

    def show_details(self):
        port = self.ports.currentData()
        if port:
            self.details.setText(f"{port['description']}\nVID {port['vid']} / PID {port['pid']}\n{port['manufacturer']}")

    def set_state(self, state):
        idle = state == 'DISCONNECTED'
        self.connect_button.setEnabled(idle)
        self.disconnect_button.setEnabled(not idle)
        self.ports.setEnabled(idle)
        self.baud.setEnabled(idle)
