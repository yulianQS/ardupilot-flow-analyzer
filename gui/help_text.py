"""集中维护中文解释；仅描述，不生成参数写入或自动调参建议。"""
import re
import html
import config

SIGNALS = {
    'quality': '光流质量指标，0–255，通常越大越好；不是准确率百分比。LOW 使用本软件阈值，不代表 EKF 一定拒绝或接受。',
    'flow_x': 'X 轴图像运动角速率，rad/s，包含旋转影响；不是机头方向的地速。平移与旋转应分别验证。',
    'flow_y': 'Y 轴图像运动角速率，rad/s，包含旋转影响；不能直接与东向速度比较。',
    'body_x': '机体 X 轴角速率，rad/s，用于理解光流的旋转分量；不是平移速度。',
    'body_y': '机体 Y 轴角速率，rad/s，用于理解光流的旋转分量；不是平移速度。',
    'range': '传感器沿测量方向得到的距离，米；0.14 m=14 cm。飞机倾斜或翻转后，不一定等于垂直离地高度。',
    'range_status': '测距状态：0 未连接，1 无数据，2 低于量程，3 高于量程，4 Good。缺少状态字段不能当作 Good。',
    'vx': '北向速度估计 VN，m/s；正为向北，负为向南。它是估计值，不是独立实测真值。',
    'vy': '东向速度估计 VE，m/s；正为向东，负为向西；不是机体右向速度。',
    'vz': '向下速度估计 VD，m/s；正数表示下降方向，负数表示上升方向。',
    'roll': '实际横滚角，度；机体向左右倾斜的角度。与目标横滚比较可帮助分析控制响应。',
    'pitch': '实际俯仰角，度；正为抬头，负为低头。先后顺序比单独的峰值更有用。',
    'yaw': '航向角，度；接近 0/360 为北、90 为东。359→0 是角度环绕，不一定是航向跳变。',
    'desired_roll': '飞控要求的目标横滚角，度；目标先变而实际随后变化，说明飞控先给出了倾斜指令。',
    'desired_pitch': '飞控要求的目标俯仰角，度；Loiter 下也会因位置/速度误差自动变化，不只取决于摇杆。',
    'desired_yaw': '飞控要求的目标航向角，度；与实际航向比较时需要处理 0/360 环绕。',
    'armed': '解锁状态：1=ARMED，0=DISARMED。急停可能先停电机，稍后才进入锁定；缺少记录时状态未知。',
    'mode': '飞行模式：Copter 0=Stabilize，5=Loiter，9=Land。模式是离散状态，沿用此前最近记录。',
    'flow_norm': 'XKF5.NI 原始记录值。已核对 Copter 4.6.3：100 对应一致性比值 1，255 为截顶上限；不是质量或百分比。其他版本需核对定义。',
    'flow_test_ratio': 'Copter 4.6.3 的 NI/100：约 1 是一致性检查边界，2.55 表示截顶，真实值可更大；取两轴最大值，不能据此判断两轴都拒绝。',
    'flow_innov_x': '光流 X 创新原始 logged value。Copter 4.6.3 按 1000 倍记录，不应直接读成 rad/s。',
    'flow_innov_y': '光流 Y 创新原始 logged value。Copter 4.6.3 按 1000 倍记录，不应直接读成 rad/s。',
    'sv': 'EKF 速度观测一致性检查比值；超过 1 需关注。不是 m/s；未启用相应观测时，零不代表全部导航状态健康。',
    'sp': 'EKF 水平位置观测一致性检查比值；不是位置误差的米数。',
    'sh': 'EKF 高度观测一致性检查比值；不是高度的米数。超过 1 需检查高度源。',
    'sm': 'EKF 磁场观测一致性检查比值；超过 1 需检查磁场、姿态和事件时序，不能单独判罗盘坏。',
    'iyaw': '航向创新：预测与观测的差异，度。用于检查一致性，不是实际航向。',
    'ivn': '北向速度创新，m/s，即速度观测与预测的差异。',
    'ive': '东向速度创新，m/s，即速度观测与预测的差异。',
    'primary_core': '该时刻使用的主 EKF 实例编号。从 0 开始；需与当前选择的 core 匹配。',
    'ekf_flags': 'EKF 状态位集合，每个位代表一种状态；出现某标志不保证光流始终可靠融合。',
    'battery_v': '电池电压，伏；仅显示遥测值，未据此推断电池剩余容量。',
}
PARAMETERS = {
    'AHRS_EKF_TYPE': '姿态/导航使用的估计器类型；3 表示 EKF3。不是传感器数量。',
    'EK3_ENABLE': '是否启用 EKF3；1 启用。',
    'EK3_IMU_MASK': '选择哪些 IMU 运行 EKF 的位掩码；1 选择第一颗 IMU，编号通常对应 core 0。',
    'EK3_PRIMARY': '首选 EKF 实例编号，从 0 开始。实际主实例还要看日志中的 primary_core。',
    'EK3_SRC1_POSXY': '源组1的水平位置观测来源；0 表示无独立位置观测，不表示不能估计位置。',
    'EK3_SRC1_VELXY': '源组1的水平速度观测来源；5 表示光流。收到光流不等于融合一定通过。',
    'EK3_SRC1_POSZ': '源组1的高度观测来源；1 为气压计，2 为测距。应结合实际传感器有效范围选择。',
    'EK3_SRC1_VELZ': '源组1的垂直速度观测来源；0 表示不使用独立垂直速度观测，EKF 仍会估计垂直速度。',
    'EK3_SRC1_YAW': '源组1的航向观测来源；1 为罗盘。应结合磁场一致性检查。',
    'EK3_SRC_OPTIONS': '数据源选项位掩码；多个开关组合成一个整数，不是单一档位。',
    'FLOW_TYPE': '光流输入驱动类型；Copter 4.6.3 中 5 为 MAVLink。还需核对实际模块与通信配置。',
    'FLOW_ORIENT_YAW': '光流安装偏航角补偿，单位 0.01 度；9000=90°。零表示不旋转补偿，并不证明安装方向正确。',
    'FLOW_FXSCALER': 'X 轴比例修正，千分比；0 表示默认比例，100 表示增加约10%，不是输出乘零。需标定后确定。',
    'FLOW_FYSCALER': 'Y 轴比例修正，千分比；0 表示默认比例。不能根据质量分数直接计算。',
    'RNGFND1_TYPE': '第一个测距传感器的驱动类型；10 为 MAVLink。类型需匹配模块输出。',
    'RNGFND1_ORIENT': '第一个测距传感器的朝向枚举；25 为朝下，不是25度。',
    'RNGFND1_GNDCLEAR': '飞机落地时传感器到地面的安装高度，厘米；应实测，不是最小测量距离。',
    'RNGFND1_MIN_CM': '允许使用的最小测距，厘米；需与硬件规格一致。新固件可能改为以米为单位的 MIN。',
    'RNGFND1_MAX_CM': '允许使用的最大测距，厘米；800=8米。应核对模块实际量程，不能套用其他型号。',
    'RNGFND1_MIN': '新版参数：允许使用的最小测距，米。旧版可能不存在，缺失显示 N/A。',
    'RNGFND1_MAX': '新版参数：允许使用的最大测距，米；不要与 MAX_CM 的厘米值直接比较。',
    'EK3_FLOW_I_GATE': '光流创新检查门限，以百分之一标准差表示；300 对应3倍标准差。不是质量最低值。',
    'EK3_FLOW_M_NSE': '光流观测噪声参数，rad/s；影响融合权重，需要有依据地标定。',
    'EK3_FLOW_DELAY': '光流观测延迟补偿，毫秒。不是串口刷新周期。',
    'EK3_MAX_FLOW': 'EKF 使用的最大光流角速率，rad/s；不是最大飞行速度 m/s。',
    'SERIAL4_BAUD': 'SERIAL4 波特率编码；115 表示115200。这里显示编码，不是实际每秒115位。',
    'SERIAL4_PROTOCOL': 'SERIAL4 使用的通信协议；1=MAVLink1，2=MAVLink2。端口号不等同于电脑 COM4。',
    'SERIAL4_OPTIONS': 'SERIAL4 的选项位掩码；多个串口选项可组合，需按对应固件定义核对。',
    'ARMING_CHECK': '解锁检查位掩码；1 通常表示全部检查，其他整数可能是多个单项检查的组合。不是检查次数。',
    'MOT_PWM_TYPE': '电机输出协议；决定输出记录能否按 PWM 微秒解释。输出指令不是电机实际转速。',
}
HEADERS = {
    '当前':'最近一次有效样本；超过有效期则 N/A。不是平均值。',
    '当前值':'最近一次有效样本；超过有效期则 N/A。',
    '1秒均值':'最近1秒样本的算术平均，减轻单点跳动。',
    '5秒均值':'最近5秒样本的算术平均，变化比当前值慢。',
    '5秒标准差':'最近5秒波动大小；小表示平稳，不表示准确，也不能排除冻结。',
    '5秒最大':'最近5秒样本中的最大值。', '5秒最小':'最近5秒样本中的最小值。',
    'Parameter':'飞控参数名称；鼠标悬停可查看用途及单位。所有参数只读。',
    '实时读取':'当前连接会话最近读到的参数；读取时间不是飞控参数修改时间。',
    '日志末次值':'打开的 BIN 中该参数最后一次记录值；不保证等于飞控现在的配置。',
    '对比':'只比较同名参数的数值；差异不等于配置错误，缺失不当作零。',
    'Description':'参数的简短中文解释；具体枚举请以当前固件为准。',
    'Log ID':'飞控内部日志编号，不是起飞次数。', 'Size (bytes)':'日志文件字节数，不是记录条数。',
    'Date/Time (UTC)':'UTC 时间；飞控时间未同步时显示 N/A，不能猜测飞行日期。',
    '单位':'数值的计量单位；rad/s 是角速率，m/s 是平移速度，deg 是角度。',
    '数据来源':'当前数值使用的消息/字段，速度优先使用 LOCAL_POSITION_NED，无可用值时才显示 GLOBAL_POSITION_INT。',
    '样本距今':'最近样本距今时间；过期只表示没有新鲜数据，不能直接断言传感器损坏。',
}
CONTROLS = {
    'EKF core':'选择日志中的 EKF 实例；0 是第一个。切换后诊断与曲线使用同一实例。',
    'RFND实例':'选择测距实例；0 通常对应 RNGFND1，不是关闭传感器。',
    '打开本地 BIN':'读取电脑上的 DataFlash 日志，无需连接飞控。',
    '全程诊断':'覆盖完整 Loiter 段，并对解锁、模式、急停、融合和异常事件建立局部证据窗口。',
    'Loiter Diagnosis':'生成候选异常报告；不能把阈值告警当作确定根因。',
    '恢复全局视图':'恢复有连续传感器数据的时间范围，不把末尾重复状态文字的空白时间拉入曲线。',
    '自动缩放Y':'按当前可见时间段的已勾选曲线调整纵轴；不修改原始数据。',
    '上一事件':'跳到上一个事件，并显示事件前后各8秒。',
    '下一事件':'跳到下一个事件，并显示事件前后各8秒。',
    '重新读取参数':'重新向当前飞控请求参数，只读；未返回参数保持 N/A。',
    '刷新串口':'枚举电脑串口，不会解锁或控制飞机。',
    '连接飞控':'通过选定串口建立只读 MAVLink 连接；同一串口不能被其他地面站同时占用。',
    '断开':'断开本软件的串口连接，不向飞控发送锁定或急停指令。',
    '开始保存实时 CSV':'记录之后接收到的实时遥测；与打开的历史 BIN 是不同的数据来源。',
    '导出 TXT / CSV / HTML':'导出诊断证据、事件与阈值；不是导出或修改飞控参数。',
    '取消后台任务':'请求停止当前解析或诊断，等待后台线程清理，不删除原始日志。',
    '重新测试':'清空本轮方向测试采样，保留飞控配置。',
}
ALIASES = {'Flow X':'flow_x','Flow Y':'flow_y','Optical Flow X':'flow_x','Optical Flow Y':'flow_y',
           'Quality 0..255':'quality','Range / m':'range','RangeFinder':'range','VX 北':'vx','VY 东':'vy','VZ 下':'vz',
           'EKF flags':'ekf_flags','Battery':'battery_v','Vibration X':'vibe_x','Vibration Y':'vibe_y','Vibration Z':'vibe_z'}

