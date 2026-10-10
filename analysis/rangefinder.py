import numpy as np
import config

def range_health(store, now):
    value = store.get('range', now)
    if value is None:
        return 'RangeFinder Data Lost' if 'range' in store.latest else 'No Data — 未收到朝下 DISTANCE_SENSOR'
    minimum = store.get('range_min', now) or config.RANGE_MIN_M
    maximum = store.get('range_max', now) or config.RANGE_MAX_M
    if not minimum <= value <= maximum:
        return f'Out of Range ({minimum:g}–{maximum:g} m)'
    samples = store.window('range', now, config.RANGE_FIXED_WINDOW_S)
    if len(samples) >= 2:
        difference = np.abs(np.diff(samples[:,1]))
        interval = np.diff(samples[:,0])
        if np.any((difference > config.RANGE_JUMP_M) & (interval <= config.RANGE_JUMP_INTERVAL_S)):
            return 'WARNING: RangeFinder 突然跳变'
    if len(samples) >= config.STATIC_MIN_SAMPLES and samples[-1,0]-samples[0,0] >= config.RANGE_FIXED_WINDOW_S * 0.8:
        if np.ptp(samples[:,1]) <= config.RANGE_FIXED_EPS_M:
            return '固定值提示：静止时可正常；需实际改变高度再判断'
    return 'NORMAL — 数据持续更新，量程内'
