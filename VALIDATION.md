# 本机验收记录

## 2026-09-14 功能改进验收（最新）

- 已实现：中文字段/参数/表头/控件悬停提示，历史游标逐行解释，参数搜索、实时与日志末次值对比及CSV导出，断开快照标识。
- 十三组同步曲线；目标俯仰默认可见、航向独立，横轴固定秒数，可见区自动缩放Y；事件下拉列表、前后导航、输入时间定位。
- 全部Loiter段覆盖至退出或连续数据末尾；全程事件包含模式、解锁、急停、融合、速度/目标姿态异常，以及已核对4.6.3的离地/落地判定与估计重置。未知版本不猜NI缩放。
- 地面检查七步采样、前提/失联/旋转校验、质量不足保留结论、JSON证据导出；实时/历史来源明确分区。
- 24项单元与协议测试全部通过。模拟异常堆栈是故障注入的预期结果。
- `tests/gui_smoke.py`：真实log_0011后台解析、诊断、游标点击、十三图联动和关闭清理均通过；最大定时器间隔约234ms。
- `tests/gui_improvements.py`：真实log_0012离线回归全部通过，提取90个时间线事件；覆盖78.292s开始的完整Loiter段，找到93秒附近目标俯仰异常及光流融合警告。
- 验证了数值单元格与参数名均有解释，原生Qt悬停气泡正常显示，搜索和断开参数快照标识正确。用于测试对比的合成参数值在截图前已清空；未发送到飞控。
- GUI使用真实Qt事件循环离屏验收，加载本机字体后检查截图；log_0012解析/诊断期间100ms定时器最大间隔约140ms，没有未处理异常或退出后遗留线程。
- 本次未连接真实串口、未改变飞控参数、未执行物理搬动或飞行；地面动作仍需操作者实测。没有增加依赖或修改全局配置。
- 机器可读结果、界面截图、tooltip截图和新版log_0012 TXT/CSV/HTML报告：`F:\codex_pro\outputs\ardupilot_analyzer\data\upgrade_validation`。
- 关闭原来的上位机窗口，再双击 `F:\codex_pro\outputs\ardupilot_analyzer\start.bat` 即加载新版；普通启动不自动连接飞控。

以下为此前版本的历史验收记录，旧诊断窗口和图组数量不代表新版行为。

日期：2026-09-13（Asia/Shanghai）。这是实测记录，不是模拟数据生成的飞控结果。

## 环境

- Windows / Python 3.10.10 x64。
- 项目：`F:\codex_pro\outputs\ardupilot_analyzer`。
- 虚拟环境：项目内 `.venv`；PySide6 6.11.2、pymavlink 2.4.49、pyserial 3.5、numpy 2.2.6、pandas 2.3.3、pyqtgraph 0.14.0。
- `pip check`：No broken requirements found。

## 真实硬件

- 枚举发现COM15：ArduPilot MAVLink，VID1209/PID5740，Manufacturer ArduPilot Project；同时发现COM14 SLCAN及4个蓝牙串口。
- COM15 @115200 实际连接成功，多次断开/重连成功。
- Heartbeat：system=1 / component=1，Vehicle QUADROTOR，Autopilot ArduPilot；固件4.6.3。
- 测试时状态DISARMED、模式LAND。软件没有改变该状态/模式。
- 实際收到：HEARTBEAT、ATTITUDE、GLOBAL_POSITION_INT、LOCAL_POSITION_NED、VFR_HUD、SYS_STATUS、SERVO_OUTPUT_RAW、RC_CHANNELS、RANGEFINDER、DISTANCE_SENSOR、OPTICAL_FLOW、EKF_STATUS_REPORT、VIBRATION、AUTOPILOT_VERSION、STATUSTEXT。
- OPTICAL_FLOW_RAD没有收到，因此不声称此消息的真实硬件链路已验证；积分转换有单元测试。
- 截图时RangeFinder=0.140m（14cm），光流Quality约35/255。是静态测试某时刻的读数，不能直接用于解释飞行故障。
- MAVLink2角光流扩展已实际显示rad/s，避免旧整数栏截断小数导致误显示。
- 参数读回确认：AHRS_EKF_TYPE=3、EK3_SRC1_VELXY=5、FLOW_TYPE=5、FLOW_ORIENT_YAW=0、SERIAL4_PROTOCOL=1、SERIAL4_BAUD=115、SERIAL4_OPTIONS=1024、RNGFND1_MIN_CM=1、RNGFND1_MAX_CM=800。
- EK3_SRC1_POSZ读回2；这仅是记录，未修改任何参数。RCMAP_ROLL/PITCH=1/2，RC1_TRIM=1500，RC2_TRIM=1496。

## 日志下载与解析

- 真实飞控返回12条LOG_ENTRY；未授时的1980/0日期显示N/A。
- 下载已结束的第11条日志 `logs/log_0011.BIN`。
- 预期及最终覆盖字节数均 **6,217,346**，实际文件长度一致。
- 平均下载速度约 **145.7 KiB/s**，整个下载约41.7秒；115秒硬件验收进程中同时接收遥测和写CSV。
- 没有丢失块遗留或下载错误，部分包/重复包/重传/超时另外用故障测试覆盖。
- pymavlink解析得到 **171,215条记录、73类消息、300.217秒**。
- 自动识别2个Loiter段。第1段开始时已处于Loiter，报告明确无法确认真实切入；第2段记录切入约5.444秒。
- 输出真实数据报告：`data/log_0011.diagnosis.txt`、`.csv`、`.html`。
- 窗口内质量低、方向/比例证据不足时输出LOW或Insufficient Data；不把这份日志认定为用户所述事故，也不编造“接反”结论。

## GUI与异常验证

- GUI多次实际启动、截图、关闭；最后一次启动保留供用户操作。
- 使用真实BIN运行后台解析和诊断，通过QTest点击Loiter按钮与图上时间点。
- 9组图同步到完全相同的2–16秒范围，游标明细更新，报告可导出。
- GUI100ms定时器在解析期间最大间隔 **125ms**（一次实测），修复前曾超过2秒。
- 关闭后没有仍运行的解析/诊断线程。
- 18项单元/协议测试通过；包含禁止控制发送、串口占用提示、Heartbeat缺失/超时、模拟USB断线和重连、下载缺口重传/乱序/重复包/大小校验/超时保留part、不覆盖旧BIN、无效积分时间、MAVLink1扩展补零、陈旧数据、方向轴约定、角度环绕、EKF lane隔离、缺字段与损坏文件。
- 单元测试输出中的模拟异常堆栈是故障注入的预期记录，测试全部OK。

## 尚需操作者参与

- 未执行物理USB拔插；已用故障注入覆盖相应清理和重连路径。
- 未搬动飞机执行四方向测试，也未飞行/产生新日志。
- 未证明本机日志对应所述冲飞事件。自动检查窗口为Loiter切入前3秒/后10秒，之后持续Loiter内部发生的异常须使用全局曲线另行定位。
- 不提供飞行安全认证。方向与比例判断需要有效数据、地面纹理和独立运动证据。

截图与机器可读验收证据位于 `docs/qa/`；高频遥测保存在 `data/telemetry_*.csv`。
