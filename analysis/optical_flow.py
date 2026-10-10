"""方向测试只输出证据和检查建议，绝不修改 FLOW_ORIENT_YAW。

ArduPilot OF 原始角光流及标准 OPTICAL_FLOW_RAD 约定：水平向前 -> +Y，
水平向右 -> -X。转动机体会混入角速度，故测试要求水平且无明显转动。
dpix 的设备约定不够明确，仅报告观测轴，不强行判定正负是否错误。
"""
import numpy as np
import config

DIRECTIONS = [('forward','向机头方向平移'), ('backward','向机尾方向平移'),
              ('right','向右平移'), ('left','向左平移')]

def evaluate_direction(captures, unit):
    means = {}
    lines = []
    minimum = config.DIRECTION_MIN_RAD_S if unit == 'rad/s' else config.DIRECTION_MIN_DPIX
    for name, label in DIRECTIONS:
        samples = np.asarray(captures.get(name, []), dtype=float).reshape(-1, 2)
        samples = samples[np.all(np.isfinite(samples), axis=1)]
        if len(samples) < config.DIRECTION_MIN_SAMPLES:
            return 'Insufficient Data: ' + label + '有效样本不足'
        means[name] = np.mean(samples, axis=0)
        lines.append(f'{label}: X={means[name][0]:.4f}, Y={means[name][1]:.4f} {unit}, n={len(samples)}')
    forward = (means['forward'] - means['backward']) / 2
    right = (means['right'] - means['left']) / 2
    axes = [int(np.argmax(np.abs(vector))) for vector in (forward, right)]
    for vector, axis in zip((forward, right), axes):
        if abs(vector[axis]) < minimum or abs(vector[axis]) < config.DIRECTION_AXIS_RATIO * abs(vector[1-axis]):
            return '\n'.join(lines) + '\nInsufficient Data：运动轴不清楚或信号太弱，请重测。'
    for positive, negative, axis in [('forward','backward',axes[0]), ('right','left',axes[1])]:
        if means[positive][axis] * means[negative][axis] >= 0:
            return '\n'.join(lines) + '\nInsufficient Data：相反方向未得到相反符号，可能有偏置或搬动方式不一致。'
    lines.append(f'前后主要对应 {"XY"[axes[0]]}；左右主要对应 {"XY"[axes[1]]}')
    if axes[0] == axes[1]:
        lines.append('Insufficient Data：两个动作落在同一轴，请重新测试。')
    elif unit != 'rad/s':
        lines.append('X/Y交换、X反向、Y反向：Insufficient Data（dpix 未确认设备坐标约定）。请结合 BIN OF 或 OPTICAL_FLOW_RAD。')
    else:
        lines.append(f'X/Y交换候选：{"是" if axes != [1,0] else "否"}')
        if axes == [1, 0]:
            lines.append(f'X反向候选：{"是" if right[0] > 0 else "否"}')
            lines.append(f'Y反向候选：{"是" if forward[1] < 0 else "否"}')
        else:
            lines.append('先核对轴映射，再判断 X/Y 符号；当前不单独归因。')
        lines.append('标准角光流约定为前移 +Y、右移 -X，不是速度 X/Y。')
    lines.append('建议：核对安装朝向及 FLOW_ORIENT_YAW；本工具不会修改参数。')
    return '\n'.join(lines)
