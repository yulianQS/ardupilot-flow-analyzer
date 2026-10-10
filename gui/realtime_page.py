import json
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QSplitter, QPlainTextEdit
from PySide6.QtCore import Qt
from gui.common import table, cell, number

class RealtimePage(QWidget):
    FIELDS = [('roll','Roll','deg'),('pitch','Pitch','deg'),('yaw','Yaw','deg'),
              ('vx','VX 北','m/s'),('vy','VY 东','m/s'),('vz','VZ 下','m/s'),
              ('flow_x','Optical Flow X',''),('flow_y','Optical Flow Y',''),('quality','Quality','0..255'),
              ('range','RangeFinder','m'),('ekf_flags','EKF flags','bitmask'),
              ('vibe_x','Vibration X','m/s²'),('vibe_y','Vibration Y','m/s²'),('vibe_z','Vibration Z','m/s²'),
              ('battery_v','Battery','V')]
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        caption = QLabel('实时遥测 · 超过有效期的数据自动显示 N/A')
        caption.setMaximumHeight(32)
        layout.addWidget(caption)
        split = QSplitter(Qt.Orientation.Horizontal)
        self.values = table(['信号','当前值','单位','数据来源','样本距今'], len(self.FIELDS))
        split.addWidget(self.values)
        self.raw = QPlainTextEdit()
        self.raw.setReadOnly(True)
        self.raw.setPlaceholderText('收到的 MAVLink 消息及原始字段（只读）')
        split.addWidget(self.raw)
        layout.addWidget(split,1)

    def update_data(self, store, now):
        prefix, unit = store.flow_source(now)
        for row, (key, title, units) in enumerate(self.FIELDS):
            mapped = {'flow_x':prefix+'_x','flow_y':prefix+'_y','quality':prefix+'_quality'}.get(key,key)
            value = store.get(mapped, now)
            if key in ('vx','vy','vz') and value is None:
                mapped='global_'+key
                value = store.get(mapped, now)
            cell(self.values,row,0,title)
            cell(self.values,row,1,number(value))
            cell(self.values,row,2,unit if key.startswith('flow_') else units)
            timestamp=store.latest.get(mapped,(None,None))[0]
            source=('GLOBAL_POSITION_INT' if mapped.startswith('global_') else 'LOCAL_POSITION_NED') if key in ('vx','vy','vz') else mapped
            cell(self.values,row,3,source)
            cell(self.values,row,4,'未收到' if timestamp is None else (f'{max(0,now-timestamp):.1f}s'+(' / 已过期' if value is None else '')))
        cursor = self.raw.verticalScrollBar().value()
        data = {kind: {'age_s':round(now-store.message_times[kind],2), **value} for kind,value in store.raw_messages.items()}
        self.raw.setPlainText(json.dumps(data, indent=2, ensure_ascii=False, default=str))
        self.raw.verticalScrollBar().setValue(cursor)
