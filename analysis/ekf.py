"""跨消息对齐和坐标换算：不在数据空洞中造点，不混合 EKF core。"""
import numpy as np
import config

def align(series, timestamps, tolerance=config.ALIGN_TOLERANCE_S):
    values = np.full(len(timestamps),np.nan)
    if series is None or not len(series.time):
        return values
    right = np.searchsorted(series.time,timestamps)
    left = np.clip(right-1,0,len(series.time)-1)
    right = np.clip(right,0,len(series.time)-1)
    indices = np.where(np.abs(series.time[left]-timestamps) <= np.abs(series.time[right]-timestamps),left,right)
    valid = np.abs(series.time[indices]-timestamps) <= tolerance
    values[valid] = series.value[indices[valid]]
    return values

def flow_body_velocity(flow_x, flow_y, body_x, body_y, distance):
    # 对应 Copter-4.6.3 Measurements.cpp 的 -rawFlow+bodyRate，
    # 以及 OptFlowFusion.cpp 的 LOS=(VbodyY/range, -VbodyX/range)。
    # 因此机体平移速度为 ((rawY-bodyY)*range, -(rawX-bodyX)*range)。
    return (flow_y-body_y)*distance, -(flow_x-body_x)*distance

def body_to_ned(vx,vy,yaw_deg):
    # 仅近水平条件使用二维 yaw 旋转；大姿态时须完整三维旋转和斜距补偿。
    angle = np.radians(yaw_deg)
    return vx*np.cos(angle)-vy*np.sin(angle), vx*np.sin(angle)+vy*np.cos(angle)

def correlation(first,second):
    valid = np.isfinite(first)&np.isfinite(second)
    if valid.sum() < config.MIN_DIAG_SAMPLES:
        return None
    first,second = first[valid],second[valid]
    if np.std(first)<1e-6 or np.std(second)<1e-6:
        return None
    return float(np.corrcoef(first,second)[0,1])
