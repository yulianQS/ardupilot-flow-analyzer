"""从日志提取事件及局部证据；阈值事件只表示观测，不能作为物理根因。"""
from dataclasses import dataclass
import re
import numpy as np
import config

MODE_NAMES={0:'STABILIZE',1:'ACRO',2:'ALT_HOLD',3:'AUTO',4:'GUIDED',5:'LOITER',6:'RTL',9:'LAND',16:'POSHOLD',17:'BRAKE'}

@dataclass
class TimelineEvent:
    time_s: float
    category: str
    label: str
    evidence: str = ''

def supports_flow_ratio(dataset):
    frame=dataset.frames.get('MSG')
    return frame is not None and 'Message' in frame and any(re.search(r'ArduCopter\s+V?4\.6\.3(?:\s|\(|$)',str(x)) for x in frame.Message)

def active_bounds(signals):
    continuous=[s for s in signals.values() if not s.discrete and len(s.time) and np.any(np.isfinite(s.value))]
    if not continuous:
        available=[s for s in signals.values() if len(s.time)]
        return (min(float(s.time[0]) for s in available),max(float(s.time[-1]) for s in available)) if available else (0.,1.)
    return min(float(s.time[0]) for s in continuous),max(float(s.time[-1]) for s in continuous)

def _starts(series,mask):
    """只返回连续异常段起点；不跨记录缺口。"""
    previous=np.r_[False,mask[:-1]]
    gap=np.r_[True,np.diff(series.time)>config.STALE_S]
    return np.flatnonzero(mask & (~previous | gap))

def extract_events(dataset,signals=None,cancelled=lambda:False):
    signals=dataset.signals() if signals is None else signals
    events=[]
    for key,category in [('mode','模式'),('armed','解锁状态')]:
        s=signals.get(key)
        if s is None:continue
        previous=None
        for t,value in zip(s.time,s.value):
            if np.isfinite(value) and value!=previous:
                label=MODE_NAMES.get(int(value),f'模式 {int(value)}') if key=='mode' else ('ARMED 解锁' if value==1 else 'DISARMED 锁定')
                events.append(TimelineEvent(float(t),category,label,s.source))
                previous=value
    msgs=dataset.frames.get('MSG')
    last={}
    if msgs is not None and 'Message' in msgs:
        for row in msgs.itertuples():
            if cancelled():raise InterruptedError('诊断已取消')
            text=str(row.Message)
            if not any(x in text.lower() for x in ('motorestop','crash','fusing optical flow','stopped aiding','relative aiding','prearm:')):continue
            # 重复PreArm会延续数十分钟；仅显示该文字首次或间隔超过60秒的记录。
            if text in last and (text.startswith('PreArm:') or row.t-last[text]<5):continue
            last[text]=row.t
            category='急停' if 'MotorEStop' in text else ('碰撞检测' if 'Crash' in text else ('解锁检查' if 'PreArm:' in text else '融合'))
            events.append(TimelineEvent(float(row.t),category,text,'MSG.Message；文字事件不等于已证明物理根因'))
    # 编号已核对 Copter-4.6.3/AP_Logger.h；飞控判定不等于独立物理验证。
    ev=dataset.frames.get('EV')
    if ev is not None and 'Id' in ev and supports_flow_ratio(dataset):
        meanings={17:('落地判定','可能已落地'),18:('落地判定','LAND_COMPLETE 飞控判定已落地'),
                  28:('离地判定','NOT_LANDED 飞控判定未落地'),
                  54:('急停','电机急停事件 EV54'),55:('急停','电机急停解除 EV55'),
                  60:('估计重置','EKF 高度重置'),62:('估计重置','EKF 航向重置'),
                  85:('数据源切换','切换至源组1'),86:('数据源切换','切换至源组2'),87:('数据源切换','切换至源组3')}
        for row in ev.itertuples():
            if row.Id in meanings:
                category,label=meanings[row.Id]
                events.append(TimelineEvent(float(row.t),category,label,f'EV.Id={row.Id}；固件判定，需与实际操作核对'))
    errors=dataset.frames.get('ERR')
    if errors is not None and 'Subsys' in errors and 'ECode' in errors:
        for row in errors.itertuples():
            events.append(TimelineEvent(float(row.t),'错误记录',f'ERR 子系统{row.Subsys} / 代码{row.ECode}','原始错误记录；枚举含义需结合固件及同刻MSG核对'))
    checks=[('vx',config.EKF_SPEED_HIGH_M_S,'速度异常','北向估计速度超过本地阈值'),('vy',config.EKF_SPEED_HIGH_M_S,'速度异常','东向估计速度超过本地阈值'),
            ('desired_roll',config.ATTITUDE_HIGH_DEG,'目标姿态','目标横滚超过本地阈值'),('desired_pitch',config.ATTITUDE_HIGH_DEG,'目标姿态','目标俯仰超过本地阈值')]
    if 'flow_test_ratio' in signals:checks.append(('flow_test_ratio',1.,'融合检查','光流一致性比值达到边界'))
    for key,threshold,category,label in checks:
        s=signals.get(key)
        if s is None:continue
        mask=np.isfinite(s.value)&(np.abs(s.value)>=threshold)
        last_time=-np.inf
        for i in _starts(s,mask):
            if s.time[i]-last_time<2:continue
            last_time=s.time[i]
            events.append(TimelineEvent(float(s.time[i]),category,label,f'{s.source}={s.value[i]:.4g} {s.unit}；阈值 {threshold:g}；非真实速度或根因证明'))
    return sorted(events,key=lambda e:e.time_s)

def event_evidence(dataset,signals,event):
    """每个事件独立对齐，不拿后续撞击峰值解释此前原因。"""
    t=event.time_s
    values={key:s.at(t) for key,s in signals.items()}
    lines=[event.evidence]
    for key in ('mode','armed','range','range_status','quality','vx','vy','desired_roll','roll','desired_pitch','pitch','flow_test_ratio'):
        if key in signals:
            value=values[key]
            lines.append(f'{key}='+('N/A' if value is None else f'{value:.4g} {signals[key].unit}'))
    if event.category=='目标姿态':
        for axis in ('ROLL','PITCH'):
            channel=dataset.param_at('RCMAP_'+axis,t)
            if channel is None:lines.append(f'{axis} 输入映射缺失');continue
            channel=int(channel);trim=dataset.param_at(f'RC{channel}_TRIM',t)
            s=signals.get(f'rc{channel}');value=s.at(t) if s else None
            lines.append(f'{axis}: RC{channel}={value}, trim={trim}；'+('此刻接近中位' if value is not None and 0<value<65535 and trim is not None and abs(value-trim)<=config.RC_DEADBAND_US else '中位条件未确认'))
    return '；'.join(lines)
