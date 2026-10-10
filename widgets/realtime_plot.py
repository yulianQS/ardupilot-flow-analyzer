from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel
import numpy as np
import pyqtgraph as pg
import config

class RealtimePlot(QWidget):
    def __init__(self, title='实时趋势', fields=None):
        super().__init__()
        layout = QVBoxLayout(self)
        self.caption = QLabel(title)
        layout.addWidget(self.caption)
        self.plot = pg.PlotWidget()
        self.plot.setLabel('bottom', '连接后时间', units='s')
        self.plot.showGrid(x=True, y=True, alpha=0.18)
        self.plot.addLegend()
        self.fields = fields or ['roll','pitch']
        self.curves = {field:self.plot.plot(name=field, pen=pg.mkPen(color,width=1.7), connect='finite')
                       for field,color in zip(self.fields,['#42cfbd','#ffb454','#c79df8','#69b4ff'])}
        layout.addWidget(self.plot)

    def update_data(self, store, now):
        for field, curve in self.curves.items():
            samples = list(store.history.get(field, ()))
            if samples and store.start is not None:
                data = np.asarray(samples, dtype=float)
                # 空洞插入 NaN，断流处不画虚假的连续轨迹。
                gaps = np.flatnonzero(np.diff(data[:,0]) > config.STALE_S) + 1
                x = np.insert(data[:,0]-store.start, gaps, np.nan)
                y = np.insert(data[:,1], gaps, np.nan)
                curve.setData(x, y)
            else:
                curve.setData([], [])
