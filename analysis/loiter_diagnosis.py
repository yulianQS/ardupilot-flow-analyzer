"""Loiter 证据筛查，不把时间相关性升级为根因或统计概率。

每个检查包含状态、实际数值/时刻、阈值、证据来源和建议。没有记录/未满足
物理前提 => Insufficient Data。光流与EKF可能同源，不可视为独立真值。
"""
from dataclasses import dataclass, asdict, field
import csv
import html
import io
import json
import logging
from pathlib import Path
import numpy as np
from PySide6.QtCore import QThread, Signal
import config
from analysis.ekf import align, flow_body_velocity, body_to_ned, correlation
from analysis.timeline_events import extract_events,event_evidence,active_bounds

@dataclass
class Finding:
    check: str
    status: str
    evidence: str
    recommendation: str = ''
    time_s: float | None = None
    confidence: str = '观测结论；未标定概率'

@dataclass
class LoiterEvent:
    index: int
    time_s: float
    exit_s: float
    window_start: float
    window_end: float
    findings: list

@dataclass
class DiagnosisReport:
    path: str
    core: int
    range_instance: int
    events: list
    notes: list
    thresholds: dict
    timeline: list = field(default_factory=list)

    def text(self):
        lines = ['ArduPilot Optical Flow Analyzer — 全程事件与 Loiter 诊断',f'文件: {self.path}',
                 f'EKF core={self.core}; RangeFinder instance={self.range_instance}',
                 '已确认事实=记录值及事件；候选原因=待验证解释；N/A=证据缺失。HIGH/LOW不是根因概率。',*self.notes]
        lines.extend(['','全程事件时间线（包括 Loiter 以外及锁定后的事件）'])
        for item in self.timeline:
            lines.extend([f"[{item['category']}] {item['time_s']:.3f}s · {item['label']}",
                          '  已记录事实：'+item['evidence'],
                          '  局部窗口：'+item['window'],
                          '  解释边界：相关性不是根因；急停/锁定后的峰值不应倒推为起因。'])
        if not self.events:
            lines.append('Insufficient Data：没有可确认的 Copter LOITER 时间段；仍可阅读上方事件证据。')
        for event in self.events:
            lines.extend(['','─'*55,f'Loiter Event #{event.index}',f'Time: {event.time_s:.3f} s; Exit: {event.exit_s:.3f} s',
                          f'分析窗口: {event.window_start:.3f}–{event.window_end:.3f} s'])
            for finding in event.findings:
                when = '' if finding.time_s is None else f' @ {finding.time_s:.3f}s (Loiter {finding.time_s-event.time_s:+.3f}s)'
                lines.extend([f'[{finding.status}] {finding.check}{when}',f'  Evidence: {finding.evidence}',
                              f'  Recommendation: {finding.recommendation or "结合时间游标查看其他信号。"}'])
            candidates = [finding.check for finding in event.findings if finding.status in ('WARNING','HIGH','LOW','ABNORMAL','CANDIDATE')]
            lines.append('优先复核：'+('；'.join(candidates) if candidates else '未检出超阈值项；不表示飞行安全已获证明。'))
        lines.extend(['','本次阈值快照:',json.dumps(self.thresholds,ensure_ascii=False,indent=2)])
        return '\n'.join(lines)

    def export(self,path):
        path = Path(path)
        suffix = path.suffix.lower()
        if suffix == '.csv':
            with path.open('w',encoding='utf-8-sig',newline='') as file:
                writer = csv.writer(file)
                writer.writerow(['file','event','entry_s','exit_s','check','status','evidence_time_s','evidence','recommendation'])
                for event in self.events:
                    for finding in event.findings:
                        writer.writerow([self.path,event.index,event.time_s,event.exit_s,finding.check,finding.status,finding.time_s,finding.evidence,finding.recommendation])
                for item in self.timeline:
                    writer.writerow([self.path,'timeline','','',item['label'],item['category'],item['time_s'],item['evidence'],item['window']])
                for note in self.notes:
                    writer.writerow([self.path,'','','','报告备注','INFO','',note,''])
                writer.writerow([self.path,'','','','阈值快照','INFO','',json.dumps(self.thresholds,ensure_ascii=False),''])
        elif suffix == '.html':
            path.write_text('<!doctype html><html lang="zh"><meta charset="utf-8"><title>Loiter Diagnosis</title>'
                            '<style>body{max-width:1100px;margin:40px auto;background:#111923;color:#e4edf7;font:15px/1.7 system-ui}pre{white-space:pre-wrap}</style><pre>'
                            +html.escape(self.text())+'</pre></html>',encoding='utf-8')
        else:
            path.write_text(self.text(),encoding='utf-8-sig')

