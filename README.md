# ArduPilot 光流分析与飞控诊断工具

Windows 飞控只读诊断上位机，面向 Pogo-CANFCU-Mini、ArduCopter 4.6.3、MTF02P 光流 + ToF 测距及室内 Loiter 问题。支持 USB/MAVLink 遥测、飞控 DataFlash 日志下载、本地 BIN 解析、同步曲线与有证据的 Loiter 筛查。

项目实体：`F:\codex_pro\outputs\ardupilot_analyzer`。当前工作区中的 `ardupilot_analyzer` 目录映射至此。所有项目日志、CSV、报告和虚拟环境均位于 F 盘。

## 安装和运行

要求 Windows 10/11、64位 Python 3.10+。本机已创建 `.venv` 并安装依赖。

直接双击 **start.bat**，或在 PowerShell 执行：

```powershell
cd F:\codex_pro\outputs\ardupilot_analyzer
.\.venv\Scripts\python.exe main.py
```

从零安装：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python main.py
```

若 PowerShell 禁止激活脚本，无须修改系统执行策略：

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe main.py
```

CMD 激活方式：`.venv\Scripts\activate.bat`。`requirements-lock.txt` 保存本机验收时的完整依赖版本；需要精确复现时安装该文件。只使用 PySide6，不混用 PyQt。

## 连接与实时数据

1. **Mission Planner 必须先断开 COM15，否则程序可能无法连接飞控。** 本工具不会关闭其他程序或抢占端口。
2. 点击“刷新串口”，查看端口、设备描述、VID/PID 和 Manufacturer。优先选择 COM15，也可手动填写其他端口。默认115200。
3. 点击“连接飞控”。5秒内收到合法飞控 HEARTBEAT 后显示 CONNECTED、系统/组件ID、固件、Vehicle、ARMED/DISARMED和模式。
4. 实时数据页显示姿态、NED速度、光流、质量、测距、EKF标志、振动、电池；右侧保留实际收到的 MAVLink 字段。无GPS或某消息缺失时为 N/A。
5. 超过2秒未更新的测量显示 N/A；Heartbeat超过5秒关闭连接。拔线异常会记录在 `app.log` 和界面事件区。点击连接可重连。
6. “开始保存实时 CSV”将每条接收到的遥测写入 `data/telemetry_时间.csv`，包含UTC、单调接收时间、源ID、消息类型和字段JSON。保存运行在串口线程，停止或断开后刷新并关闭文件。LOG_DATA二进制包不重复写CSV。

普通启动不会自动连接；`python main.py --connect COM15` 是显式连接选项。

### 光流字段的关键区别

- 通用 `OPTICAL_FLOW.flow_x/y` 定义为 dpix；**Copter 4.6.3 的发送实现把角速率传进了整数栏，小于1的角速率可能被截成0**。该栏仅作兼容原始数据显示，不能用于可靠的小幅漂移定量分析。
- 确认收到固件版本4.6.3且使用 MAVLink 2 后，本程序优先选用 `OPTICAL_FLOW.flow_rate_x/y` 扩展字段（rad/s）。MAVLink 1 不把扩展补零当作有效数据。
- `OPTICAL_FLOW_RAD.integrated_x/y` 单位rad，除以积分时长（us转s）后才是rad/s；积分时长0显示N/A。
- ArduPilot 4.6.3 的 `flow_comp_m_x/y` 实际为角流减机体角速率，不能盲目按字段名称当作m/s。程序保留原始字段，但不将其作为机体速度。
- BIN中的 `OF.flowX/flowY/bodyX/bodyY` 由 DataFlash 格式解析，单位rad/s。
- 不同消息来源使用独立缓存，绝不把dpix和rad/s拼成一条统计曲线。其他固件的扩展语义需核对后再增加适配。

## MTF02P 与方向测试

MTF02P页给出X/Y、Quality和Range的当前值、1秒均值、5秒均值、5秒标准差及最大/最小值。Quality为0是有效的“无质量”读数，不能当成缺消息。

信号波动检查要求已确认DISARMED、连续姿态稳定和足够光流样本。**姿态稳定不能证明飞机没有被水平搬动**，波动小也不能证明测量准确。Quality不是准确率，LOW是本地阈值提示，不是EKF融合门限。

