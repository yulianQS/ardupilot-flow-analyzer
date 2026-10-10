"""DataFlash 解析完全交给 pymavlink；格式、倍率、动态 FMT 均由成熟解析器处理。

所有时序用 TimeUS / 1e6 或 TimeMS / 1000，再减全日志共同起点。
不把无时间戳消息伪装成 t=0。不同 EKF lane/传感器实例保留在原始表中。
"""
from collections import Counter, defaultdict
from dataclasses import dataclass, field
import logging
import time
from pathlib import Path
import numpy as np
import pandas as pd
from pymavlink import DFReader
from PySide6.QtCore import QThread, Signal
import config

@dataclass
class Series:
    time: np.ndarray
    value: np.ndarray
    unit: str
    source: str
    discrete: bool = False

    def at(self, timestamp, tolerance=config.CURSOR_TOLERANCE_S):
        if len(self.time) == 0:
            return None
        index = int(np.searchsorted(self.time,timestamp,side='right')-1)
        if self.discrete:
            return float(self.value[index]) if index >= 0 and np.isfinite(self.value[index]) else None
        candidates = [i for i in (index,index+1) if 0 <= i < len(self.time)]
        index = min(candidates,key=lambda i:abs(self.time[i]-timestamp))
        if abs(self.time[index]-timestamp) > tolerance or not np.isfinite(self.value[index]):
            return None
        return float(self.value[index])

@dataclass
class LogDataset:
    path: str
    frames: dict
    counts: dict
    duration: float
    origin: float
    warnings: list = field(default_factory=list)
    parameters: dict = field(default_factory=dict)

    def param_at(self, name, timestamp):
        frame = self.frames.get('PARM')
        if frame is None or 'Name' not in frame or 'Value' not in frame:
            return None
        rows = frame[(frame.Name == name) & (frame.t <= timestamp)]
        return float(rows.Value.iloc[-1]) if len(rows) else None

    def instances(self, kinds, columns=('C','Instance','I')):
        values = set()
        for kind in kinds:
            frame = self.frames.get(kind)
            if frame is not None:
                for column in columns:
                    if column in frame:
                        values.update(int(value) for value in frame[column].dropna().unique())
                        break
        return sorted(values) or [0]

    def signals(self, core=config.EKF_CORE, range_instance=config.RANGE_INSTANCE):
        result = {}
        def extract(key, kinds, columns, unit='', instance=None, discrete=False, multiplier=1):
            for kind in kinds:
                frame = self.frames.get(kind)
                if frame is None or frame.empty:
                    continue
                if instance is not None:
                    for field_name in ('C','Instance','I'):
                        if field_name in frame:
                            frame = frame[frame[field_name] == instance]
                            break
                if kind == 'RFND' and 'Orient' in frame:
                    frame = frame[frame.Orient == config.DOWNWARD_ORIENTATION]
                for column in columns:
                    if column not in frame or frame.empty:
                        continue
                    values = pd.to_numeric(frame[column],errors='coerce').to_numpy(dtype=float) * multiplier
                    times = frame.t.to_numpy(dtype=float)
                    valid = np.isfinite(times)
                    if not np.any(np.isfinite(values[valid])):
                        continue
                    result[key] = Series(times[valid],values[valid],unit,f'{kind}.{column}'+(f' [instance {instance}]' if instance is not None else ''),discrete)
                    return
        extract('flow_x',['OF'],['flowX','FlowX'],'rad/s',0)
        extract('flow_y',['OF'],['flowY','FlowY'],'rad/s',0)
        extract('body_x',['OF'],['bodyX','BodyX'],'rad/s',0)
        extract('body_y',['OF'],['bodyY','BodyY'],'rad/s',0)
        extract('quality',['OF'],['Qual','Q','Quality'],'0..255',0)
        extract('range',['RFND'],['Dist','Dist1'],'m',range_instance)
        extract('range_status',['RFND'],['Stat','Status'],'enum',range_instance)
        for key,field_name in [('vx','VN'),('vy','VE'),('vz','VD')]:
            extract(key,['XKF1','NKF1','XKF','NKF'],[field_name],'m/s',core)
        for axis in ('roll','pitch','yaw'):
            extract(axis,['ATT'],[axis.capitalize()],'deg')
            extract('desired_'+axis,['ATT'],['Des'+axis.capitalize()],'deg')
            extract('ekf_'+axis,['XKF1','NKF1'],[axis.capitalize()],'deg',core)
        for axis in 'xyz':
            extract('vibe_'+axis,['VIBE'],['Vibe'+axis.upper()],'m/s²',config.VIBE_INSTANCE)
            extract('gyro_'+axis,['IMU'],['Gyr'+axis.upper()],'rad/s',0)
        for i in range(1,17):
            extract(f'rc{i}',['RCIN'],[f'C{i}'],'us')
            extract(f'out{i}',['RCOU'],[f'C{i}'],'output units')
        extract('mode',['MODE'],['ModeNum','Mode'],'Copter mode',discrete=True)
        extract('armed',['ARM'],['ArmState'],'0/1',discrete=True)
        for key,column in [('ivn','IVN'),('ive','IVE'),('iyaw','IYAW')]:
            extract(key,['XKF3','NKF3'],[column],'deg' if key=='iyaw' else 'm/s',core)
        for key,column in [('sv','SV'),('sp','SP'),('sh','SH'),('sm','SM')]:
            extract(key,['XKF4','NKF4'],[column],'test ratio',core)
        extract('primary_core',['XKF4','NKF4'],['PI'],'core',core,True)
        for key,column in [('flow_innov_x','FIX'),('flow_innov_y','FIY'),('flow_norm','NI')]:
            extract(key,['XKF5','NKF5'],[column],'logged value',core)
        # 保留原始字段/API；只在已核对版本上新增归一化显示，未知版本不猜缩放。
        from analysis.timeline_events import supports_flow_ratio
        if supports_flow_ratio(self):
            extract('flow_test_ratio',['XKF5'],['NI'],'ratio (clipped 2.55)',core,multiplier=.01)
        return result