def parameter_help(name):
    if name in PARAMETERS: return PARAMETERS[name]
    if name.startswith(('FLOW_POS_','RNGFND1_POS_')):
        return '传感器相对机体参考位置的偏移，米；X 向前、Y 向右、Z 向下。需按实际安装测量。'
    if re.fullmatch(r'RC\d+_TRIM',name): return '该遥控通道的校准中位，微秒；不能对所有通道一律假定1500。'
    if name.startswith('RCMAP_'): return '该控制轴对应的遥控输入通道编号，从1开始；用于解释 RCIN。'
    return config.PARAMETERS.get(name,'此参数尚无内置解释；请按当前固件版本核对官方定义。缺失值不是零。')

def signal_help(name):
    name=ALIASES.get(name,name).lower()
    if name.startswith('ekf_') and name[4:] in SIGNALS: return 'EKF 姿态估计。'+SIGNALS[name[4:]]
    if name.startswith('vibe_'): return '该轴振动指标，m/s²；持续超过约30需关注，急停/撞击后的尖峰应单独解释。'
    if name.startswith('gyro_') or name.endswith('speed'): return '机体转动角速率，rad/s；用于识别旋转，不是平移速度。'
    if re.fullmatch(r'rc\d+',name): return '遥控输入，通常以微秒记录；具体控制轴由 RCMAP/RCx_OPTION 决定，中位以 RCx_TRIM 为准。'
    if re.fullmatch(r'out\d+',name): return '飞控输出指令；功能由 SERVOx_FUNCTION 决定，单位取决于输出协议，不是实际电机转速。'
    if name.startswith(('flow_rate_','flow_rad_','flow_raw_')):
        if name.endswith('quality'): return SIGNALS['quality']
        if name.startswith('flow_raw_'): return 'OPTICAL_FLOW 原始整数，协议单位 dpix；不能直接套用 rad/s 的阈值或换算速度。'
        return SIGNALS.get('flow_'+name[-1],'光流角速率，rad/s。')
    return SIGNALS.get(name,'')

