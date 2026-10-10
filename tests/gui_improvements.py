"""对真实日志12的离线GUI验收；不连接串口，不操作运行中的另一实例。"""
import os
os.environ.setdefault('MAVLINK20','1')
os.environ.setdefault('PYQTGRAPH_QT_LIB','PySide6')
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import json
import sys
import time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QTimer,QEvent,Qt
from PySide6.QtGui import QFontDatabase,QFont,QHelpEvent
from PySide6.QtWidgets import QApplication,QToolTip
import pyqtgraph as pg
from gui.main_window import MainWindow
import config

def main():
    app=QApplication([])
    for name in ('msyh.ttc','msyhbd.ttc','segoeui.ttf'):
        path=Path(os.environ.get('WINDIR','C:/Windows'))/'Fonts'/name
        if path.exists():QFontDatabase.addApplicationFont(str(path))
    app.setFont(QFont('Microsoft YaHei',10))
    pg.setConfigOptions(background='#111d29',foreground='#c9dae9')
    out=config.DATA_DIR/'upgrade_validation';out.mkdir(exist_ok=True)
    window=MainWindow();window.show()
    status={'errors':[],'checks':{},'maximum_tick_gap_s':0,'complete':False}
    oldhook=sys.excepthook
    def hook(kind,error,tb):status['errors'].append(str(error));oldhook(kind,error,tb)
    sys.excepthook=hook
    started=previous=time.monotonic();stage=0
    def check(key,value):status['checks'][key]=bool(value)
    def poll():
        nonlocal previous,stage
        now=time.monotonic();status['maximum_tick_gap_s']=max(status['maximum_tick_gap_s'],now-previous);previous=now
        page=window.diagnosis_page
        if stage==0:
            window.open_bin(str(config.LOG_DIR/'log_0012.BIN'));stage=1
        elif stage==1 and page.dataset is not None:
            check('full_signal_mapping',all(k in page.plots.curves and len(page.plots.curves[k].getData()[0])>0 for k in ('flow_x','flow_y','roll','pitch','desired_pitch','flow_test_ratio')))
            check('seconds_without_ks',not page.plots.plots[0].getAxis('bottom').autoSIPrefix)
            check('plot_excludes_status_tail',page.plots.plots[0].viewRange()[0][1]<310)
            check('target_pitch_visible',page.plots.curves['desired_pitch'].isVisible())
            check('yaw_separate',page.plots.curves['yaw'].getViewBox()!=page.plots.curves['pitch'].getViewBox())
            event=next(e for e in page.plots.events if e.category=='目标姿态' and 93<e.time_s<94)
            page.plots.focus_time(event.time_s)
            check('history_label','历史 BIN 游标' in window.cursor_details.toPlainText())
            check('live_health_label','实时 MAVLink' in window.health.text())
            check('ground_start_guard',window.ground_page.started is None)
            window.ground_page.begin();check('disconnected_ground_cannot_start',window.ground_page.started is None)
            page.diagnose();stage=2
        elif stage==2 and page.report is not None:
            target=next(e for e in page.report.events if 78<e.time_s<79)
            check('late_loiter_covered',target.window_end>94)
            check('event_evidence_93s',any(e['category']=='目标姿态' and 93<e['time_s']<94 for e in page.report.timeline))
            check('innovation_warning',any('融合一致性' in f.check and f.status=='WARNING' for f in target.findings))
            status['timeline_events']=len(page.report.timeline)
            for extension in ('txt','csv','html'):page.report.export(out/('log_0012.full_diagnosis.'+extension))
            page.tabs.setCurrentWidget(page.plots)
            window.grab().save(str(out/'timeline.png'))
            window.tabs.setCurrentWidget(window.parameter_page)
            params=window.parameter_page;params.search.setText('FLOW')
            row=params.names.index('FLOW_ORIENT_YAW')
            check('log_parameter_loaded',params.table.item(row,2).text()=='0.0')
            check('tooltip_units','0.01' in params.table.item(row,0).toolTip())
            check('value_cell_help','0.01' in params.table.item(row,2).toolTip())
            params.set_connected(True);params.set_value('FLOW_ORIENT_YAW',9000)
            check('parameter_difference',params.table.item(row,3).text()=='数值不同')
            params.set_connected(False)
            check('disconnected_snapshot_marked','连接已断开' in params.table.item(row,3).text())
            # 合成值仅用于UI测试，清空后才保存用户可见截图。
            params.reset()
            params.table.scrollToItem(params.table.item(row,0))
            stage=3
        elif stage==3:
            params=window.parameter_page
            row=params.names.index('FLOW_ORIENT_YAW');item=params.table.item(row,0)
            pos=params.table.visualItemRect(item).center()
            event=QHelpEvent(QEvent.Type.ToolTip,pos,params.table.viewport().mapToGlobal(pos))
            QApplication.sendEvent(params.table.viewport(),event)
            check('native_tooltip_shown','0.01' in QToolTip.text())
            window.grab().save(str(out/'parameters.png'))
            for widget in app.topLevelWidgets():
                if widget.isVisible() and widget.windowType()==Qt.WindowType.ToolTip:widget.grab().save(str(out/'tooltip.png'))
            QToolTip.hideText()
            window.tabs.setCurrentWidget(window.ground_page)
            stage=4
        elif stage==4:
            window.grab().save(str(out/'ground_check.png'))
            status['complete']=True;window.close();stage=5
        if now-started>60:status['errors'].append('GUI验收超时');window.close()
    timer=QTimer();timer.timeout.connect(poll);timer.start(100)
    app.exec()
    check('threads_stopped',not any(job.isRunning() for job in window.jobs))
    (out/'validation.json').write_text(json.dumps(status,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(status,ensure_ascii=False))
    return 0 if status['complete'] and not status['errors'] and all(status['checks'].values()) and status['maximum_tick_gap_s']<1 else 1

if __name__=='__main__':sys.exit(main())
