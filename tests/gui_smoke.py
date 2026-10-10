"""真实 Qt 事件循环验收：后台解析BIN、运行诊断、移动游标、检查响应并截图。"""
import os
os.environ.setdefault('MAVLINK20','1')
os.environ.setdefault('PYQTGRAPH_QT_LIB','PySide6')
import json
import sys
import time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest
from PySide6.QtCore import Qt,QPointF
import pyqtgraph as pg
from gui.main_window import MainWindow
import config

def main():
    app = QApplication([])
    pg.setConfigOptions(background='#111d29',foreground='#c9dae9')
    window = MainWindow()
    window.show()
    output = Path('F:/codex_pro/work/ardupilot_analyzer')
    output.mkdir(parents=True,exist_ok=True)
    status = {'timer_ticks':0,'maximum_tick_gap_s':0.,'errors':[],'complete':False}
    previous = time.monotonic()
    stage = 0
    start = previous
    def exception_hook(kind,error,traceback):
        status['errors'].append(str(error))
        sys.__excepthook__(kind,error,traceback)
    sys.excepthook = exception_hook
    def poll():
        nonlocal previous,stage
        now = time.monotonic()
        status['timer_ticks'] += 1
        status['maximum_tick_gap_s'] = max(status['maximum_tick_gap_s'],now-previous)
        previous = now
        page = window.diagnosis_page
        if stage == 0:
            window.open_bin(str(config.LOG_DIR/'log_0011.BIN'))
            stage = 1
        elif stage == 1 and page.dataset is not None:
            plot = page.plots.plots[0]
            plot.setXRange(2,16,padding=0)
            point = plot.mapFromScene(plot.plotItem.vb.mapViewToScene(QPointF(5.444,0)))
            QTest.mouseClick(plot.viewport(),Qt.MouseButton.LeftButton,pos=point)
            status['plot_mouse_click_works'] = 5.2 < page.plots.current_time < 5.7
            page.plots.set_cursor(5.444)
            status['cursor_details_present'] = '5.444' in window.cursor_details.toPlainText()
            page.plots.plots[0].setXRange(2,16,padding=0)
            stage = 2
        elif stage == 2:
            window.grab().save(str(output/'timeline.png'))
            status['linked_ranges'] = [plot.viewRange()[0] for plot in page.plots.plots]
            status['ranges_linked'] = all(abs(bounds[0]-2)<0.00001 and abs(bounds[1]-16)<0.00001 for bounds in status['linked_ranges'])
            QTest.mouseClick(page.diagnose_button,Qt.MouseButton.LeftButton)
            stage = 3
        elif stage == 3 and page.report is not None:
            window.grab().save(str(output/'diagnosis.png'))
            for extension in ('txt','csv','html'):
                page.report.export(config.DATA_DIR/f'log_0011.diagnosis.{extension}')
            status['events'] = len(page.report.events)
            status['complete'] = True
            stage = 4
            window.close()
        if now-start>40:
            status['errors'].append('GUI验收超时')
            window.close()
    timer = QTimer()
    timer.timeout.connect(poll)
    timer.start(100)
    app.exec()
    status['threads_running_after_close'] = any(job.isRunning() for job in window.jobs)
    (output/'gui_smoke.json').write_text(json.dumps(status,indent=2),encoding='utf-8')
    print(json.dumps(status))
    return 0 if status['complete'] and not status['errors'] and not status['threads_running_after_close'] and status['maximum_tick_gap_s']<1.0 and status['ranges_linked'] and status['plot_mouse_click_works'] else 1

if __name__ == '__main__':
    sys.exit(main())
