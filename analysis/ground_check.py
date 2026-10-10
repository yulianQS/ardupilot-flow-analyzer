"""地面检查的保守证据判读，不输出准飞结论。"""
import numpy as np
import config

def assess_step(kind,samples,unit,quality_min=None):
    if quality_min is None:quality_min=config.FLOW_QUALITY_MIN
    def values(key):
        a=np.asarray(samples.get(key,[]),dtype=float).reshape(-1,2)
        return a[:,1][np.isfinite(a[:,1])]
    def enough(*keys):return all(len(values(k))>=config.DIRECTION_MIN_SAMPLES for k in keys)
    q=values('quality')
    quality=f'质量中位 {np.median(q):.0f}/255。' if len(q) else '质量缺失。'
    if kind=='height':
        r=values('range')
        if len(r)<8:return '证据不足：测距样本不足。'
        span=float(np.ptp(r))
        return f'测距 {r.min():.3f}–{r.max():.3f}m，变化 {span:.3f}m；'+('已观察到随动作变化，仍需与尺量距离核对。' if span>=.05 else '未观察到明显变化：检查是否实际改变了高度、传感器是否冻结。')
    if kind=='rotation':
        if not enough('flow_x','flow_y','rollspeed','pitchspeed'):return '证据不足：需要角光流与机体转动速率。'
        peak=max(np.max(np.abs(values(k))) for k in ('rollspeed','pitchspeed'))
        return quality+f'机体角速率峰值 {peak:.3f}rad/s。'+('未观察到足够转动。' if peak<.1 else '已记录转动；本步不判比例或补偿正确，需对照 BIN 的 OF.bodyX/bodyY 与 IMU。')
    if kind=='static':
        if not enough('vx','vy'):return '证据不足：缺少连续水平速度估计，不能判断静置速度漂移。'
        peak=max(np.max(np.abs(values(k))) for k in ('vx','vy'))
        return quality+f'按你确认的静置条件，单轴速度绝对峰值 {peak:.3f}m/s；'+('明显偏大，先检查速度估计与融合。' if peak>config.EKF_SPEED_HIGH_M_S else '本次未超过本地2m/s筛查线；不等于已达到悬停精度或通过飞行验收。')
    if not enough('flow_x','flow_y','quality'):return '证据不足：光流或质量样本不足。'
    x,y=values('flow_x'),values('flow_y')
    return quality+f'原始X均值 {np.mean(x):.4f}，Y均值 {np.mean(y):.4f} {unit}。'+('质量中位低于本地采样门限，需检查筛选后样本数。' if np.median(q)<quality_min else '完成四个方向后统一判断轴与符号。')