Optical Flow Direction Test按“前、后、右、左”分别记录3秒，按钮点击后开始采样。需要操作者实际保持水平平移、无旋转、DISARMED和足够质量；本程序不会控制飞机。选择正确来源，四步必须使用同一来源。可随时重新测试。

方向测试与“地面检查”页各有独立的动作采样质量门限，默认30，可在1–255间调整。质量约45时可先用30观察响应；这只是排查起点，不是设备合格线。开始后整轮锁定门限，修改需先重置该页测试。质量0不参与方向判断。结果显示质量范围、中位数、对齐及保留样本数；低于原100参考值仍保留提示。地面检查导出保留原始样本，并在原有 `quality_local_threshold` 字段记录本轮实际门限。离线报告的100参考门限保持独立。

角度与转动速度检查仍生效：横滚/俯仰不超过±10°，各轴角速度不超过±0.1rad/s。采样中出现超限或数据超过2秒未更新时，会显示具体字段、超限读数或缺失原因，整步仍需重做。门限降低不消除全零、反向动作无响应、信号太弱等问题，也不代表允许起飞。

标准角光流的水平平移约定是：**向前→+Y角流，向右→−X角流**。这并不表示X/Y接反。只有存在足够激励、相反动作符号一致且来源约定已知时，才提示交换/反向候选。dpix来源只报告观测轴，无法可靠确认符号。

提示可能检查 `FLOW_ORIENT_YAW`，绝不会自动修改。没有做真实移动测试时，不会声称已完成方向校准。

## RangeFinder

显示cm和m及实时曲线。默认自动锁定第一个朝下（orientation=25）的 `DISTANCE_SENSOR`，不混入朝侧方的距离。

健康筛查包括No Data、Data Lost、Out of Range、跳变和固定值。实时量程优先使用消息的min/max，诊断默认量程集中在config.py。固定值在静止平面上可能完全正常，需要实际改变高度后判定。

其他 `RANGEFINDER` 和 `OPTICAL_FLOW.ground_distance` 保留原始字段，不能自动替代选定的真实朝下测距，以免混入EKF高度估计。

## 飞控日志下载

1. 确认DISARMED，在“飞控日志”页点击“刷新日志列表”。
2. 选择一条日志，点击“下载选中日志”，或按协议 `last_log_num` 下载最新日志。
3. 显示唯一收到字节数、总大小、百分比和平均速度。
4. 文件位于 `logs/log_XXXX.BIN`；同名存在时添加后缀，不覆盖已有数据。未完成文件为 `.BIN.part`。
5. 完成后点击“打开已下载BIN”。取消或USB中断保留部分文件，重新下载时创建新文件；当前版本不跨进程续传。

实现有限字节窗口、乱序处理、重复包去重、缺口重请求与有限超时重试。只有整个预期范围的每个字节均收到且实际大小一致才重命名为BIN。`LOG_ENTRY.size`可能近似；当前日志若还在增长，不能保证一次下载覆盖之后新增内容，建议下载已经结束的日志。

没有GPS授时时常见1980默认日期，表格显示N/A，不作为真实飞行日期。列表为空与列表超时明确区分。

日志协议在某些固件上可能临时停止机载日志写入，因此日志枚举/下载限定DISARMED，正常结束、取消及连接结束时发送 `LOG_REQUEST_END` 恢复常规日志行为。运行期间检测到ARMED也会停止日志传输。

## 本地 BIN、联动图和 Loiter 诊断

“打开本地 BIN”调用pymavlink DataFlash解析器，先扫描实际格式与类型，再保留可分析数据。解析与诊断均使用QThread，可取消；大型日志每1000条让出执行权，保持GUI响应。

支持OF、RFND、XKF/NKF家族、ATT、IMU、VIBE、MODE、RCIN/RCOU、BARO、MAG、GPS、ERR、EV、MSG、PARM、ARM等；“消息与字段”展示实际存在的消息。缺少某字段不导致崩溃。当前内存保护上限是400万条记录，超过明确报错，可在config.py调整。

时间使用TimeUS或TimeMS，所有曲线减去同一个日志起点；无时间戳消息只计数，不伪造时间。检测到明显时钟回退时停止自动事件诊断，避免跨重启拼接。