def diagnose(dataset,core=0,range_instance=0,cancelled=lambda:False):
    signals = dataset.signals(core,range_instance)
    notes = list(dataset.warnings)
    notes.append('覆盖每段完整 Loiter 至退出或连续数据末尾；另列全程事件及前3秒/后8秒局部窗口。段内峰值可能位于急停之后，请先核对时间线。固定core可能不是当时主core。')
    notes.append('NED X=北/Y=东/Z=下；Body X=机头/Y=右/Z=下；OF为rad/s；RFND为m；ATT为deg。')
    thresholds = {name:value for name,value in vars(config).items() if name.isupper() and isinstance(value,(int,float))}
    report = DiagnosisReport(dataset.path,core,range_instance,[],notes,thresholds)
    mode = signals.get('mode')
    # Copter 固定模式号 5=LOITER；不对 Plane/Rover 日志套用此映射。
    messages = dataset.frames.get('MSG')
    if messages is not None and 'Message' in messages:
        firmware = ' '.join(messages.Message.astype(str).tolist())
        if any(name in firmware for name in ('ArduPlane','ArduRover','ArduSub')):
            report.notes.append('Insufficient Data：检测到非Copter固件，本诊断仅支持 ArduCopter。')
            return report
    if any('时钟回退' in note for note in notes):
        report.notes.append('Insufficient Data：时钟回退可能混合多次启动，已停止自动事件诊断。')
        return report
    for event in extract_events(dataset,signals,cancelled):
        if cancelled():raise InterruptedError('诊断已取消')
        local=[]
        for key in ('vx','vy','range','desired_pitch','flow_test_ratio'):
            s=signals.get(key)
            if s is None:continue
            mask=(s.time>=max(0,event.time_s-3))&(s.time<=event.time_s+8)&np.isfinite(s.value)
            if np.any(mask):
                v=s.value[mask];t=s.time[mask]
                local.append(f'{key} {v.min():.3g}–{v.max():.3g} {s.unit}，最大绝对值@{t[np.argmax(np.abs(v))]:.3f}s')
        report.timeline.append(dict(time_s=event.time_s,category=event.category,label=event.label,
                                    evidence=event_evidence(dataset,signals,event),window='；'.join(local) or '缺少附近连续数据'))
    if mode is None:return report
    continuous_end=active_bounds(signals)[1]
    transitions = []
    previous = None
    for timestamp,value in zip(mode.time,mode.value):
        if np.isfinite(value) and value != previous:
            transitions.append((float(timestamp),int(value)))
            previous = value
    for index,(entry,number) in enumerate(transitions):
        if cancelled():
            raise InterruptedError('诊断已取消')
        if number != 5:
            continue
        exit_time = transitions[index+1][0] if index+1<len(transitions) else dataset.duration
        start,end = max(0,entry-config.BEFORE_LOITER_S),min(dataset.duration,continuous_end,exit_time)
        if end<entry:continue
        findings = []
        if index == 0:
            findings.append(Finding('Loiter进入时刻','Insufficient Data','第一条 MODE 已为 Loiter，实际切入可能早于日志开始。'))
        def window(key,post=True):
            series = signals.get(key)
            if series is None:
                return np.array([]),np.array([])
            mask = (series.time >= (entry if post else start))&(series.time <= end)&np.isfinite(series.value)
            return series.time[mask],series.value[mask]
        def missing(check,reason):
            findings.append(Finding(check,'Insufficient Data',reason))
        def magnitude(check,keys,threshold,unit,recommendation,status='HIGH',absolute=True):
            candidates = []
            available = []
            for key in keys:
                t,v = window(key)
                if len(v)>=config.MIN_DIAG_SAMPLES:
                    available.append(key)
                    at = int(np.argmax(np.abs(v) if absolute else v))
                    candidates.append((abs(v[at]) if absolute else v[at],t[at],key,v[at]))
            if not candidates:
                missing(check,'缺少足够的 '+','.join(keys)+' 样本')
                return
            peak,t,key,actual = max(candidates)
            findings.append(Finding(check,status if peak>threshold else 'NORMAL',
                f'{signals[key].source}={actual:.4g} {unit}; 阈值 {threshold:g}；可用字段 {available}',recommendation,float(t)))
        magnitude('1. Optical Flow X/Y',['flow_x','flow_y'],config.FLOW_RATE_HIGH_RAD_S,'rad/s','核对纹理、光照、角运动及 OF.bodyX/bodyY。')
        t,q = window('quality')
        if len(q)<config.MIN_DIAG_SAMPLES:
            missing('2. Optical Flow Quality','缺少 OF.Qual / Q')
        else:
            i = int(np.argmin(q))
            findings.append(Finding('2. Optical Flow Quality','LOW' if q[i]<config.FLOW_QUALITY_MIN else 'NORMAL',
                f'min={q[i]:.0f}/255; 低于{config.FLOW_QUALITY_MIN}的比例={np.mean(q<config.FLOW_QUALITY_MIN):.1%}',
                '本软件质量阈值，不是飞控的融合门限或准确率。检查纹理、照明和有效距离。',float(t[i])))
        ft,fv=window('flow_test_ratio')
        if len(fv)>=config.MIN_DIAG_SAMPLES:
            bad=fv>=1
            findings.append(Finding('2b. 光流融合一致性','WARNING' if bad.any() else 'INFO',
                f'Copter4.6.3 NI/100，>=1样本占比 {np.mean(bad):.1%}；最大记录比值 {fv.max():.3g}（2.55为截顶）；至少一个轴不一致，不代表两个轴均拒绝。',
                '比较事件前的速度、测距、光流和姿态；Quality达标也不能替代融合验证。',float(ft[np.argmax(fv)])))
        else:missing('2b. 光流融合一致性','缺少已核对版本的 XKF5.NI 或样本；未知固件不猜缩放。')
        zero_x,zero_y=signals.get('flow_x'),signals.get('flow_y')
        if zero_x is not None and zero_y is not None:
            zt,zx=window('flow_x');zy=align(zero_y,zt)
            valid=np.isfinite(zy)
            if valid.sum()>=config.MIN_DIAG_SAMPLES:
                fraction=float(np.mean((zx[valid]==0)&(zy[valid]==0)))
                findings.append(Finding('2c. 双轴零值观测','CANDIDATE' if fraction>.95 else 'INFO',
                    f'对齐样本双轴恰为零占比 {fraction:.1%}；零值可能是静止、低质量处理或数据问题。',
                    '需要已知平移/旋转动作验证响应；不能以全零判定工作正常或直接判定硬件损坏。'))
        t,r = window('range',False)
        if len(r)<config.MIN_DIAG_SAMPLES:
            missing('3. RangeFinder掉线','缺少 RFND 数据；不能据此认定硬件掉线')
            missing('4. RangeFinder跳变','缺少 RFND 数据')
        else:
            gaps = np.diff(np.r_[start,t,end])
            statuses = align(signals.get('range_status'),t)
            bad = np.isfinite(statuses)&(statuses!=4)
            gap = float(np.max(gaps))
            findings.append(Finding('3. RangeFinder掉线','WARNING' if gap>config.STALE_S or bad.any() else 'NORMAL',
                f'最大记录空洞={gap:.3f}s；非Good状态样本={int(bad.sum())}；无Stat时仅检查记录空洞',
                '区分记录速率不足与传感器掉线，检查 RFND.Stat 和 STATUSTEXT。'))
            jump = (np.abs(np.diff(r))>config.RANGE_JUMP_M)&(np.diff(t)<=config.RANGE_JUMP_INTERVAL_S)
            out = (r<config.RANGE_MIN_M)|(r>config.RANGE_MAX_M)
            findings.append(Finding('4. RangeFinder跳变','WARNING' if jump.any() or out.any() else 'NORMAL',
                f'距离 {r.min():.3f}–{r.max():.3f} m；跳变 {int(jump.sum())} 次；超本地量程 {int(out.sum())} 次',
                '核对斜距、表面反光以及实际量程；跳变阈值见config.py。',float(t[np.flatnonzero(jump)[0]+1]) if jump.any() else None))
        magnitude('5. EKF水平速度',['vx','vy'],config.EKF_SPEED_HIGH_M_S,'m/s','对照控制动作与外部运动证据。',status='ABNORMAL')
        magnitude('6. Roll/Pitch控制动作',['roll','pitch','desired_roll','desired_pitch'],config.ATTITUDE_HIGH_DEG,'deg','比较 ATT.DesRoll/DesPitch 与实际姿态，确认控制指令先后。')
        rc_neutral = None
        rc_evidence = []
        for axis in ('ROLL','PITCH'):
            channel = dataset.param_at('RCMAP_'+axis,entry)
            if channel is None or not 1<=channel<=16:
                continue
            channel = int(channel)
            trim = dataset.param_at(f'RC{channel}_TRIM',entry)
            t,v = window(f'rc{channel}')
            if trim is None or len(v)<config.MIN_DIAG_SAMPLES:
                continue
            # RC 0/65535 是无效值，不能当成飞手指令。
            valid = (v>0)&(v<65535)
            if valid.sum()<config.MIN_DIAG_SAMPLES:
                continue
            delta = float(np.max(np.abs(v[valid]-trim)))
            rc_evidence.append((axis,channel,trim,delta))
        if len(rc_evidence)==2:
            rc_neutral = all(item[3]<=config.RC_DEADBAND_US for item in rc_evidence)
            findings.append(Finding('7. RC输入','NEUTRAL' if rc_neutral else 'WARNING',
                '; '.join(f'{a}=RC{c},trim={tr:g},最大偏移={d:.1f} us' for a,c,tr,d in rc_evidence),
                '超过死区说明存在输入，但需要确认遥控器校准和飞手意图。'))
        else:
            missing('7. RC输入','缺少 RCIN、RCMAP_ROLL/PITCH 或对应 RCx_TRIM；不假定通道1/2或1500中位')
        pwm_type = dataset.param_at('MOT_PWM_TYPE',entry)
        motor_channels = [i for i in range(1,17) if dataset.param_at(f'SERVO{i}_FUNCTION',entry) in range(33,41)]
        output_values = []
        for channel in motor_channels:
            output_time,values = window(f'out{channel}')
            arm_source = signals.get('armed')
            if arm_source is not None:
                is_armed = np.array([arm_source.at(t)==1 for t in output_time])
                output_values.append(values[is_armed])
        output_values = [values[(values>0)&(values<65535)] for values in output_values if len(values)]
        output_values = [v for v in output_values if len(v)]
        if pwm_type not in (0,1) or not output_values:
            missing('8. Motor / Servo输出',f'MOT_PWM_TYPE={pwm_type}；需确认PWM协议、SERVOx_FUNCTION电机映射和ARMED片段，不能用停转输出诊断饱和。')
        else:
            fractions = [np.mean((v<=config.OUTPUT_LOW_US)|(v>=config.OUTPUT_HIGH_US)) for v in output_values]
            findings.append(Finding('8. Motor / Servo输出','WARNING' if max(fractions)>config.OUTPUT_SATURATION_FRACTION else 'NORMAL',
                f'有效输出范围 {min(v.min() for v in output_values):g}–{max(v.max() for v in output_values):g}; 最大通道边界占比 {max(fractions):.1%}',
                '仅对SERVOx_FUNCTION已确认的电机及ARMED片段筛查；低油门贴近下界也可能正常，不能直接判电机故障。'))
        magnitude('9. Vibration',['vibe_x','vibe_y','vibe_z'],config.VIBRATION_HIGH_M_S2,'m/s²','检查桨、电机、安装减振，并对照IMU clipping。')
        t,yaw = window('yaw',False)
        if len(yaw)<config.MIN_DIAG_SAMPLES:
            missing('10. Yaw跳变','缺少ATT.Yaw')
        else:
            delta = (np.diff(yaw)+180)%360-180
            mask = (np.abs(delta)>config.YAW_JUMP_DEG)&(np.diff(t)<=config.YAW_JUMP_INTERVAL_S)
            findings.append(Finding('10. Yaw跳变','WARNING' if mask.any() else 'NORMAL',
                f'环绕处理后最大相邻变化={np.max(np.abs(delta)):.3f} deg; 超阈值次数={mask.sum()}',
                '359°→0°已排除；检查航向重置、磁干扰及真实旋转。',float(t[np.flatnonzero(mask)[0]+1]) if mask.any() else None))
        magnitude('11. Compass / EKF航向',['iyaw'],config.YAW_INNOVATION_HIGH_DEG,'deg',
                  '检查 XKF3.IYAW、XKF4.SM 与 MAG；仅凭航向创新不能确定磁罗盘故障。')
        _flow_comparison(findings,signals,entry,end)
        # 无位置真值不能确认静止：即使ARM=0且姿态稳定，也可能有人搬动。
        arm = signals.get('armed')
        pre_t,pre_fx = window('flow_x',False)
        pre_mask = pre_t < entry
        if arm is None or arm.at(max(start,entry-0.1)) != 0 or pre_mask.sum()<config.STATIC_MIN_SAMPLES:
            missing('13. 静止假速度','缺少进入前已确认DISARMED的稳定姿态/光流片段；飞行中不能假定静止')
        else:
            pre_t = pre_t[pre_mask]
            roll = align(signals.get('roll'),pre_t)
            pitch = align(signals.get('pitch'),pre_t)
            fy = align(signals.get('flow_y'),pre_t)
            stable = np.all(np.isfinite(roll)) and np.all(np.isfinite(pitch)) and np.std(roll)<config.STATIC_ATTITUDE_STD_DEG and np.std(pitch)<config.STATIC_ATTITUDE_STD_DEG
            drift = max(float(np.std(pre_fx[pre_mask])),float(np.nanstd(fy)))
            findings.append(Finding('13. 静止假速度','CANDIDATE' if stable and drift>config.STATIC_FLOW_STD_RAD_S else 'Insufficient Data',
                f'DISARMED片段角光流std={drift:.4f} rad/s，姿态稳定={stable}；缺少位置静止独立证据',
                '固定飞机再做静止测试，排除水平搬动。'))
        magnitude('17. EKF innovation / variance',['sv','sp','sh','sm'],config.EKF_TEST_RATIO_HIGH,'test ratio',
                  '检查XKF4创新检验比及主lane；大于1通常表示对应观测被拒绝。')
        magnitude('17b. 速度创新',['ivn','ive'],config.VELOCITY_INNOVATION_HIGH_M_S,'m/s','检查观测延迟与速度数据源。')
        _feedback(findings,signals,entry,end,rc_neutral)
        lane = signals.get('primary_core')
        if lane:
            _,values = window('primary_core')
            findings.append(Finding('EKF lane上下文','INFO',f'窗口内主lane={np.unique(values).tolist()}，当前分析lane={core}。'))
        report.events.append(LoiterEvent(len(report.events)+1,entry,exit_time,start,end,findings))
    logging.info('Loiter诊断完成 events=%s path=%s',len(report.events),dataset.path)
    return report

