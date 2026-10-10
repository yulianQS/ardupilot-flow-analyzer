import time
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QPushButton, QHBoxLayout, QComboBox, QSpinBox
from gui.common import table, cell, number
from analysis.optical_flow import DIRECTIONS, evaluate_direction
from analysis.capture_checks import motion_errors, filter_capture
from widgets.realtime_plot import RealtimePlot
import config

class MTF02PPage(QWidget):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        self.title = QLabel('MTF02P · 光流与测距')
        layout.addWidget(self.title)
        self.table = table(['信号','当前','1秒均值','5秒均值','5秒标准差','5秒最大','5秒最小'],4)
        self.table.setMinimumHeight(175)
        self.table.setMaximumHeight(205)
        layout.addWidget(self.table)
        self.health = QLabel('信号波动检查：证据不足')
        self.health.setWordWrap(True)
        layout.addWidget(self.health)
        self.plot = RealtimePlot('Optical Flow / rad/s', ['flow_rate_x','flow_rate_y'])
        layout.addWidget(self.plot)
        instruction = QLabel('Optical Flow Direction Test\n确认 DISARMED、保持水平且不旋转。每步点击后沿提示方向持续平移3秒，停止后再开始下一步。')
        instruction.setWordWrap(True)
        layout.addWidget(instruction)
        controls = QHBoxLayout()
        self.source = QComboBox()
        self.source.addItems(['ArduCopter4.6.3 MAVLink2 / rad/s','OPTICAL_FLOW_RAD / rad/s','OPTICAL_FLOW原始整数 / dpix(协议)'])
        self.source.setToolTip('为本轮方向测试选择已确认的来源和单位；dpix不能与rad/s混用。完整分步测试可使用“地面检查”页。')
        self.title.setToolTip('显示当前使用的光流消息与单位。实时数据过期显示 N/A；质量不是准确率。')
        controls.addWidget(self.source)
        self.capture_button = QPushButton('开始：向机头方向平移')
        self.capture_button.clicked.connect(self.begin)
        self.capture_button.setToolTip('仅拆桨、DISARMED、近水平且不旋转时采样；每个方向3秒，质量低于本地阈值的样本不用于方向结论。')
        controls.addWidget(self.capture_button)
        reset = QPushButton('重新测试')
        reset.clicked.connect(self.reset)
        controls.addWidget(reset)
        layout.addLayout(controls)
        quality_controls = QHBoxLayout()
        quality_controls.addWidget(QLabel('动作采样质量门限（1–255）：'))
        self.quality_min = QSpinBox()
        self.quality_min.setRange(1, 255)
        self.quality_min.setValue(config.CAPTURE_QUALITY_MIN)
        self.quality_min.setToolTip('只影响本页地面采样。整轮使用同一门限；要更改请重新测试。质量0不参与方向判断。')
        quality_controls.addWidget(self.quality_min)
        quality_note = QLabel('默认30供排查；质量不是百分制，降低门限不代表光流可靠。')
        quality_note.setWordWrap(True)
        quality_controls.addWidget(quality_note, 1)
        layout.addLayout(quality_controls)
        self.result = QLabel('方向结论：Insufficient Data')
        self.result.setWordWrap(True)
        layout.addWidget(self.result)
        self.store, self.armed = None, None
        self.reset()

    def reset(self):
        self.captures = {}
        self.capture_summaries = []
        self.step = 0
        self.capture_start = None
        self.capture_button.setText('开始：向机头方向平移')
        self.capture_button.setEnabled(True)
        self.source.setEnabled(True)
        self.quality_min.setEnabled(True)
        self.result.setText('方向结论：Insufficient Data')

    def begin(self):
        if self.armed is not False:
            self.result.setText('仅限已确认 DISARMED，不能在状态未知时执行搬动测试。')
            return
        self.capture_start = time.monotonic()
        self.capture_button.setEnabled(False)
        self.source.setEnabled(False)
        self.quality_min.setEnabled(False)
        self.invalid = {}

    def update_data(self, store, now, armed):
        self.store, self.armed = store, armed
        prefix, unit = store.flow_source(now)
        self.title.setText(f'MTF02P · 当前光流来源 {prefix} / {unit} · sensor_id={config.FLOW_SENSOR_ID}')
        for row,(name,label) in enumerate([(prefix+'_x','Flow X'),(prefix+'_y','Flow Y'),(prefix+'_quality','Quality 0..255'),('range','Range / m')]):
            cell(self.table,row,0,label)
            for column,value in enumerate([store.get(name,now)]+store.stats(name,now),1):
                cell(self.table,row,column,number(value))
        self.health.setText(store.static_warning(now,armed))
        self.plot.update_data(store,now)
        if self.capture_start is not None:
            self.invalid.update(motion_errors(store, now))
            if armed is not False:
                self.invalid['armed'] = '飞控未保持 DISARMED'
            source = ['flow_rate','flow_rad','flow_raw'][self.source.currentIndex()]
            for field in ('x', 'y', 'quality'):
                if store.get(source+'_'+field, now) is None:
                    self.invalid[field] = f'所选来源 {source} 的 {field} 数据缺失或过期'
            remaining = config.DIRECTION_CAPTURE_S - (now-self.capture_start)
            issue = '；已触发：'+'；'.join(self.invalid.values()) if self.invalid else ''
            self.result.setText(f'{DIRECTIONS[self.step][1]} · 剩余 {max(0,remaining):.1f} 秒'+issue)
            if remaining <= 0:
                source = ['flow_rate','flow_rad','flow_raw'][self.source.currentIndex()]
                xs = store.window(source+'_x',now,config.DIRECTION_CAPTURE_S)
                ys = dict(store.window(source+'_y',now,config.DIRECTION_CAPTURE_S))
                qs = dict(store.window(source+'_quality',now,config.DIRECTION_CAPTURE_S))
                samples, summary = filter_capture(xs, ys, qs, self.quality_min.value())
                self.capture_start = None
                self.capture_button.setEnabled(True)
                if self.invalid or len(samples) < config.DIRECTION_MIN_SAMPLES:
                    reasons = list(self.invalid.values())
                    if len(samples) < config.DIRECTION_MIN_SAMPLES:
                        reasons.append('筛选后样本不足；检查质量、消息频率与所选来源')
                    self.result.setText('本次无效：'+'；'.join(reasons)+'。\n'+summary+'\n请重做此步；更改门限需点击“重新测试”。')
                    return
                self.captures[DIRECTIONS[self.step][0]] = samples
                self.capture_summaries.append(DIRECTIONS[self.step][1]+'：'+summary)
                self.step += 1
                if self.step == len(DIRECTIONS):
                    self.result.setText(evaluate_direction(self.captures,'dpix' if source == 'flow_raw' else 'rad/s')+'\n'+'\n'.join(self.capture_summaries))
                    self.capture_button.setEnabled(False)
                else:
                    self.capture_button.setText('开始：'+DIRECTIONS[self.step][1])
                    self.result.setText('已保存本步。停止移动，准备下一步。\n'+summary)