十三组图：光流、质量、光流融合一致性、测距、测距状态、EKF速度、目标与实际横滚/俯仰、独立航向、振动、RC输入、输出、解锁状态、模式。目标俯仰默认显示，航向不再压扁俯仰曲线。滚轮缩放、拖动平移、曲线复选框、可见范围自动缩放Y和恢复全局视图均可用。各图X轴同步，横轴固定用秒，不自动切换ks。

默认时间范围取连续信号范围，文件末时刻另外标出，不把状态文字尾段当作飞行时长。事件下拉框、“上一事件/下一事件”或输入秒数可定位前后8秒；首张曲线标记视野内最多40个事件，全部事件保留在列表和报告。Copter4.6.3可解释离地/落地、急停、估计重置与源组切换EV事件，其他版本保留未确认定义，不能把飞控离地判定当作独立物理证据。

光流融合图在已确认Copter4.6.3时显示XKF5.NI/100，约1为检查边界、2.55为截顶；未知版本不猜倍率，原始flow_norm和创新值仍保留。质量、测距状态与融合结果分别展示。

点击曲线或拖动竖线同步时间游标，右侧列出该时刻数据。连续量取±0.5秒内最近实际样本；模式/ARM状态使用此前最近记录。跨大空洞不插值，不把空洞连接成连续轨迹。诊断使用完整原始样本，绘图仅显示降采样。

EKF lane与RFND实例可以选择，默认0。实例切换后旧诊断清空。报告注明主lane与所选lane；不会把不同lane拼在一起。RC图默认为RC1/RC2，当前验收飞机映射确为1/2；自动RC诊断独立读取每次事件对应的RCMAP与TRIM，不假定1500中位。

点击“全程诊断”识别Copter MODE=5并覆盖完整Loiter段，直至退出或连续数据末尾。另列全程解锁、模式、急停、融合变化、目标姿态和速度异常事件，每个事件附同刻读数与前3秒/后8秒局部证据。日志第一条已在Loiter时仍说明切入时刻未知。全段极值可能出现在急停之后，需结合时间线判断，不能直接当作起因。

报告覆盖用户要求的18项筛查，包含实际字段、数值、时刻、阈值和复核建议。缺少数据、坐标变换前提不满足、质量不足或激励不足，明确写Insufficient Data。不会输出未经标定的事故概率，也不会仅凭相关性断定根因。

坐标换算：Body X机头/Y右/Z下；NED X北/Y东/Z下。近水平且有body角速率、有效测距、质量和yaw时，才由角流估计机体速度，再转NED与EKF比较。EKF可能正在融合该光流，因此不能把EKF当作独立真值。比例/反向/正反馈仅给候选，不生成新参数值。

“导出 TXT / CSV / HTML”默认保存至data；报告包含阈值快照。CSV按事件和检查逐行保存。HTML为离线静态报告。

## STATUSTEXT 和参数

STATUSTEXT/PreArm页保存最近1000条，支持关键词、severity过滤与复制。MAVLink2分块消息保留id/seq，避免缺块时拼成看似完整文本。

参数只读表支持请求清单内所有配置，包括用户列出的EKF3、FLOW、RNGFND1、SERIAL4、ARMING_CHECK和诊断所需RC映射/中位。不存在的旧版/新版量程字段有限重试后N/A；不会自动替换或写入参数。

参数名、参数数值、统计表头、曲线复选框和主要控件都有中文悬停说明。参数页支持名称/中文搜索、当前会话读取与日志末次值比较、参数对比CSV导出。断开连接后保留读数但明确标为断开快照；重连或重新读取清空实时栏，日志栏独立保留。差异只表示数值不同，不表示应该改参。右侧实时健康与历史BIN游标分别标识；悬停历史字段行可读解释。

## 地面检查向导

“地面检查”页提供七步：改变高度、前/后/右/左平移、缓慢旋转、放回静置。拆桨确认、连接和DISARMED满足后，每步采集5秒；失联、状态变化、平移时明显转动或必要数据过期将使当前步骤无效。完成后可导出含原始采样、动作和结论的JSON。

