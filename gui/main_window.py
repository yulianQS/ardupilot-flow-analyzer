import logging
import time
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QTabWidget, QSplitter, QPlainTextEdit, QPushButton
from gui.connection_panel import ConnectionPanel
from gui.realtime_page import RealtimePage
from gui.mtf02p_page import MTF02PPage
from gui.rangefinder_page import RangeFinderPage
from gui.parameter_page import ParameterPage
from gui.status_text_page import StatusTextPage
from gui.log_page import LogPage
from gui.diagnosis_page import DiagnosisPage
from gui.ground_check_page import GroundCheckPage
from gui.help_text import install_help,tooltip,signal_help
from widgets.help_text_edit import HelpTextEdit
from mavlink.connection import ConnectionWorker
from analysis.realtime import RealtimeStore
from analysis.rangefinder import range_health
from widgets.realtime_plot import RealtimePlot
from pymavlink import mavutil
import config

STYLE = '''
QMainWindow, QWidget { background: #111923; color: #e4edf7; font-family: "Microsoft YaHei UI", "Microsoft YaHei", "Segoe UI"; font-size: 12px; }
QLabel#sectionTitle { font-size: 18px; font-weight: 600; color: #57d8c1; padding: 8px 0; }
QLabel#bigValue { font-size: 26px; padding: 16px; color: #57d8c1; }
QLabel#topStatus { background: #1a2938; border-radius: 6px; padding: 12px; }
QPushButton { background: #243548; padding: 9px 12px; border: 1px solid #354b61; border-radius: 5px; }
QPushButton:hover { background: #304b63; } QPushButton:disabled { color: #637789; background: #1b2733; }
QPushButton#primary { background: #176f68; border-color: #249a8c; }
QComboBox, QLineEdit { background: #1b2938; padding: 7px; border: 1px solid #354b61; border-radius: 4px; }
QTabWidget::pane { border: 1px solid #2c3d50; } QTabBar::tab { background: #192736; padding: 11px 14px; }
QTabBar::tab:selected { color: #57d8c1; background: #263c4a; }
QTableWidget { background: #14202d; alternate-background-color: #192939; gridline-color: #293d50; }
QHeaderView::section { background: #223447; padding: 7px; border: none; }
QPlainTextEdit { background: #111d29; border: 1px solid #2c3d50; padding: 7px; }
QProgressBar { border: 1px solid #354b61; text-align: center; min-height: 20px; }
QProgressBar::chunk { background: #218c7c; }
QSplitter::handle { background: #253648; }
QToolTip { background: #fff6d9; color: #172434; border: 1px solid #d7b96c; padding: 7px; font-size: 12px; }
'''

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('ArduPilot Optical Flow Analyzer')
        self.resize(1500, 950)
        self.setStyleSheet(STYLE)
        self.worker = None
        self.jobs = []
        self.store = RealtimeStore()
        self.armed = None
        self.connection_state = 'DISCONNECTED'
        self.info = {}
        self.firmware = 'N/A'
        self.parameter_values = {}
        self.closing = False
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        self.top = QLabel('DISCONNECTED · COM: N/A · Heartbeat: N/A · Vehicle: N/A · Firmware: N/A · Armed: N/A · Mode: N/A')
        self.top.setObjectName('topStatus')
        root.addWidget(self.top)
        horizontal = QSplitter(Qt.Orientation.Horizontal)
        self.connection_panel = ConnectionPanel()
        self.connection_panel.setMinimumWidth(210)
        self.connection_panel.setMaximumWidth(310)
        horizontal.addWidget(self.connection_panel)
        center = QSplitter(Qt.Orientation.Vertical)
        self.tabs = QTabWidget()
        self.realtime_page = RealtimePage()
        self.mtf_page = MTF02PPage()
        self.range_page = RangeFinderPage()
        self.parameter_page = ParameterPage()
        self.text_page = StatusTextPage()
        self.log_page = LogPage()
        self.diagnosis_page = DiagnosisPage()
        self.ground_page = GroundCheckPage()
        for page,name in [(self.realtime_page,'实时数据'),(self.mtf_page,'MTF02P'),(self.range_page,'RangeFinder'),
                          (self.log_page,'飞控日志'),(self.diagnosis_page,'BIN / Loiter'),
                          (self.parameter_page,'参数只读'),(self.ground_page,'地面检查'),(self.text_page,'STATUSTEXT / PreArm')]:
            self.tabs.addTab(page,name)
        center.addWidget(self.tabs)
        self.live_plot = RealtimePlot('实时姿态 · deg · 鼠标拖动 / 滚轮缩放')
        center.addWidget(self.live_plot)
        center.setSizes([630,220])
        horizontal.addWidget(center)
        side = QWidget()
        side_layout = QVBoxLayout(side)
        title = QLabel('实时状态 / 历史游标')
        title.setObjectName('sectionTitle')
        side_layout.addWidget(title)
        self.health = QLabel('尚未连接飞控')
        self.health.setWordWrap(True)
        side_layout.addWidget(self.health)
        self.health.setToolTip(tooltip(signal_help('quality')+'\n实时状态与下方历史 BIN 游标独立。'))
        self.history_title=QLabel('历史 BIN 游标（尚未打开）')
        self.history_title.setWordWrap(True);side_layout.addWidget(self.history_title)
        self.cursor_details = HelpTextEdit()
        self.cursor_details.setReadOnly(True)
        self.cursor_details.setPlaceholderText('打开 BIN 后，点击曲线查看同一时刻的全部信号。')
        side_layout.addWidget(self.cursor_details)
        self.record_button = QPushButton('开始保存实时 CSV')
        self.record_button.setCheckable(True)
        self.record_button.clicked.connect(self.record)
        side_layout.addWidget(self.record_button)
        self.events = QPlainTextEdit()
        self.events.setReadOnly(True)
        self.events.document().setMaximumBlockCount(500)
        self.events.setMaximumHeight(190)
        side_layout.addWidget(self.events)
        side.setMinimumWidth(250)
        horizontal.addWidget(side)
        horizontal.setSizes([220,1000,280])
        root.addWidget(horizontal)
        self.connection_panel.connect_requested.connect(self.connect_vehicle)
        self.connection_panel.disconnect_requested.connect(self.disconnect_vehicle)
        self.parameter_page.read_requested.connect(lambda:self.request('parameters'))
        self.connection_panel.open_requested.connect(self.open_bin)
        self.log_page.list_requested.connect(lambda:self.request('logs'))
        self.log_page.download_requested.connect(lambda entry:self.request('download',entry))
        self.log_page.cancel_requested.connect(lambda:self.request('cancel_download'))
        self.log_page.open_requested.connect(self.open_bin)
        self.diagnosis_page.cursor_text.connect(self.cursor_details.setPlainText)
        self.diagnosis_page.notice.connect(self.notice)
        self.diagnosis_page.job_started.connect(self.register_job)
        self.diagnosis_page.dataset_changed.connect(self.parameter_page.set_dataset)
        self.diagnosis_page.dataset_changed.connect(lambda data:self.history_title.setText('历史 BIN · '+data.path.replace('\\','/').split('/')[-1] if data else '历史 BIN（无数据）'))
        self.tabs.currentChanged.connect(lambda _:self.live_plot.setVisible(self.tabs.currentWidget()==self.realtime_page))
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(config.GUI_INTERVAL_MS)
        self.statusBar().showMessage('只读模式 · 不发送控制命令或参数修改')
        self.top.setToolTip('实时连接信息：HB为心跳距今时间；FW为固件；ARMED/DISARMED为解锁状态。与历史日志中的状态独立。')
        self.connection_panel.ports.setToolTip('电脑上的串口名称，例如 COM15；与飞控 SERIAL4 参数的编号不是同一含义。')
        self.connection_panel.baud.setToolTip('电脑串口通信波特率，例如115200。')
        install_help(self)

    def connect_vehicle(self,port,baud):
        if self.worker and self.worker.isRunning():
            return
        self.store = RealtimeStore()
        self.firmware = 'N/A'
        self.parameter_values = {}
        self.log_page.set_entries([])
        self.parameter_page.reset()
        self.mtf_page.reset()
        self.ground_page.reset()
        self.worker = ConnectionWorker(port,baud)
        self.worker.state.connect(self.set_connection_state)
        self.worker.messages.connect(self.receive)
        self.worker.error.connect(self.show_error)
        self.worker.notice.connect(self.notice)
        self.worker.parameters.connect(self.parameter_received)
        self.wire_log_signals()
        self.connection_panel.set_state('CONNECTING')
        self.worker.start()

    def register_job(self,job):
        self.jobs.append(job)
        job.finished.connect(lambda:self.jobs.remove(job) if job in self.jobs else None)

    def wire_log_signals(self):
        self.worker.logs.connect(self.log_page.set_entries)
        self.worker.download_progress.connect(self.log_page.update_progress)
        self.worker.download_done.connect(self.log_page.completed)

    def disconnect_vehicle(self):
        if self.worker:
            self.worker.stop()

    def request(self,action,payload=None):
        if not self.worker or not self.worker.isRunning() or self.connection_state != 'CONNECTED':
            self.show_error('请先连接飞控并等待 HEARTBEAT')
            return
        self.worker.request(action,payload)

    def record(self,checked):
        if self.connection_state != 'CONNECTED':
            self.record_button.setChecked(False)
            self.show_error('请先连接后再开始保存 CSV')
            return
        self.request('record',checked)
        self.record_button.setText('停止保存实时 CSV' if checked else '开始保存实时 CSV')

    def parameter_received(self,name,value):
        self.parameter_values[name] = value
        self.parameter_page.set_value(name,value)

    def set_connection_state(self,state,info):
        self.connection_state, self.info = state, info
        self.armed = info.get('armed') if state == 'CONNECTED' else None
        self.connection_panel.set_state(state)
        self.parameter_page.set_connected(state=='CONNECTED')
        if state == 'DISCONNECTED':
            self.record_button.setChecked(False)
            self.record_button.setText('开始保存实时 CSV')
        self.refresh()

    def receive(self,batch):
        for timestamp,kind,data in batch:
            self.store.add(timestamp,kind,data)
            if kind == 'STATUSTEXT':
                self.text_page.add(data)
                text = str(data.get('text',''))
                if text.startswith('ArduCopter'):
                    self.firmware = text
            elif kind == 'AUTOPILOT_VERSION':
                version = int(data.get('flight_sw_version',0))
                if version:
                    self.firmware = f'{version >> 24}.{(version >> 16)&255}.{(version >> 8)&255} (type {version&255})'

    def refresh(self):
        now = time.monotonic()
        info = self.info
        age = now - info['heartbeat'] if 'heartbeat' in info else None
        heartbeat = f'{age:.1f}s' if age is not None else 'N/A'
        armed = 'ARMED' if self.armed else ('DISARMED' if self.armed is False else 'N/A')
        vehicle_enum = mavutil.mavlink.enums['MAV_TYPE'].get(info.get('type'))
        vehicle = vehicle_enum.name.replace('MAV_TYPE_','') if vehicle_enum else 'N/A'
        self.top.setText(f"{self.connection_state}  |  {info.get('port','N/A')}  |  HB {heartbeat}  |  {vehicle} / AP {info.get('autopilot','N/A')}  |  FW {self.firmware}  |  {armed}  |  {info.get('mode','N/A')}  |  Sys/Comp {info.get('system','N/A')}/{info.get('component','N/A')}")
        if self.connection_state != 'CONNECTED':
            # 断开后立即失效，不等旧样本自然超时。
            display_now = now + config.STALE_S
        else:
            display_now = now
        self.realtime_page.update_data(self.store,display_now)
        self.mtf_page.update_data(self.store,display_now,self.armed)
        self.range_page.update_data(self.store,display_now)
        self.ground_page.update_data(self.store,now,self.armed,self.connection_state=='CONNECTED' and age is not None and age<config.HEARTBEAT_TIMEOUT_S)
        self.live_plot.update_data(self.store,now)
        prefix,_ = self.store.flow_source(display_now)
        quality = self.store.get(prefix+'_quality',display_now)
        quality_text = 'N/A' if quality is None else f'{quality:.0f}/255 · '+(f'低于本地阈值{config.FLOW_QUALITY_MIN}' if quality<config.FLOW_QUALITY_MIN else '本地阈值内（非准飞证明）')
        flags = self.store.get('ekf_flags',display_now)
        ekf_text = 'N/A' if flags is None else ' / '.join(value.name.replace('EKF_','') for bit,value in mavutil.mavlink.enums['EKF_STATUS_FLAGS'].items() if bit>0 and bit&(bit-1)==0 and int(flags)&bit)
        self.health.setText(f"【实时 MAVLink · {self.connection_state}】\n{range_health(self.store,display_now)}\n\nQuality: {quality_text}\n\nEKF: {ekf_text}\n\n{self.store.static_warning(display_now,self.armed)}")

    def notice(self,text):
        self.events.appendPlainText(time.strftime('%H:%M:%S')+' '+text)
        self.statusBar().showMessage(text,15000)

    def show_error(self,text):
        self.notice('ERROR: '+text)
        self.log_page.failed(text)

    def open_bin(self,path=None):
        self.tabs.setCurrentWidget(self.diagnosis_page)
        self.diagnosis_page.open_file(path)

    def closeEvent(self,event):
        active = []
        if self.worker and self.worker.isRunning():
            self.worker.stop()
            active.append(self.worker)
        for job in self.jobs:
            if job.isRunning():
                job.requestInterruption()
                active.append(job)
        if self.connection_panel.scanner and self.connection_panel.scanner.isRunning():
            active.append(self.connection_panel.scanner)
        if active:
            event.ignore()
            self.closing = True
            self.statusBar().showMessage('正在关闭串口和后台任务…')
            QTimer.singleShot(100,self.close)
        else:
            self.timer.stop()
            logging.info('程序退出：所有工作线程已结束')
            event.accept()
