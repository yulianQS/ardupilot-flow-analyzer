from collections import deque
from datetime import datetime
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLineEdit, QComboBox, QPushButton, QPlainTextEdit, QApplication
import config

class StatusTextPage(QWidget):
    def __init__(self):
        super().__init__()
        self.entries = deque(maxlen=config.STATUSTEXT_MAX)
        layout = QVBoxLayout(self)
        controls = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText('搜索 PreArm / EKF / Rangefinder / GPS / Optical Flow')
        controls.addWidget(self.search)
        self.severity = QComboBox()
        self.severity.addItems(['全部','0–3 错误','0–4 警告','0–6 信息'])
        controls.addWidget(self.severity)
        copy = QPushButton('复制筛选结果')
        controls.addWidget(copy)
        layout.addLayout(controls)
        self.text = QPlainTextEdit()
        self.text.setReadOnly(True)
        layout.addWidget(self.text)
        self.search.textChanged.connect(self.render)
        self.severity.currentIndexChanged.connect(self.render)
        copy.clicked.connect(lambda: QApplication.clipboard().setText(self.text.toPlainText()))

    def add(self, data):
        text = data.get('text','')
        if isinstance(text, bytes):
            text = text.decode('utf-8', errors='replace')
        # MAVLink2 分块信息保留 id/seq，避免把缺块拼成看似完整的原文。
        chunk = f" [id={data['id']} seq={data.get('chunk_seq',0)}]" if data.get('id') else ''
        self.entries.append((datetime.now().strftime('%H:%M:%S'), int(data.get('severity',6)), str(text).rstrip('\x00')+chunk))
        self.render()

    def render(self):
        query = self.search.text().lower()
        maximum = [7,3,4,6][self.severity.currentIndex()]
        self.text.setPlainText('\n'.join(f'{timestamp} [{severity}] {text}' for timestamp,severity,text in self.entries
                                        if severity <= maximum and query in text.lower()))
