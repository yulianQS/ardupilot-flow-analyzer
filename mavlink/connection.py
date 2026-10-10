"""单一 QThread 拥有串口、协议状态与文件；GUI 仅通过队列发起只读任务。

线程不直接修改任何 QWidget。接收批量通知每200ms一次，防止日志高速下载时
淹没 Qt 事件队列。Heartbeat 超时统一断开，重新连接总是新建线程和状态。
"""
import csv
import json
import logging
import queue
import time
from datetime import datetime, timezone
from PySide6.QtCore import QThread, Signal
from pymavlink import mavutil
from serial.tools import list_ports
import config
from mavlink.safety import ReadOnlyLink
from mavlink.parameter_reader import ParameterReader
from mavlink.log_downloader import LogDownloader
from mavlink.message_handler import MONITORED

def scan_ports():
    return [{'device': port.device, 'description': port.description,
             'vid': f'{port.vid:04X}' if port.vid is not None else 'N/A',
             'pid': f'{port.pid:04X}' if port.pid is not None else 'N/A',
             'manufacturer': port.manufacturer or 'N/A'} for port in list_ports.comports()]

class ConnectionWorker(QThread):
    state = Signal(str, object)
    messages = Signal(object)
    error = Signal(str)
    parameters = Signal(str, object)
    logs = Signal(object)
    download_progress = Signal(object)
    download_done = Signal(str)
    notice = Signal(str)

    def __init__(self, port, baud=config.BAUD, connection_factory=None):
        super().__init__()
        self.port, self.baud = port, baud
        self.factory = connection_factory or mavutil.mavlink_connection
        self.commands = queue.Queue(maxsize=100)
        self.download = None
        self.record_file = None
        self.listing = False
        self.armed = None

    def request(self, action, payload=None):
        if action not in ('parameters', 'logs', 'download', 'cancel_download', 'record'):
            raise PermissionError('只读任务不支持: ' + action)
        try:
            self.commands.put_nowait((action, payload))
        except queue.Full:
            self.error.emit('请求队列已满，请稍后重试')

    def stop(self):
        self.requestInterruption()

    def _end_list(self):
        if self.listing:
            self.listing = False
            self.link.send('log_request_end_send', self.system, self.component)

    def _actions(self):
        for _ in range(4):
            try:
                action, payload = self.commands.get_nowait()
            except queue.Empty:
                return
            try:
                if action == 'parameters':
                    self.reader.start()
                elif action in ('logs', 'download'):
                    # 日志协议可能影响机载日志写入，只允许已确认 DISARMED 时使用。
                    if self.armed is not False:
                        raise RuntimeError('飞控日志操作仅限 Heartbeat 已确认 DISARMED 时使用')
                    if self.download.active:
                        raise RuntimeError('请先完成或取消当前下载')
                    if action == 'logs':
                        self._end_list()
                        self.entries = {}
                        self.listing = True
                        self.list_attempts = 1
                        self.list_requested = time.monotonic()
                        self.link.send('log_request_list_send', self.system, self.component, 0, 65535)
                    else:
                        self._end_list()
                        self.download.start(payload['id'], payload['size'], config.LOG_DIR)
                elif action == 'cancel_download':
                    self.download.cancel()
                    self._end_list()
                elif action == 'record':
                    if self.record_file:
                        self.record_file.close()
                        self.record_file = None
                    if payload:
                        config.DATA_DIR.mkdir(parents=True, exist_ok=True)
                        path = config.DATA_DIR / ('telemetry_' + datetime.now().strftime('%Y%m%d_%H%M%S_%f') + '.csv')
                        self.record_file = path.open('x', encoding='utf-8-sig', newline='')
                        self.csv_writer = csv.writer(self.record_file)
                        self.csv_writer.writerow(['utc', 'receive_monotonic_s', 'source_system', 'source_component', 'message_type', 'fields_json'])
                        self.notice.emit('CSV 记录中: ' + str(path))
                    else:
                        self.notice.emit('CSV 记录已停止')
            except Exception as exception:
                logging.exception('只读任务失败')
                self.error.emit(str(exception))

    def run(self):
        connection = None
        batch = []
        self.state.emit('CONNECTING', {'port': self.port})
        logging.info('连接 %s @ %s', self.port, self.baud)
        try:
            connection = self.factory(self.port, baud=self.baud, source_system=254,
                                      source_component=190, dialect='ardupilotmega', autoreconnect=False)
            # pymavlink 内部串口写超时也有界，拔线时不能永久卡住退出。
            if hasattr(connection, 'port') and hasattr(connection.port, 'write_timeout'):
                connection.port.write_timeout = 0.5
            deadline = time.monotonic() + config.HEARTBEAT_TIMEOUT_S
            heartbeat = None
            while not self.isInterruptionRequested() and time.monotonic() < deadline:
                message = connection.recv_match(blocking=True, timeout=0.05)
                if (message and message.get_type() == 'HEARTBEAT' and
                    message.autopilot != mavutil.mavlink.MAV_AUTOPILOT_INVALID and
                    message.type != mavutil.mavlink.MAV_TYPE_GCS):
                    heartbeat = message
                    break
            if self.isInterruptionRequested():
                return
            if heartbeat is None:
                raise TimeoutError('5 秒内没有收到飞控 HEARTBEAT，请检查端口、USB 和 MAVLink 配置。')
            self.system, self.component = heartbeat.get_srcSystem(), heartbeat.get_srcComponent()
            connection.target_system, connection.target_component = self.system, self.component
            self.link = ReadOnlyLink(connection)
            self.reader = ParameterReader(self.link, self.system, self.component)
            self.download = LogDownloader(self.link, self.system, self.component, self.download_progress.emit,
                                          self.download_done.emit, self.error.emit)
            self.entries = {}
            # REQUEST_DATA_STREAM 不用 COMMAND_LONG，不写 SRx 参数。
            self.link.send('request_data_stream_send', self.system, self.component, mavutil.mavlink.MAV_DATA_STREAM_ALL, 10, 1)
            self.link.send('autopilot_version_request_send', self.system, self.component)
            self.reader.start()
            last_heartbeat = time.monotonic()
            last_emit = last_heartbeat
            message = heartbeat
            while not self.isInterruptionRequested():
                now = time.monotonic()
                if message is not None and message.get_srcSystem() == self.system and message.get_srcComponent() == self.component:
                    kind = message.get_type()
                    data = message.to_dict()
                    data['_wire_version'] = 2 if message.get_msgbuf()[0] == 253 else 1
                    if kind == 'HEARTBEAT':
                        last_heartbeat = now
                        self.armed = bool(message.base_mode & mavutil.mavlink.MAV_MODE_FLAG_SAFETY_ARMED)
                        logging.debug('Heartbeat %s armed=%s',self.system,self.armed)
                        self.state.emit('CONNECTED', {'port': self.port, 'system': self.system,
                            'component': self.component, 'type': message.type, 'autopilot': message.autopilot,
                            'armed': self.armed, 'mode': mavutil.mode_string_v10(message), 'heartbeat': now})
                        if self.armed:
                            self.download.cancel('检测到 ARMED，停止日志传输')
                            self._end_list()
                    if kind in MONITORED:
                        batch.append((now, kind, data))
                    if kind == 'PARAM_VALUE':
                        name = message.param_id
                        if isinstance(name, bytes):
                            name = name.decode('ascii', errors='replace')
                        name = name.rstrip('\x00')
                        self.reader.received(name)
                        self.parameters.emit(name, float(message.param_value))
                    elif kind == 'LOG_ENTRY' and self.listing:
                        if message.num_logs == 0:
                            self.logs.emit([])
                            self.notice.emit('飞控日志列表为空')
                            self._end_list()
                        else:
                            self.entries[int(message.id)] = data
                            self.logs.emit(list(self.entries.values()))
                            if len(self.entries) >= message.num_logs:
                                self._end_list()
                                self.notice.emit(f'日志列表完整：{len(self.entries)} 条')
                    elif kind == 'LOG_DATA':
                        self.download.accept(message)
                    if self.record_file and kind not in ('BAD_DATA', 'LOG_DATA'):
                        self.csv_writer.writerow([datetime.now(timezone.utc).isoformat(), f'{now:.6f}',
                            self.system, self.component, kind, json.dumps(data, ensure_ascii=False, default=str)])
                if now - last_heartbeat > config.HEARTBEAT_TIMEOUT_S:
                    raise TimeoutError('Heartbeat 超时：MAVLink 数据中断或 USB 已拔出。可重新连接。')
                if now - last_emit >= config.GUI_INTERVAL_MS / 1000:
                    if batch:
                        self.messages.emit(batch)
                        batch = []
                    self._actions()
                    for name in self.reader.tick(now):
                        self.parameters.emit(name, None)
                    if self.record_file:
                        self.record_file.flush()
                    last_emit = now
                self.download.tick(now)
                if self.listing and now - self.list_requested > config.LOG_LIST_TIMEOUT_S:
                    if self.list_attempts >= config.LOG_LIST_RETRIES:
                        self._end_list()
                        self.error.emit(f'日志列表超时/可能不完整，已收到 {len(self.entries)} 条')
                    else:
                        self.list_attempts += 1
                        self.list_requested = now
                        self.link.send('log_request_list_send', self.system, self.component, 0, 65535)
                message = connection.recv_match(blocking=True, timeout=0.03)
        except Exception as exception:
            logging.exception('连接或接收失败')
            detail = str(exception)
            if 'PermissionError' in detail or 'Access is denied' in detail or '拒绝访问' in detail:
                detail = f'{self.port} 可能被 Mission Planner 或其他程序占用，请先断开 Mission Planner。\n' + detail
            else:
                detail = f'{self.port}: {detail}'
            self.error.emit(detail)
        finally:
            if self.download:
                self.download.cancel('连接结束，未完成下载保留 .part')
            try:
                self._end_list()
            except Exception:
                logging.exception('结束日志列表失败')
            if self.record_file:
                self.record_file.close()
                self.record_file = None
            if connection:
                connection.close()
            if batch:
                self.messages.emit(batch)
            self.state.emit('DISCONNECTED', {'port': self.port})
            logging.info('连接关闭 %s', self.port)