def _flow_comparison(findings,signals,start,end):
    checks = ['12. 光流与EKF速度方向','14. 光流X/Y交换','15. 光流符号反向','16. 光流比例错误']
    required = ['flow_x','flow_y','body_x','body_y','quality','range','range_status','vx','vy','roll','pitch','yaw']
    missing = [key for key in required if key not in signals]
    def insufficient(reason):
        for check in checks:
            findings.append(Finding(check,'Insufficient Data',reason,'做独立方向测试；核对 FLOW_ORIENT_YAW 和 FLOW_FXSCALER/FLOW_FYSCALER。'))
    if missing:
        insufficient('缺少 '+','.join(missing)+'；不能直接比较光流轴与NED速度轴')
        return
    flow = signals['flow_x']
    times = flow.time[(flow.time>=start)&(flow.time<=end)]
    values = {key:align(signals[key],times) for key in required}
    valid = np.all(np.isfinite(np.array(list(values.values()))),axis=0)
    valid &= (values['quality']>=config.FLOW_QUALITY_MIN)&(values['range_status']==4)
    valid &= (values['range']>=config.RANGE_MIN_M)&(values['range']<=config.RANGE_MAX_M)
    valid &= (np.abs(values['roll'])<=config.DIRECTION_LEVEL_MAX_DEG)&(np.abs(values['pitch'])<=config.DIRECTION_LEVEL_MAX_DEG)
    valid &= np.hypot(values['vx'],values['vy'])>=config.FLOW_COMPARE_MIN_SPEED_M_S
    if valid.sum()<config.FLOW_COMPARE_MIN_SAMPLES:
        insufficient(f'质量、量程、近水平、有效速度及时间对齐筛选后仅{valid.sum()}个样本')
        return
    values = {key:value[valid] for key,value in values.items()}
    bx,by = flow_body_velocity(values['flow_x'],values['flow_y'],values['body_x'],values['body_y'],values['range'])
    vn,ve = body_to_ned(bx,by,values['yaw'])
    reference = np.column_stack([values['vx'],values['vy']])
    predicted = np.column_stack([vn,ve])
    rms = float(np.sqrt(np.mean((predicted-reference)**2)))
    denominator = np.sqrt(np.mean(reference**2))
    normalized_error = rms/max(denominator,1e-6)
    corr = correlation(predicted.ravel(),reference.ravel())
    findings.append(Finding(checks[0],'CANDIDATE' if corr is not None and corr<0 else 'INFO',
        f'n={len(vn)}, 同轴相关={corr}, RMS差={rms:.3f} m/s；已减机体角速率、乘斜距、按yaw转NED；近水平近似',
        'EKF可能融合该光流，因此相关性不是独立验证；还需外部运动真值。'))
    # 拟合只是反事实对照，先检查两个机体轴都得到充分激励。
    if min(np.std(bx),np.std(by))<config.FLOW_COMPARE_MIN_SPEED_M_S/2:
        for check in checks[1:]:
            findings.append(Finding(check,'Insufficient Data','两个轴的运动激励不足，无法区分交换、反向和比例。'))
        return
    alternatives = {}
    for label,x,y in [('identity',bx,by),('swap',by,bx),('invert_x',-bx,by),('invert_y',bx,-by),('invert_xy',-bx,-by)]:
        north,east = body_to_ned(x,y,values['yaw'])
        alternatives[label] = float(np.sqrt(np.mean((np.column_stack([north,east])-reference)**2))/max(denominator,1e-6))
    best = min(alternatives,key=alternatives.get)
    improvement = alternatives['identity']-alternatives[best]
    evidence = f'归一化RMS差 {alternatives}; 最佳候选={best}，改善={improvement:.3f}；速度层对照无法单独定位传感器轴。'
    for check,is_candidate in [(checks[1],best=='swap'),(checks[2],best.startswith('invert'))]:
        findings.append(Finding(check,'CANDIDATE' if is_candidate and improvement>config.FLOW_COMPARE_IMPROVEMENT else 'INFO',evidence,
            '仅为待复核假设；做光流方向测试并检查 FLOW_ORIENT_YAW，不自动改参。'))
    ratio = float(np.sqrt(np.mean(predicted**2))/max(denominator,1e-6))
    findings.append(Finding(checks[3],'CANDIDATE' if ratio<config.FLOW_SCALE_RATIO_LOW or ratio>config.FLOW_SCALE_RATIO_HIGH else 'INFO',
        f'光流估计/EKF速度RMS比={ratio:.3f}；范围{config.FLOW_SCALE_RATIO_LOW}–{config.FLOW_SCALE_RATIO_HIGH}',
        '比例差也可来自距离、时间延迟、倾斜和融合反馈；需独立速度真值，不能据此计算新scaler。'))

