from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel
from widgets.realtime_plot import RealtimePlot
from analysis.rangefinder import range_health

class RangeFinderPage(QWidget):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        self.value = QLabel('RangeFinder: N/A cm / N/A m')
        self.value.setObjectName('bigValue')
        layout.addWidget(self.value)
        self.health = QLabel('No Data')
        layout.addWidget(self.health)
        self.plot = RealtimePlot('朝下 DISTANCE_SENSOR · m', ['range'])
        layout.addWidget(self.plot)

    def update_data(self,store,now):
        value = store.get('range',now)
        self.value.setText('RangeFinder: N/A cm / N/A m' if value is None else f'RangeFinder: {value*100:.1f} cm  /  {value:.3f} m')
        self.health.setText(range_health(store,now) + f' · sensor id={store.handler.range_id}')
        self.plot.update_data(store,now)
