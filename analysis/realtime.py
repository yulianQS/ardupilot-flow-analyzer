"""GUI线程独占有界历史。用接收单调时间统计，不混合传感器不同时钟。"""
from collections import defaultdict, deque
import math
import numpy as np
import config
from mavlink.message_handler import MessageHandler

class RealtimeStore:
    def __init__(self):
        self.handler = MessageHandler()
        self.history = defaultdict(lambda: deque(maxlen=config.HISTORY_MAX))
        self.latest = {}
        self.message_times = {}
        self.raw_messages = {}
        self.start = None

    def add(self, timestamp, kind, data):
        if self.start is None:
            self.start = timestamp
        self.message_times[kind] = timestamp
        self.raw_messages[kind] = data
        for name, value in self.handler.values(kind, data).items():
            self.latest[name] = (timestamp, value)
            samples = self.history[name]
            samples.append((timestamp, value if value is not None else math.nan))
            while samples and timestamp - samples[0][0] > config.HISTORY_S:
                samples.popleft()

    def get(self, name, now):
        timestamp, value = self.latest.get(name, (0, None))
        return value if now - timestamp <= config.STALE_S else None

    def window(self, name, now, duration):
        values = [(t, v) for t, v in self.history.get(name, ()) if t >= now-duration and np.isfinite(v)]
        return np.array(values, dtype=float).reshape(-1, 2)

    def flow_source(self, now):
        if self.get('flow_rate_quality', now) is not None:
            return 'flow_rate', 'rad/s'
        if self.get('flow_rad_quality', now) is not None:
            return 'flow_rad', 'rad/s'
        return 'flow_raw', 'dpix'

    def stats(self, name, now):
        recent = self.window(name, now, 5)
        if len(recent) == 0 or self.get(name, now) is None:
            return [None] * 5
        one = recent[recent[:,0] >= now-1, 1]
        return [float(np.mean(one)) if len(one) else None, float(np.mean(recent[:,1])),
                float(np.std(recent[:,1])), float(np.max(recent[:,1])), float(np.min(recent[:,1]))]

    def static_warning(self, now, armed):
        if armed is not False:
            return '信号波动检查：仅 DISARMED 时评估'
        for axis in ('roll','pitch','yaw'):
            samples = self.window(axis, now, config.STATIC_WINDOW_S)
            if len(samples) < config.STATIC_MIN_SAMPLES or self.get(axis, now) is None:
                return '信号波动检查：证据不足（姿态样本不足）'
            values = np.degrees(np.unwrap(np.radians(samples[:,1]))) if axis == 'yaw' else samples[:,1]
            if np.std(values) > config.STATIC_ATTITUDE_STD_DEG:
                return '信号波动检查：姿态尚未稳定'
        prefix, unit = self.flow_source(now)
        threshold = config.STATIC_FLOW_STD_RAD_S if unit == 'rad/s' else config.STATIC_FLOW_STD_DPIX
        for axis in 'xy':
            samples = self.window(prefix + '_' + axis, now, config.STATIC_WINDOW_S)
            if len(samples) < config.STATIC_MIN_SAMPLES or samples[-1,0]-samples[0,0] < config.STATIC_WINDOW_S * 0.8:
                return '信号波动检查：证据不足（光流采样不足5秒）'
            if np.std(samples[:,1]) > threshold:
                return '光流波动超过本地阈值；可能是平移、旋转或噪声，姿态稳定不能证明位置静止。'
        return '信号波动检查：未超本地阈值；不能据此证明位置静止或测量准确。'
