import csv
import math
import time
from pathlib import Path
from PySide6.QtCore import Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QWidget, QVBoxLayout, QPushButton, QLabel,QLineEdit,QHBoxLayout,QFileDialog,QHeaderView
from gui.common import table, cell
from gui.help_text import parameter_help,tooltip
import config

class ParameterPage(QWidget):
    read_requested = Signal()
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        self.live={};self.logged={};self.log_path='';self.connected=False
        self.caption=QLabel('光流相关参数只读；悬停参数名或数值查看解释。未返回 / 固件不支持显示 N/A。')
        self.caption.setWordWrap(True)
        layout.addWidget(self.caption)
        controls=QHBoxLayout()
        button = QPushButton('重新读取参数')
        button.clicked.connect(self.reread)
        controls.addWidget(button)
        export=QPushButton('导出参数对比 CSV')
        export.setToolTip('导出本页已有读数与日志末次值，不会写入飞控。')
        export.clicked.connect(self.export)
        controls.addWidget(export)
        layout.addLayout(controls)
        self.search=QLineEdit()
        self.search.setPlaceholderText('搜索参数名称或中文解释，例如 光流 / 高度 / FLOW')
        self.search.setToolTip('过滤当前表格，不会改变飞控参数或请求范围。')
        self.search.textChanged.connect(self.filter_rows)
        layout.addWidget(self.search)
        self.names = list(config.PARAMETERS)
        self.table = table(['Parameter','实时读取','日志末次值','对比','Description'], len(self.names))
        self.table.horizontalHeader().setSectionResizeMode(4,QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.table)
        self.review=QLabel('打开 BIN 可对比日志参数；连接飞控可读取当前会话参数。')
        self.review.setWordWrap(True);layout.addWidget(self.review)
        self.reset()

    def reset(self):
        self.live.clear()
        for row,name in enumerate(self.names):
            cell(self.table,row,0,name)
            self.render_row(row)

    def reread(self):
        if self.connected:self.reset()
        self.read_requested.emit()

    def render_row(self,row):
        name=self.names[row]
        current=self.live.get(name);logged=self.logged.get(name)
        status='缺少一侧数据'
        if current is not None and logged is not None:status='一致' if math.isclose(current[0],logged,rel_tol=1e-6,abs_tol=1e-6) else '数值不同'
        if current is not None and not self.connected:status+='（连接已断开）'
        for col,value in enumerate([current[0] if current else None,logged,status,parameter_help(name).split('；')[0]],1):cell(self.table,row,col,value)
        detail=parameter_help(name)+'\n只读；差异不等于配置错误。'
        for col in range(5):self.table.item(row,col).setToolTip(tooltip(detail))
        self.table.item(row,3).setForeground(QColor('#ffb454' if status.startswith('数值不同') else '#c5d4df'))
        if current:self.table.item(row,1).setToolTip(tooltip(detail+f'\n本会话读取时间：{current[1]}；'+('当前已连接，读数仍为最近一次请求快照。' if self.connected else '连接已断开，保留历史读数。')))
        self.table.item(row,2).setToolTip(tooltip(detail+'\n日志来源：'+(self.log_path or '未打开日志')+'；显示日志末次记录值。'))

    def set_value(self, name, value):
        if name in self.names:
            self.live[name]=(float(value),time.strftime('%Y-%m-%d %H:%M:%S'))
            self.render_row(self.names.index(name))

    def set_connected(self,connected):
        self.connected=connected
        for row in range(len(self.names)):self.render_row(row)

    def set_dataset(self,dataset):
        self.logged=dict(dataset.parameters) if dataset else {}
        self.log_path=dataset.path if dataset else ''
        for row in range(len(self.names)):self.render_row(row)
        self.review.setText('日志参数来源：'+(self.log_path or '无')+'\n安装方向、比例、地面间隙与量程需要实测；此处仅对比，不自动判定应改成哪个值。')

    def filter_rows(self,text):
        text=text.casefold().strip()
        for row,name in enumerate(self.names):self.table.setRowHidden(row,text not in (name+' '+parameter_help(name)).casefold())

    def export(self):
        path,_=QFileDialog.getSaveFileName(self,'导出参数对比',str(config.DATA_DIR/'parameter_comparison.csv'),'CSV (*.csv)')
        if not path:return
        try:
            with Path(path).open('w',encoding='utf-8-sig',newline='') as stream:
                writer=csv.writer(stream);writer.writerow(['parameter','live_value','live_read_time','connected','log_last_value','log_path','description'])
                for name in self.names:
                    live=self.live.get(name,('',''))
                    writer.writerow([name,*live,self.connected,self.logged.get(name,''),self.log_path,parameter_help(name)])
            self.review.setText('已导出：'+path)
        except OSError as exc:self.review.setText('导出失败：'+str(exc))