def parse_bin(path, progress=lambda value:None, cancelled=lambda:False):
    path = Path(path).resolve()
    if not path.is_file() or path.stat().st_size < 3:
        raise ValueError('BIN 文件不存在或为空')
    with path.open('rb') as file:
        if file.read(2) != b'\xa3\x95':
            raise ValueError('不是有效的 DataFlash BIN 文件（缺少 A3 95 文件头）')
    reader = None
    rows = defaultdict(list)
    counts = Counter()
    warnings = []
    records = 0
    last_percent = -1
    previous_time = None
    def index_progress(percent):
        if cancelled():
            raise InterruptedError('解析已取消')
        progress(int(percent*0.25))
    try:
        # 先保留对象引用，再初始化：构造中取消/损坏也能关闭mmap和filehandle。
        reader = DFReader.DFReader_binary.__new__(DFReader.DFReader_binary)
        reader.__init__(str(path),zero_time_base=True,progress_callback=index_progress)
        # reader 的构造步骤已扫描 FMT/类型索引，接下来仅保留实际存在的分析消息。
        selected = {'OF','RFND','ATT','IMU','VIBE','MODE','RCIN','RCOU','BARO','MAG','GPS','ERR','EV','MSG','PARM','ARM'}
        actual = {fmt.name for fmt in reader.formats.values()}
        selected |= {name for name in actual if name.startswith(('XKF','NKF'))}
        while True:
            if cancelled():
                raise InterruptedError('解析已取消')
            message = reader.recv_msg()
            if message is None:
                break
            kind = message.get_type()
            counts[kind] += 1
            records += 1
            if records % 1000 == 0:
                # CPython/GIL下显式让出执行权，让Qt主线程及时处理绘制和关闭事件。
                # 这不改变记录内容，只给大型日志的解析加约1ms/1000条的协作点。
                time.sleep(0.001)
            if records > config.MAX_PARSE_RECORDS:
                raise ValueError('日志记录数超过 config.MAX_PARSE_RECORDS；为避免内存耗尽已停止，请分段或调高限额。')
            data = message.to_dict()
            timestamp = data.get('TimeUS')
            timestamp = float(timestamp)/1e6 if timestamp is not None else (float(data['TimeMS'])/1000 if 'TimeMS' in data else None)
            if timestamp is not None:
                if previous_time is not None and timestamp < previous_time-1.0:
                    if '检测到时钟回退：可能跨重启或乱序，诊断时需人工核对时间轴。' not in warnings:
                        warnings.append('检测到时钟回退：可能跨重启或乱序，诊断时需人工核对时间轴。')
                previous_time = timestamp
            if kind in selected and timestamp is not None:
                data['t'] = timestamp
                rows[kind].append(data)
            percent = 25 + int(70*reader.offset/max(reader.data_len,1))
            if percent != last_percent:
                progress(percent)
                last_percent = percent
        if not rows:
            raise ValueError('BIN 中没有可用的带时间戳分析数据，文件可能损坏或格式不受支持')
        origin = min(row['t'] for values in rows.values() for row in values)
        frames = {}
        for kind,values in rows.items():
            if cancelled():
                raise InterruptedError('解析已取消')
            frame = pd.DataFrame.from_records(values)
            frame['t'] -= origin
            frames[kind] = frame.sort_values('t',kind='stable').reset_index(drop=True)
        duration = max(float(frame.t.max()) for frame in frames.values())
        remaining = reader.data_len-reader.offset
        if remaining > 0:
            warnings.append(f'解析结束仍有 {remaining} 字节未消费：可能尾包截断/损坏。')
        # 有格式错误时 pymavlink 可能跳过损坏数据；不声称所有文件均完好。
        warnings.append('解析成功不等于文件完整；下载完整性须以字节覆盖和文件大小校验为准。')
        parameters = {}
        if 'PARM' in frames and 'Name' in frames['PARM']:
            parameters = dict(zip(frames['PARM'].Name,frames['PARM'].Value))
        dataset = LogDataset(str(path),frames,dict(counts),duration,origin,warnings,parameters)
        progress(100)
        logging.info('BIN解析完成 %s records=%s types=%s',path,records,','.join(sorted(counts)))
        return dataset
    finally:
        if reader:
            for attribute in ('data_map','filehandle'):
                resource = getattr(reader,attribute,None)
                if resource is not None:
                    resource.close()

class ParserWorker(QThread):
    progress = Signal(int)
    result = Signal(object)
    error = Signal(str)
    def __init__(self,path):
        super().__init__()
        self.path = path
    def run(self):
        try:
            self.result.emit(parse_bin(self.path,self.progress.emit,self.isInterruptionRequested))
        except Exception as exception:
            logging.exception('BIN解析失败')
            self.error.emit(str(exception))
