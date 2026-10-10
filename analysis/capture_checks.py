"""地面采样条件与质量筛选；不更改飞控或离线诊断门限。"""
import math
import numpy as np
import config


def motion_errors(store, now):
    errors = {}
    for field, label, limit, unit in (
        ('roll', '横滚角', config.DIRECTION_LEVEL_MAX_DEG, '°'),
        ('pitch', '俯仰角', config.DIRECTION_LEVEL_MAX_DEG, '°'),
        ('rollspeed', '横滚角速度', config.STATIC_RATE_MAX_RAD_S, 'rad/s'),
        ('pitchspeed', '俯仰角速度', config.STATIC_RATE_MAX_RAD_S, 'rad/s'),
        ('yawspeed', '偏航角速度', config.STATIC_RATE_MAX_RAD_S, 'rad/s'),
    ):
        value = store.get(field, now)
        if value is None or not math.isfinite(value):
            errors[field] = f'{label}数据缺失或超过{config.STALE_S:g}秒未更新'
        elif abs(value) > limit:
            errors[field] = f'{label} {value:.3f}{unit}，超出 ±{limit:g}{unit}'
    return errors


def filter_capture(xs, ys, qs, threshold):
    """只使用同时间戳、有限值且质量为正的样本；返回可复核统计。"""
    ys, qs = dict(ys), dict(qs)
    aligned = [(x, ys[t], qs[t]) for t, x in xs
               if t in ys and t in qs and np.all(np.isfinite([x, ys[t], qs[t]]))]
    samples = [(x, y) for x, y, q in aligned if 0 < q <= 255 and q >= threshold]
    quality = [q for _, _, q in aligned if 0 <= q <= 255]
    summary = f'采样门限 {threshold}/255；对齐样本 {len(aligned)}，保留 {len(samples)}（至少需{config.DIRECTION_MIN_SAMPLES}）'
    if quality:
        summary += f'；质量 {min(quality):.0f}–{max(quality):.0f}，中位 {np.median(quality):.0f}'
    else:
        summary += '；质量数据缺失或无效'
    if quality and np.median(quality) < config.FLOW_QUALITY_MIN:
        summary += f'。质量低于原筛查参考值{config.FLOW_QUALITY_MIN}，仅供动作响应排查'
    summary += '。采样完成不代表光流可靠或允许起飞。'
    return samples, summary