方向结论需要同一光流来源、已确认单位和本地质量门限筛选后的足够样本；质量不足时保留结论。旋转步骤记录响应，但不能仅用现有遥测宣称补偿已校准；静置依赖操作者确认，软件不从姿态平稳推断位置静止。所有动作由操作者执行，程序不发控制命令。

## 只读发送边界

唯一发送入口是 `mavlink/safety.py` 的 `ReadOnlyLink`，白名单仅：

- REQUEST_DATA_STREAM（请求本连接遥测，不写SRx参数）
- PARAM_REQUEST_READ
- AUTOPILOT_VERSION_REQUEST
- LOG_REQUEST_LIST / LOG_REQUEST_DATA / LOG_REQUEST_END

没有ARM/DISARM、模式切换、参数写入、电机测试、Servo设置、RC Override、COMMAND_LONG/INT、任务上传或LOG_ERASE接口。也不发送GCS心跳来冒充飞行控制站。读取并显示ARMED状态与主动解锁是不同操作。

## 配置、日志与结构

所有诊断阈值集中于config.py，并注明单位及适用前提。它们是筛查初值，不是飞行安全界限。修改本地阈值后需重新启动。

```text
main.py / config.py / requirements.txt / requirements-lock.txt / start.bat
gui/       连接、实时、MTF02P、RangeFinder、日志、诊断、参数、STATUSTEXT页面
mavlink/   只读发送、单线程串口、字段转换、参数重试、日志下载
analysis/  DataFlash解析、实时缓存、测距、方向、坐标转换、Loiter报告
widgets/   实时曲线、十三组同步时间轴、字段悬停说明
logs/      下载的真实BIN及未完成.part
data/      遥测CSV和诊断报告
tests/     单元测试、GUI验收和显式硬件只读验收脚本
```

app.log采用2MB轮转、保留3份，记录连接、解析、下载、诊断和异常，不写所有高频遥测。关闭时发停止请求，Qt保持响应直到串口和后台任务结束；不会强制terminate线程。

## 验证

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe main.py --smoke-seconds 5
.\.venv\Scripts\python.exe tests/gui_smoke.py
.\.venv\Scripts\python.exe tests/gui_improvements.py
```

GUI验收使用本次下载的 `logs/log_0011.BIN`，检查后台解析、图表范围、游标、报告导出和线程退出。硬件测试不会自动随单元测试运行：

```powershell
.\.venv\Scripts\python.exe tests/hardware_probe.py --port COM15 --seconds 20 --output F:\codex_pro\work\ardupilot_analyzer\probe.json
```

当前实际验收结果见 `VALIDATION.md`。USB物理拔插与人为搬动方向测试需要操作者参与，当前以故障模拟验证断线恢复逻辑，不冒充已做物理拔插。

2026-09-14改进验收使用log_0012，报告和截图在 `data/upgrade_validation/`；新代码在关闭旧窗口并重新双击start.bat后生效，无需重新安装依赖。

## 实现依据

- [MAVLink消息定义与日志读取协议](https://mavlink.io/en/messages/common.html)
- [ArduPilot光流测试文档](https://ardupilot.org/copter/docs/common-optical-flow-sensor-setup.html)
- [DataFlash字段参考](https://ardupilot.org/copter/docs/logmessages.html)
- [Copter-4.6.3光流遥测发送实现](https://github.com/ArduPilot/ardupilot/blob/Copter-4.6.3/libraries/GCS_MAVLink/GCS_Common.cpp)
- [Copter-4.6.3 EKF3光流测量符号转换](https://github.com/ArduPilot/ardupilot/blob/Copter-4.6.3/libraries/AP_NavEKF3/AP_NavEKF3_Measurements.cpp)
- [Copter-4.6.3 EKF3光流融合模型](https://github.com/ArduPilot/ardupilot/blob/Copter-4.6.3/libraries/AP_NavEKF3/AP_NavEKF3_OptFlowFusion.cpp)
- [Copter-4.6.3 日志事件编号](https://github.com/ArduPilot/ardupilot/blob/Copter-4.6.3/libraries/AP_Logger/AP_Logger.h)
- [pymavlink DataFlash解析器](https://github.com/ArduPilot/pymavlink/blob/master/DFReader.py)
