"""共享X轴与游标，保留原始样本；事件导航和峰值降采样只影响显示。"""
import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Signal, Qt
from PySide6.QtWidgets import QWidget,QVBoxLayout,QHBoxLayout,QGridLayout,QPushButton,QScrollArea,QCheckBox,QLabel,QComboBox,QDoubleSpinBox
from gui.help_text import signal_help,tooltip,help_for
from analysis.timeline_events import active_bounds
import config

GROUPS = [('Optical Flow / rad/s',['flow_x','flow_y']),('Quality / 0..255',['quality']),
          ('光流融合一致性 / NI÷100（已核对版本）',['flow_test_ratio']),
          ('RangeFinder / m',['range']),('测距状态 / 4=Good',['range_status']),('EKF Velocity / NED m/s',['vx','vy','vz']),
          ('横滚与俯仰 / deg',['roll','pitch','desired_roll','desired_pitch']),('航向 / deg',['yaw','desired_yaw']),
          ('Vibration / m/s²',['vibe_x','vibe_y','vibe_z']),('RC Input / us',['rc1','rc2']),
          ('Motor / Servo Outputs',['out'+str(i) for i in range(1,17)]),('解锁状态 / 0锁定 1解锁',['armed']),('Flight Mode / Copter',['mode'])]
COLORS = ['#48d7c1','#ffb454','#a898ff','#5aaaff','#ed86b3','#dfda7d']
MODE_NAMES = {0:'STABILIZE',1:'ACRO',2:'ALT_HOLD',3:'AUTO',4:'GUIDED',5:'LOITER',6:'RTL',7:'CIRCLE',9:'LAND',16:'POSHOLD',17:'BRAKE',20:'GUIDED_NOGPS'}

