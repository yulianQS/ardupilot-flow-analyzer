"""集中配置：诊断阈值是筛查起点，不代表飞控安全边界，也不会写入飞控。"""
from pathlib import Path

ROOT = Path(__file__).resolve().parent
LOG_DIR = ROOT / 'logs'
DATA_DIR = ROOT / 'data'
DEFAULT_PORT = 'COM15'
BAUD = 115200
HEARTBEAT_TIMEOUT_S = 5.0
STALE_S = 2.0                 # 超过此时间的实时数据一律 N/A，禁止旧值假装在线。
GUI_INTERVAL_MS = 200        # GUI 5 Hz；接收和 CSV 仍保存每条数据。
HISTORY_S = 120.0
HISTORY_MAX = 12000          # 每字段有界缓存，防止长时间连接内存无限增长。
STATUSTEXT_MAX = 1000
FLOW_SENSOR_ID = 0
RANGE_SENSOR_ID = None       # None 自动锁定第一个朝下(25)测距；可明确填 MAVLink id。
DOWNWARD_ORIENTATION = 25
EKF_CORE = 0                 # 离线固定一个 EKF lane，界面可切换；禁止混合不同 lane。
RANGE_INSTANCE = 0           # 离线 RFND 实例，界面可切换。
VIBE_INSTANCE = 0
FLOW_QUALITY_MIN = 100       # MAVLink/OF Q 0..255；按地面纹理、光照和设备实测调整。
CAPTURE_QUALITY_MIN = 30     # 地面动作排查默认值，可在页面调整；不是飞行合格线。
RANGE_MIN_M = 0.01           # 本地筛查范围，与用户提供硬件配置对应，并非参数修改。
RANGE_MAX_M = 8.0
RANGE_JUMP_M = 0.40          # 相邻 <=0.5s 样本距离变化超过 40cm 提示跳变。
RANGE_JUMP_INTERVAL_S = 0.5
RANGE_FIXED_WINDOW_S = 5.0
RANGE_FIXED_EPS_M = 0.001    # 固定值只是提示；静止平面上固定值通常正常。
STATIC_WINDOW_S = 5.0
STATIC_MIN_SAMPLES = 15
STATIC_ATTITUDE_STD_DEG = 1.0
STATIC_RATE_MAX_RAD_S = 0.10
STATIC_FLOW_STD_RAD_S = 0.15 # 仅应用于已确认 rad/s 的角光流；dpix 不可套此阈值。
STATIC_FLOW_STD_DPIX = 40.0  # 原始像素量必须单独调阈值，不与 rad/s 拼接。
DIRECTION_CAPTURE_S = 3.0
DIRECTION_MIN_SAMPLES = 8
DIRECTION_MIN_RAD_S = 0.03
DIRECTION_MIN_DPIX = 5.0
DIRECTION_AXIS_RATIO = 1.8
DIRECTION_LEVEL_MAX_DEG = 10.0
BEFORE_LOITER_S = 3.0
AFTER_LOITER_S = 10.0
ALIGN_TOLERANCE_S = 0.20    # 跨消息对齐最大时间差；不跨大缺口插值。
CURSOR_TOLERANCE_S = 0.5
MIN_DIAG_SAMPLES = 5
FLOW_RATE_HIGH_RAD_S = 2.5
EKF_SPEED_HIGH_M_S = 2.0
EKF_SPEED_RISE_M_S = 1.5
ATTITUDE_HIGH_DEG = 20.0
YAW_JUMP_DEG = 25.0         # 相邻 <=0.5s；先 wrap 到 [-180,180)，避免359->0误报。
YAW_JUMP_INTERVAL_S = 0.5
VIBRATION_HIGH_M_S2 = 30.0
RC_NEUTRAL_US = 1500.0     # 未读到 RCx_TRIM 时不使用默认值给出 NEUTRAL 结论。
RC_DEADBAND_US = 80.0
OUTPUT_LOW_US = 1050.0      # 仅已确认 PWM 协议时评估饱和，DShot不能套PWM阈值。
OUTPUT_HIGH_US = 1950.0
OUTPUT_SATURATION_FRACTION = 0.30
EKF_TEST_RATIO_HIGH = 1.0
YAW_INNOVATION_HIGH_DEG = 15.0
VELOCITY_INNOVATION_HIGH_M_S = 1.0
FLOW_COMPARE_MIN_SPEED_M_S = 0.3
FLOW_COMPARE_MIN_SAMPLES = 20
FLOW_COMPARE_CORRELATION = 0.70
FLOW_COMPARE_IMPROVEMENT = 0.25
FLOW_SCALE_RATIO_LOW = 0.5
FLOW_SCALE_RATIO_HIGH = 2.0
POSITIVE_FEEDBACK_CORRELATION = 0.65
POSITIVE_FEEDBACK_ACCEL_M_S2 = 0.5
LOG_WINDOW_BYTES = 90 * 128
LOG_RETRY_S = 1.5
LOG_MAX_RETRIES = 8
LOG_LIST_TIMEOUT_S = 3.0
LOG_LIST_RETRIES = 3
PARAM_RETRY_S = 2.0
PARAM_MAX_RETRIES = 3
MAX_PARSE_RECORDS = 4_000_000 # 超限停止并给出原因，不静默丢弃记录作诊断。