def _feedback(findings,signals,start,end,rc_neutral):
    check = '18. Loiter后正反馈趋势'
    required = ['vx','vy','desired_roll','desired_pitch','yaw']
    if rc_neutral is not True or any(key not in signals for key in required):
        findings.append(Finding(check,'Insufficient Data','需已校准RC中立、目标姿态、yaw及EKF速度，才能筛查控制趋势。'))
        return
    source = signals['vx']
    t = source.time[(source.time>=start)&(source.time<=end)]
    data = {key:align(signals[key],t) for key in required}
    valid = np.all(np.isfinite(np.array(list(data.values()))),axis=0)
    t = t[valid]
    data = {key:value[valid] for key,value in data.items()}
    if len(t)<config.FLOW_COMPARE_MIN_SAMPLES or np.any(np.diff(t)>config.STALE_S):
        findings.append(Finding(check,'Insufficient Data','连续对齐样本不足'))
        return
    ax = -9.80665*np.tan(np.radians(data['desired_pitch']))
    ay = 9.80665*np.tan(np.radians(data['desired_roll']))
    an,ae = body_to_ned(ax,ay,data['yaw'])
    speed = np.hypot(data['vx'],data['vy'])
    along = (an*data['vx']+ae*data['vy'])/np.maximum(speed,config.FLOW_COMPARE_MIN_SPEED_M_S)
    rise = float(np.median(speed[-5:])-np.median(speed[:5]))
    sustained = float(np.mean(along>config.POSITIVE_FEEDBACK_ACCEL_M_S2))
    candidate = rise>config.EKF_SPEED_RISE_M_S and sustained>config.POSITIVE_FEEDBACK_CORRELATION
    findings.append(Finding(check,'CANDIDATE' if candidate else 'INFO',
        f'速度中位增量={rise:.3f} m/s；目标姿态产生沿速度方向加速的样本比例={sustained:.1%}；RC中立',
        '这是控制加速与估计速度共同增长候选；需要期望速度、位置误差、真实运动及先后关系验证闭环正反馈。'))

class DiagnosisWorker(QThread):
    result = Signal(object)
    error = Signal(str)
    def __init__(self,dataset,core,range_instance):
        super().__init__()
        self.dataset,self.core,self.range_instance = dataset,core,range_instance
    def run(self):
        try:
            self.result.emit(diagnose(self.dataset,self.core,self.range_instance,self.isInterruptionRequested))
        except Exception as exception:
            logging.exception('诊断失败')
            self.error.emit(str(exception))