def help_for(text):
    return HEADERS.get(text) or CONTROLS.get(text) or signal_help(text) or (parameter_help(text) if text in config.PARAMETERS else '')

def tooltip(text):
    return '<qt><p style="white-space:pre-wrap; max-width:360px">'+html.escape(text)+'</p></qt>' if text else ''

def install_help(root):
    from PySide6.QtWidgets import QLabel,QPushButton,QCheckBox,QComboBox,QProgressBar,QTabWidget
    for widget in root.findChildren((QLabel)) + root.findChildren(QPushButton) + root.findChildren(QCheckBox):
        if not widget.toolTip(): widget.setToolTip(tooltip(help_for(widget.text())))
    for bar in root.findChildren(QProgressBar):
        if not bar.toolTip(): bar.setToolTip('任务进度；100%表示该任务完成，不表示飞控或光流健康。')
    for tabs in root.findChildren(QTabWidget):
        for i in range(tabs.count()):
            tabs.setTabToolTip(i,{'BIN / Loiter':'历史日志曲线、事件与诊断；不代表当前飞控状态。','参数只读':'参数解释、实时与日志对比；不会写入飞控。','地面检查':'拆桨、锁定后的分步采样；结果是证据，不是准飞证明。'}.get(tabs.tabText(i),tabs.tabText(i)+'：悬停在字段或控件上查看说明。'))