PARAMETERS = {
    'EK3_ENABLE': 'EKF3 启用开关', 'EK3_IMU_MASK': 'EKF3 使用的 IMU 位掩码', 'EK3_PRIMARY': '首选 EKF 实例',
    'RNGFND1_GNDCLEAR': '落地时传感器离地高度 cm',
    'EK3_FLOW_I_GATE': '光流创新检查门限', 'EK3_FLOW_M_NSE': '光流观测噪声 rad/s',
    'EK3_FLOW_DELAY': '光流延迟 ms', 'EK3_MAX_FLOW': '最大光流角速率 rad/s',
    **{f'{prefix}_POS_{axis}': '传感器安装位置偏移 m' for prefix in ('FLOW','RNGFND1') for axis in 'XYZ'},
    'AHRS_EKF_TYPE': 'AHRS 使用的 EKF 类型（3 为 EKF3）',
    'EK3_SRC_OPTIONS': 'EKF3 数据源选项位掩码',
    **{f'EK3_SRC1_{axis}': f'EKF3 源组1 {axis} 数据源' for axis in ('POSXY','VELXY','POSZ','VELZ','YAW')},
    'FLOW_TYPE': '光流驱动类型', 'FLOW_ORIENT_YAW': '光流安装偏航角，centideg（0.01°）',
    'FLOW_FXSCALER': 'X 角光流比例修正，千分比', 'FLOW_FYSCALER': 'Y 角光流比例修正，千分比',
    'RNGFND1_TYPE': '测距驱动类型', 'RNGFND1_MIN_CM': '旧版最小量程 cm（新固件可能不存在）',
    'RNGFND1_MAX_CM': '旧版最大量程 cm（新固件可能不存在）',
    'RNGFND1_MIN': '新版最小量程 m', 'RNGFND1_MAX': '新版最大量程 m',
    'RNGFND1_ORIENT': '测距朝向，25 为朝下', 'SERIAL4_PROTOCOL': 'SERIAL4 协议',
    'SERIAL4_BAUD': 'SERIAL4 波特率编码，115=115200', 'SERIAL4_OPTIONS': 'SERIAL4 选项位掩码',
    'ARMING_CHECK': '解锁检查位掩码（只读）', 'RCMAP_ROLL': '横滚输入通道',
    'RCMAP_PITCH': '俯仰输入通道', 'MOT_PWM_TYPE': '电机输出协议（决定PWM阈值是否适用）',
    **{f'RC{i}_TRIM': f'RC{i} 中位 us' for i in range(1, 17)},
}
