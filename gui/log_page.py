from datetime import datetime, timezone
from PySide6.QtCore import Signal
from PySide6.QtWidgets import QWidget,QVBoxLayout,QHBoxLayout,QPushButton,QProgressBar,QLabel
from gui.common import table,cell

class LogPage(QWidget):
    list_requested = Signal()
    download_requested = Signal(object)
    cancel_requested = Signal()
    open_requested = Signal(str)
    def __init__(self):
        super().__init__()
        self.entries = {}
        self.last_path = ''
        self.active_id = None
        self.row_states = {}
        layout = QVBoxLayout(self)
        hint = QLabel('飞控内部 DataFlash 日志 · 仅 DISARMED 时枚举/下载 · 不删除飞控日志')
        hint.setMaximumHeight(32)
        layout.addWidget(hint)
        controls = QHBoxLayout()
        for text,slot in [('刷新日志列表',self.list_requested.emit),('下载选中日志',self.selected),
                          ('下载最新日志',self.latest),('取消下载',self.cancel_requested.emit),('打开已下载BIN',self.open_downloaded)]:
            button = QPushButton(text)
            button.clicked.connect(slot)
            controls.addWidget(button)
        layout.addLayout(controls)
        self.table = table(['Log ID','Size (bytes)','Date/Time (UTC)','状态'])
        layout.addWidget(self.table,1)
        self.progress = QProgressBar()
        layout.addWidget(self.progress)
        self.status = QLabel('尚未读取日志列表')
        self.status.setWordWrap(True)
        layout.addWidget(self.status)

    def set_entries(self,entries):
        self.entries = {int(entry['id']):entry for entry in entries}
        self.table.setRowCount(len(entries))
        for row,entry in enumerate(sorted(entries,key=lambda item:item['id'])):
            timestamp = entry.get('time_utc',0)
            # 无GPS时 FAT 默认1980时间不可信，不能展示为真实飞行日期。
            valid = 946684800 <= timestamp <= datetime.now(timezone.utc).timestamp()+86400
            date = datetime.fromtimestamp(timestamp,timezone.utc).strftime('%Y-%m-%d %H:%M:%S') if valid else 'N/A（时间未同步）'
            for column,value in enumerate([entry['id'],entry['size'],date,self.row_states.get(entry['id'],'可下载')]):
                cell(self.table,row,column,value)
        self.status.setText(f'已收到 {len(entries)} 条；最新按 last_log_num 判定。')

    def selected(self):
        row = self.table.currentRow()
        if row<0:
            self.status.setText('请先在表格中选中日志')
            return
        self.start_download(self.entries[int(self.table.item(row,0).text())])

    def latest(self):
        if not self.entries:
            self.status.setText('请先刷新并等待日志列表')
            return
        latest = next(iter(self.entries.values())).get('last_log_num')
        if latest not in self.entries:
            self.status.setText('列表不完整：尚未收到 last_log_num 对应日志，请刷新')
            return
        self.start_download(self.entries[latest])

    def start_download(self,entry):
        if self.active_id is not None:
            self.status.setText('已有下载请求，请等待完成或取消。')
            return
        self.active_id = entry['id']
        self.set_row_state('请求下载')
        self.download_requested.emit(entry)

    def set_row_state(self,text):
        if self.active_id is None:
            return
        self.row_states[self.active_id] = text
        for row in range(self.table.rowCount()):
            if int(self.table.item(row,0).text()) == self.active_id:
                cell(self.table,row,3,text)

    def update_progress(self,data):
        done,total = data['done'],data['total']
        self.set_row_state('下载中')
        self.progress.setValue(int(done*100/max(total,1)))
        self.status.setText(f"{done:,} / {total:,} bytes · {done*100/max(total,1):.2f}% · {data['speed']/1024:.1f} KiB/s")

    def completed(self,path):
        self.last_path = path
        self.set_row_state('已完成 / 大小一致')
        self.active_id = None
        self.progress.setValue(100)
        self.status.setText('下载完成：覆盖校验与文件大小一致\n'+path)

    def failed(self,text):
        if self.active_id is not None:
            self.set_row_state('未完成 / 请检查错误')
            self.active_id = None
            self.status.setText(text)

    def open_downloaded(self):
        if self.last_path:
            self.open_requested.emit(self.last_path)
        else:
            self.status.setText('尚无已完成的下载')
