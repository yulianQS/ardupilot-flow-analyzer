import json
import time
from pathlib import Path
import numpy as np
from PySide6.QtWidgets import QWidget,QVBoxLayout,QHBoxLayout,QLabel,QPushButton,QCheckBox,QPlainTextEdit,QFileDialog,QSpinBox
from analysis.ground_check import assess_step
from analysis.optical_flow import evaluate_direction
from analysis.capture_checks import motion_errors, filter_capture
import config

STEPS=[('height','保持朝下，缓慢改变离地高度（在模块有效量程内）'),
       ('forward','保持水平且不旋转，向机头方向平移'),('backward','保持水平且不旋转，向机尾方向平移'),
       ('right','保持水平且不旋转，向右平移'),('left','保持水平且不旋转，向左平移'),
       ('rotation','保持位置基本不变，缓慢做小幅横滚/俯仰转动'),('static','放回稳定表面，确认没有平移或转动后开始')]

class GroundCheckPage(QWidget):
    def __init__(self):
        super().__init__()
        self.store=None;self.armed=None;self.connected=False
        layout=QVBoxLayout(self)
        intro=QLabel('地面检查 · 拆桨并保持锁定 · 每步记录5秒\n先验证测距响应，再检查四向平移、旋转与静置。结果只描述证据，不自动改参，也不代表准飞。')
        intro.setWordWrap(True);layout.addWidget(intro)
        self.confirm=QCheckBox('我已拆桨，并会按每步说明进行动作或保持静置')
        self.confirm.setToolTip('这是采样的物理前提；软件不能从姿态平稳自动证明位置静止。')
        layout.addWidget(self.confirm)
        self.instruction=QLabel();self.instruction.setWordWrap(True);layout.addWidget(self.instruction)
        controls=QHBoxLayout()
        self.begin_button=QPushButton('开始本步（5秒）');self.begin_button.clicked.connect(self.begin)
        self.begin_button.setToolTip('只采集实时数据；不发送控制命令。连接、锁定或样本条件不满足时本步无效。')
        controls.addWidget(self.begin_button)
        reset=QPushButton('重置整轮检查');reset.clicked.connect(self.reset);reset.setToolTip('清空本轮采样和结果，不修改飞控参数。');controls.addWidget(reset)
        self.export_button=QPushButton('导出地面检查 JSON');self.export_button.clicked.connect(self.export);self.export_button.setToolTip('保存动作、采样、数据来源及结论，便于后续复核。');controls.addWidget(self.export_button)
        layout.addLayout(controls)
        quality_controls=QHBoxLayout()
        quality_controls.addWidget(QLabel('动作采样质量门限（1–255）：'))
        self.quality_min=QSpinBox();self.quality_min.setRange(1,255)
        self.quality_min.setValue(config.CAPTURE_QUALITY_MIN)
        self.quality_min.setToolTip('只影响本页地面采样；原始数据仍保存。整轮使用同一门限，更改需重置整轮。质量0不参与方向判断。')
        quality_controls.addWidget(self.quality_min)
        quality_note=QLabel('默认30供排查；质量不是百分制，降低门限不代表光流可靠。')
        quality_note.setWordWrap(True);quality_controls.addWidget(quality_note,1)
        layout.addLayout(quality_controls)
        self.status=QLabel();self.status.setWordWrap(True);layout.addWidget(self.status)
        self.results=QPlainTextEdit();self.results.setReadOnly(True);layout.addWidget(self.results,1)
        self.reset()

    def reset(self):
        self.step=0;self.started=None;self.records=[];self.captures={};self.results.clear()
        self.begin_button.setEnabled(True);self.export_button.setEnabled(False)
        self.quality_min.setEnabled(True)
        self.status.setText('等待连接和本步准备完成。');self.show_step()

    def show_step(self):
        self.instruction.setText(f'第 {self.step+1}/{len(STEPS)} 步：{STEPS[self.step][1]}' if self.step<len(STEPS) else '本轮完成。请阅读每步证据和不足，再决定需要复查哪一项。')

    def begin(self):
        if not self.confirm.isChecked() or not self.connected or self.armed is not False or self.store is None:
            self.status.setText('需要确认拆桨、已连接且飞控状态为 DISARMED。');return
        if self.step>=len(STEPS):return
        self.started=time.monotonic();self.source,self.unit=self.store.flow_source(self.started)
        self.invalid={};self.begin_button.setEnabled(False);self.quality_min.setEnabled(False)

    def update_data(self,store,now,armed,connected):
        self.store,self.armed,self.connected=store,armed,connected
        if self.started is None:return
        kind,_=STEPS[self.step]
        if not connected or armed is not False or not self.confirm.isChecked():self.invalid['state']='连接、锁定状态或拆桨确认条件变化'
        if kind!='height' and store.flow_source(now)[0]!=self.source:self.invalid['source']='采样期间光流来源改变'
        if kind in ('forward','backward','right','left','static'):
            self.invalid.update(motion_errors(store,now))
        required=['range'] if kind=='height' else [self.source+'_x',self.source+'_y',self.source+'_quality']
        if kind=='static':required+=['vx','vy']
        for key in required:
            if store.get(key,now) is None:self.invalid[key]=f'{key} 数据缺失或过期'
        remaining=5-(now-self.started)
        issue='；已触发：'+'；'.join(self.invalid.values()) if self.invalid else ''
        self.status.setText(f'采样中：剩余 {max(0,remaining):.1f}秒 · {self.source} / {self.unit}'+issue)
        if remaining>0:return
        began=self.started;self.started=None;self.begin_button.setEnabled(True)
        if self.invalid:
            self.status.setText('本步无效：'+'；'.join(self.invalid.values())+'。请重做当前步骤。');return
        samples={}
        for key in ('range','flow_x','flow_y','quality','rollspeed','pitchspeed','yawspeed','vx','vy'):
            mapped={'flow_x':self.source+'_x','flow_y':self.source+'_y','quality':self.source+'_quality'}.get(key,key)
            data=store.window(mapped,now,now-began)
            samples[key]=data.tolist()
        result=assess_step(kind,samples,self.unit,self.quality_min.value())
        if kind in ('forward','backward','right','left'):
            self.captures[kind],summary=filter_capture(samples['flow_x'],samples['flow_y'],samples['quality'],self.quality_min.value())
            result+='\n'+summary
        self.records.append(dict(step=kind,action=STEPS[self.step][1],source=self.source,unit=self.unit,result=result,samples=samples))
        self.results.appendPlainText(f'{self.step+1}. {STEPS[self.step][1]}\n{result}\n')
        self.step+=1;self.export_button.setEnabled(True);self.show_step()
        if self.step==len(STEPS):
            self.begin_button.setEnabled(False)
            units={r['unit'] for r in self.records if r['step'] in ('forward','backward','right','left')}
            sources={r['source'] for r in self.records if r['step'] in ('forward','backward','right','left')}
            direction=evaluate_direction(self.captures,next(iter(units))) if len(units)==1 and len(sources)==1 else '证据不足：不同步骤的光流来源或单位不一致。'
            self.results.appendPlainText(f'四向检查汇总（本轮门限{self.quality_min.value()}/255，仅供地面排查）：\n'+direction)
        self.status.setText('本步已记录。请停止动作，准备下一步。' if self.step<len(STEPS) else '本轮完成，可导出复核。')

    def export(self):
        path,_=QFileDialog.getSaveFileName(self,'导出地面检查',str(config.DATA_DIR/'ground_check.json'),'JSON (*.json)')
        if not path:return
        try:
            Path(path).write_text(json.dumps(dict(created=time.strftime('%Y-%m-%d %H:%M:%S'),quality_local_threshold=self.quality_min.value(),records=self.records,summary=self.results.toPlainText()),ensure_ascii=False,indent=2),encoding='utf-8')
            self.status.setText('已导出：'+path)
        except OSError as exc:self.status.setText('导出失败：'+str(exc))
