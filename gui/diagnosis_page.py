import logging
from PySide6.QtCore import Signal
from PySide6.QtWidgets import QWidget,QVBoxLayout,QHBoxLayout,QPushButton,QComboBox,QLabel,QProgressBar,QTabWidget,QPlainTextEdit,QFileDialog
from analysis.bin_parser import ParserWorker
from analysis.loiter_diagnosis import DiagnosisWorker
from widgets.timeline_cursor import TimelinePlots,MODE_NAMES
from analysis.timeline_events import extract_events,active_bounds
from gui.help_text import tooltip,help_for
import config

class DiagnosisPage(QWidget):
    cursor_text = Signal(str)
    notice = Signal(str)
    job_started = Signal(object)
    dataset_changed = Signal(object)
    def __init__(self):
        super().__init__()
        self.dataset = None
        self.report = None
        self.parser = None
        self.diagnoser = None
        layout = QVBoxLayout(self)
        controls = QHBoxLayout()
        open_button = QPushButton('打开本地 BIN')
        open_button.clicked.connect(lambda:self.open_file())
        controls.addWidget(open_button)
        controls.addWidget(QLabel('EKF core'))
        self.core = QComboBox()
        self.core.addItem('0')
        self.core.setToolTip(tooltip(help_for('EKF core')))
        controls.addWidget(self.core)
        controls.addWidget(QLabel('RFND实例'))
        self.range_instance = QComboBox()
        self.range_instance.addItem('0')
        self.range_instance.setToolTip(tooltip(help_for('RFND实例')))
        controls.addWidget(self.range_instance)
        self.diagnose_button = QPushButton('全程诊断')
        self.diagnose_button.setObjectName('primary')
        self.diagnose_button.clicked.connect(self.diagnose)
        self.diagnose_button.setEnabled(False)
        controls.addWidget(self.diagnose_button)
        self.export_button = QPushButton('导出 TXT / CSV / HTML')
        self.export_button.clicked.connect(self.export_report)
        self.export_button.setEnabled(False)
        controls.addWidget(self.export_button)
        layout.addLayout(controls)
        self.status = QLabel('尚未打开 BIN')
        self.status.setWordWrap(True)
        self.status.setMaximumHeight(65)
        layout.addWidget(self.status)
        progress_row = QHBoxLayout()
        self.progress = QProgressBar()
        progress_row.addWidget(self.progress)
        cancel = QPushButton('取消后台任务')
        cancel.clicked.connect(self.cancel)
        progress_row.addWidget(cancel)
        layout.addLayout(progress_row)
        self.tabs = QTabWidget()
        self.plots = TimelinePlots()
        self.tabs.addTab(self.plots,'同步曲线')
        self.report_text = QPlainTextEdit()
        self.report_text.setReadOnly(True)
        self.tabs.addTab(self.report_text,'诊断报告')
        self.inventory = QPlainTextEdit()
        self.inventory.setReadOnly(True)
        self.tabs.addTab(self.inventory,'消息与字段')
        layout.addWidget(self.tabs,1)
        self.plots.cursor_changed.connect(self.show_cursor)
        self.core.currentTextChanged.connect(self.rebuild)
        self.range_instance.currentTextChanged.connect(self.rebuild)

    def cancel(self):
        for job in (self.parser,self.diagnoser):
            if job and job.isRunning():
                job.requestInterruption()

    def open_file(self,path=None):
        if any(job and job.isRunning() for job in (self.parser,self.diagnoser)):
            self.notice.emit('请先等待或取消当前解析/诊断任务')
            return
        if not path:
            path,_ = QFileDialog.getOpenFileName(self,'打开 ArduPilot BIN',str(config.LOG_DIR),'DataFlash BIN (*.BIN *.bin)')
        if not path:
            return
        self.report = None
        self.export_button.setEnabled(False)
        self.diagnose_button.setEnabled(False)
        self.core.setEnabled(False)
        self.range_instance.setEnabled(False)
        self.dataset = None
        self.dataset_changed.emit(None)
        self.plots.set_signals({})
        self.report_text.clear()
        self.inventory.clear()
        self.cursor_text.emit('正在解析新文件；旧日志数据已清空。')
        self.status.setText('扫描格式与消息类型… '+path)
        self.parser = ParserWorker(path)
        self.parser.progress.connect(self.progress.setValue)
        self.parser.result.connect(self.loaded)
        self.parser.error.connect(self.failed)
        self.job_started.emit(self.parser)
        self.parser.start()

    def failed(self,text):
        self.status.setText('ERROR: '+text)
        self.notice.emit(text)
        self.progress.setRange(0,100)
        self.core.setEnabled(True)
        self.range_instance.setEnabled(True)
        self.diagnose_button.setEnabled(self.dataset is not None)

    def loaded(self,dataset):
        self.dataset = dataset
        self.dataset_changed.emit(dataset)
        self.core.blockSignals(True)
        self.range_instance.blockSignals(True)
        self.core.clear()
        self.core.addItems([str(value) for value in dataset.instances(['XKF1','NKF1'])])
        self.range_instance.clear()
        self.range_instance.addItems([str(value) for value in dataset.instances(['RFND'])])
        self.core.blockSignals(False)
        self.range_instance.blockSignals(False)
        self.core.setEnabled(True)
        self.range_instance.setEnabled(True)
        self.diagnose_button.setEnabled(True)
        self.inventory.setPlainText('\n'.join(f'{kind}: {count:,} 条; 字段: '+', '.join(dataset.frames[kind].columns) if kind in dataset.frames else f'{kind}: {count:,} 条（仅计数/无时序）'
                                              for kind,count in sorted(dataset.counts.items()))+'\n\n'+'\n'.join(dataset.warnings))
        low,high=active_bounds(dataset.signals())
        self.status.setText(f'{dataset.path}\n连续信号范围 {low:.2f}–{high:.2f}s · 文件末时刻 {dataset.duration:.2f}s（不等于飞行时长）· {sum(dataset.counts.values()):,} 条记录')
        self.rebuild()
        self.notice.emit('BIN解析完成: '+dataset.path)

    def rebuild(self):
        if self.dataset is None or not self.core.currentText() or not self.range_instance.currentText():
            return
        self.report = None
        self.export_button.setEnabled(False)
        self.report_text.setPlainText('数据或实例已更新，请运行全程诊断。涵盖完整 Loiter 段及解锁、急停、融合和异常事件。')
        signals = self.dataset.signals(int(self.core.currentText()),int(self.range_instance.currentText()))
        self.plots.set_signals(signals)
        self.plots.set_events(extract_events(self.dataset,signals))
        self.show_cursor(self.plots.current_time)

    def show_cursor(self,timestamp):
        lines = ['【历史 BIN 游标 · 非实时】',f'文件: {self.dataset.path if self.dataset else "N/A"}',f'Time: {timestamp:.3f} s',
                 '连续量显示±0.5s内最近样本，缺口为N/A；模式/解锁使用此前最近状态。悬停字段行查看解释。']
        for key,series in self.plots.signals.items():
            value = series.at(timestamp)
            display = 'N/A' if value is None else (MODE_NAMES.get(int(value),str(int(value))) if key=='mode' else f'{value:.4g} {series.unit}')
            lines.append(f'{key}: {display} · {series.source}')
        self.cursor_text.emit('\n'.join(lines))

    def diagnose(self):
        if self.dataset is None or (self.diagnoser and self.diagnoser.isRunning()):
            return
        self.diagnose_button.setEnabled(False)
        self.core.setEnabled(False)
        self.range_instance.setEnabled(False)
        self.progress.setRange(0,0)
        self.diagnoser = DiagnosisWorker(self.dataset,int(self.core.currentText()),int(self.range_instance.currentText()))
        self.diagnoser.result.connect(self.diagnosed)
        self.diagnoser.error.connect(self.failed)
        self.job_started.emit(self.diagnoser)
        self.diagnoser.start()

    def diagnosed(self,report):
        self.report = report
        self.progress.setRange(0,100)
        self.progress.setValue(100)
        self.diagnose_button.setEnabled(True)
        self.core.setEnabled(True)
        self.range_instance.setEnabled(True)
        self.export_button.setEnabled(True)
        self.report_text.setPlainText(report.text())
        self.tabs.setCurrentWidget(self.report_text)
        self.notice.emit(f'全程诊断完成: {len(report.timeline)} 个时间线事件，{len(report.events)} 段 Loiter')

    def export_report(self):
        if not self.report:
            return
        name = config.DATA_DIR / (self.dataset.path.replace('\\','/').split('/')[-1]+'.diagnosis.txt')
        path,_ = QFileDialog.getSaveFileName(self,'导出诊断',str(name),'Text (*.txt);;CSV (*.csv);;HTML (*.html)')
        if path:
            try:
                self.report.export(path)
                self.notice.emit('诊断已导出: '+path)
            except Exception as exception:
                logging.exception('报告导出失败')
                self.failed(str(exception))
