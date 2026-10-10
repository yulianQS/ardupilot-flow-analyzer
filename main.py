"""Windows 入口；--smoke-seconds 用于启动验证，不连接硬件、不产生模拟遥测。"""
import argparse
import logging
from logging.handlers import RotatingFileHandler
import sys
import os
os.environ.setdefault('MAVLINK20', '1')
os.environ.setdefault('PYQTGRAPH_QT_LIB', 'PySide6')
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QTimer
import pyqtgraph as pg
import config
from gui.main_window import MainWindow

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--smoke-seconds',type=float,default=0)
    parser.add_argument('--screenshot',default='')
    parser.add_argument('--connect',default='',help='显式连接串口；普通启动不自动打开串口')
    parser.add_argument('--bin',default='',help='启动时打开本地BIN')
    arguments = parser.parse_args()
    handler = RotatingFileHandler(config.ROOT/'app.log',maxBytes=2_000_000,backupCount=3,encoding='utf-8')
    logging.basicConfig(level=logging.INFO,handlers=[handler],format='%(asctime)s %(levelname)s %(message)s')
    logging.info('应用启动')
    app = QApplication(sys.argv[:1])
    app.setApplicationName('ArduPilot Optical Flow Analyzer')
    pg.setConfigOptions(antialias=False,background='#111d29',foreground='#c9dae9')
    window = MainWindow()
    def report_exception(kind,error,traceback):
        logging.error('GUI未处理异常',exc_info=(kind,error,traceback))
        window.show_error(f'{kind.__name__}: {error}（详情见app.log）')
    sys.excepthook = report_exception
    window.show()
    if arguments.connect:
        QTimer.singleShot(500,lambda:window.connect_vehicle(arguments.connect,config.BAUD))
    if arguments.bin:
        QTimer.singleShot(600,lambda:window.open_bin(arguments.bin))
    if arguments.screenshot:
        QTimer.singleShot(2500,lambda:window.grab().save(arguments.screenshot))
    if arguments.smoke_seconds:
        QTimer.singleShot(int(arguments.smoke_seconds*1000),window.close)
    return app.exec()

if __name__ == '__main__':
    sys.exit(main())