class TimelinePlots(QWidget):
    cursor_changed = Signal(float)
    def __init__(self):
        super().__init__()
        self.signals = {}
        self.plots = []
        self.curves = {}
        self.captions=[]
        self.lines = []
        self.proxies = []
        self.current_time = 0.0
        self.events = []
        self.event_items = []
        self.updating = False
        layout = QVBoxLayout(self)
        controls = QHBoxLayout()
        self.readout = QLabel('时间游标: N/A')
        controls.addWidget(self.readout)
        auto = QPushButton('自动缩放Y')
        auto.clicked.connect(self.auto_y)
        controls.addWidget(auto)
        reset = QPushButton('恢复全局视图')
        reset.clicked.connect(self.reset_view)
        controls.addWidget(reset)
        layout.addLayout(controls)
        navigation=QHBoxLayout()
        for label,direction in [('上一事件',-1),('下一事件',1)]:
            button=QPushButton(label)
            button.setToolTip(tooltip(help_for(label)))
            button.clicked.connect(lambda checked=False,d=direction:self.next_event(d))
            navigation.addWidget(button)
        self.event_select=QComboBox()
        self.event_select.setMinimumContentsLength(18)
        self.event_select.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.event_select.setToolTip('全程事件列表；选择后跳转到前后8秒。曲线上只标注当前视野内的一部分事件，完整事件保留在此列表。')
        self.event_select.activated.connect(self.select_event)
        navigation.addWidget(self.event_select,1)
        self.seconds=QDoubleSpinBox()
        self.seconds.setDecimals(3);self.seconds.setRange(0,1e8);self.seconds.setSuffix(' s')
        self.seconds.setToolTip('输入日志相对秒数，按回车跳转；不是电脑时钟。')
        self.seconds.editingFinished.connect(lambda:self.focus_time(self.seconds.value()))
        navigation.addWidget(self.seconds)
        layout.addLayout(navigation)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self.container = QWidget()
        self.stack = QVBoxLayout(self.container)
        scroll.setWidget(self.container)
        layout.addWidget(scroll)
        for group_index,(title,keys) in enumerate(GROUPS):
            box = QWidget()
            box_layout = QVBoxLayout(box)
            toggles = QGridLayout()
            caption = QLabel(title)
            caption.setToolTip(tooltip('；'.join(signal_help(key) for key in keys[:4])))
            self.captions.append(caption)
            caption.setMaximumHeight(24)
            toggles.addWidget(caption,0,0,1,8)
            plot = pg.PlotWidget()
            plot.setMinimumHeight(170)
            plot.setMaximumHeight(210)
            plot.setLabel('bottom','统一时间',units='s')
            plot.getAxis('bottom').enableAutoSIPrefix(False)
            plot.getAxis('left').setWidth(80)
            plot.showGrid(x=True,y=True,alpha=0.15)
            plot.setClipToView(True)
            plot.setDownsampling(auto=True,mode='peak')
            plot.addLegend(offset=(6,4))
            if self.plots:
                plot.setXLink(self.plots[0])
            self.plots.append(plot)
            for index,key in enumerate(keys):
                curve = plot.plot(name=key,pen=pg.mkPen(COLORS[index%len(COLORS)],width=1.5),connect='finite')
                check = QCheckBox(key)
                check.setToolTip(tooltip(signal_help(key)))
                curve.setToolTip(tooltip(signal_help(key)))
                check.setChecked(index<4)
                curve.setVisible(index<4)
                check.toggled.connect(curve.setVisible)
                toggles.addWidget(check,1+index//8,index%8)
                self.curves[key] = curve
            box_layout.addLayout(toggles)
            box_layout.addWidget(plot)
            self.stack.addWidget(box)
            vertical = pg.InfiniteLine(angle=90,movable=True,pen=pg.mkPen('#f0cc79',width=1))
            horizontal = pg.InfiniteLine(angle=0,movable=False,pen=pg.mkPen('#657789',style=Qt.PenStyle.DotLine))
            plot.addItem(vertical,ignoreBounds=True)
            plot.addItem(horizontal,ignoreBounds=True)
            self.lines.append(vertical)
            vertical.sigPositionChanged.connect(lambda line:self.set_cursor(float(line.value())))
            plot.scene().sigMouseClicked.connect(lambda event,p=plot:self.clicked(event,p))
            self.proxies.append(pg.SignalProxy(plot.scene().sigMouseMoved,rateLimit=20,
                slot=lambda args,p=plot,h=horizontal:self.hover(args,p,h)))
        self.updating = False
        self.plots[0].sigXRangeChanged.connect(lambda *args:self.draw_events())
        for button in (auto,reset):button.setToolTip(tooltip(help_for(button.text())))
        self.readout.setToolTip('游标是选中的历史时刻；鼠标坐标只是光标位置，不是实际样本。点击或拖动金色线查看右侧历史读数。')
        self.threshold=pg.InfiniteLine(pos=1,angle=0,pen=pg.mkPen('#f08b79',style=Qt.PenStyle.DashLine))
        self.plots[2].addItem(self.threshold,ignoreBounds=True)

    def set_signals(self,signals):
        self.signals = signals
        self.events=[]
        self.event_select.clear()
        self.threshold.setVisible('flow_test_ratio' in signals)
        for caption,(title,keys) in zip(self.captions,GROUPS):
            caption.setText(title+('' if any(key in signals for key in keys) else ' · 无可用数据/定义未确认'))
        end_time = active_bounds(signals)[1]
        for key,curve in self.curves.items():
            series = signals.get(key)
            if series is None:
                curve.setData([],[])
                continue
            if series.discrete:
                mask=series.time<=end_time
                if not mask.any():curve.setData([],[]);continue
                times = np.r_[series.time[mask],end_time]
                values = np.r_[series.value[mask],series.value[mask][-1]]
                x = np.repeat(times,2)[1:]
                y = np.repeat(values,2)[:-1]
                curve.setData(x,y)
            else:
                gaps = np.flatnonzero(np.diff(series.time)>config.STALE_S)+1
                curve.setData(np.insert(series.time,gaps,np.nan),np.insert(series.value,gaps,np.nan))
        if 'mode' in signals:
            self.plots[-1].getAxis('left').setTicks([[(value,MODE_NAMES.get(int(value),str(int(value)))) for value in np.unique(signals['mode'].value) if np.isfinite(value)]])
        self.reset_view()
        self.set_cursor(0)
        self.draw_events()

    def set_events(self,events):
        self.events=events
        self.event_select.clear()
        for event in events:
            self.event_select.addItem(f'{event.time_s:.3f}s · {event.category} · {event.label}')
            self.event_select.setItemData(self.event_select.count()-1,tooltip(event.evidence),Qt.ItemDataRole.ToolTipRole)
        self.draw_events()

    def draw_events(self):
        if not self.plots:return
        plot=self.plots[0]
        for item in self.event_items:plot.removeItem(item)
        self.event_items=[]
        low,high=plot.viewRange()[0]
        visible=[event for event in self.events if low<=event.time_s<=high]
        for index,event in enumerate(visible[:40]):
            color='#e77e79' if event.category in ('急停','碰撞检测') else '#869ec3'
            marker=pg.InfiniteLine(pos=event.time_s,angle=90,movable=False,pen=pg.mkPen(color,style=Qt.PenStyle.DotLine))
            marker.setToolTip(tooltip(f'{event.time_s:.3f}s {event.label}\n{event.evidence}'))
            plot.addItem(marker,ignoreBounds=True);self.event_items.append(marker)
        self.event_select.setToolTip(f'当前视野内 {len(visible)} 个事件，曲线最多标记40个；完整列表 {len(self.events)} 个。选择事件后定位前后8秒。')

    def select_event(self,index):
        if 0<=index<len(self.events):self.focus_time(self.events[index].time_s)

    def next_event(self,direction):
        candidates=[(i,e) for i,e in enumerate(self.events) if (e.time_s-self.current_time)*direction>1e-6]
        if candidates:
            index,event=candidates[0] if direction>0 else candidates[-1]
            self.event_select.setCurrentIndex(index);self.focus_time(event.time_s)

    def focus_time(self,timestamp):
        self.set_cursor(timestamp)
        self.plots[0].setXRange(max(0,timestamp-8),timestamp+8,padding=0)
        self.auto_y()

    def clicked(self,event,plot):
        if event.button() == Qt.MouseButton.LeftButton and plot.plotItem.vb.sceneBoundingRect().contains(event.scenePos()):
            self.set_cursor(plot.plotItem.vb.mapSceneToView(event.scenePos()).x())

    def hover(self,args,plot,horizontal):
        position = args[0]
        if plot.plotItem.vb.sceneBoundingRect().contains(position):
            point = plot.plotItem.vb.mapSceneToView(position)
            horizontal.setPos(point.y())
            self.readout.setText(f'游标 {self.current_time:.3f} s · 鼠标 t={point.x():.3f} s / y={point.y():.4g}')

    def set_cursor(self,timestamp):
        if self.updating:
            return
        self.updating = True
        self.current_time = max(0,float(timestamp))
        self.seconds.setValue(self.current_time)
        for line in self.lines:
            line.setPos(self.current_time)
        self.readout.setText(f'时间游标: {self.current_time:.3f} s')
        self.updating = False
        self.cursor_changed.emit(self.current_time)

    def auto_y(self):
        for plot in self.plots:
            plot.getViewBox().setAutoVisible(y=True)
            plot.enableAutoRange(axis='y',enable=True)

    def reset_view(self):
        if self.signals:
            low,high = active_bounds(self.signals)
            self.plots[0].setXRange(low,max(high,low+1),padding=0.015)
        self.auto_y()
