"""真实串口只读验收：显式运行，不被 unittest 自动发现。不会解锁或修改参数。"""
import argparse
import json
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QCoreApplication, QTimer
from mavlink.connection import ConnectionWorker
import config

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--port',default='COM15')
    parser.add_argument('--seconds',type=int,default=20)
    parser.add_argument('--output',required=True)
    parser.add_argument('--download-id',type=int)
    options = parser.parse_args()
    app = QCoreApplication([])
    worker = ConnectionWorker(options.port)
    result = {'states':[], 'messages':{}, 'parameters':{}, 'logs':[], 'errors':[], 'notices':[]}
    started = False
    downloading = False
    def state(name,info):
        nonlocal started
        result['states'].append({'state':name,**info})
        if name == 'CONNECTED' and not started:
            started = True
            worker.request('record',True)
            if info.get('armed') is False:
                worker.request('logs')
    def receive(batch):
        for timestamp,kind,data in batch:
            result['messages'][kind] = data
    def logs(entries):
        nonlocal downloading
        result['logs'] = entries
        if options.download_id is not None and not downloading:
            for entry in entries:
                if entry['id'] == options.download_id:
                    worker.request('download',entry)
                    downloading = True
    worker.state.connect(state)
    worker.messages.connect(receive)
    worker.parameters.connect(lambda name,value:result['parameters'].__setitem__(name,value))
    worker.logs.connect(logs)
    worker.error.connect(result['errors'].append)
    worker.notice.connect(result['notices'].append)
    worker.download_done.connect(lambda path:result.__setitem__('downloaded',path))
    worker.download_progress.connect(lambda data:result.__setitem__('download_progress',data))
    worker.finished.connect(app.quit)
    worker.start()
    QTimer.singleShot(options.seconds*1000,worker.stop)
    app.exec()
    worker.wait(2000)
    Path(options.output).write_text(json.dumps(result,indent=2,ensure_ascii=False,default=str),encoding='utf-8')
    print(json.dumps({'errors':result['errors'],'messages':list(result['messages']), 'logs':result['logs'],
                      'downloaded':result.get('downloaded')},ensure_ascii=True))

if __name__ == '__main__':
    main()
