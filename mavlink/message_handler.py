"""遥测字段转换。Body: X机头/Y右/Z下；NED: X北/Y东/Z下。

OPTICAL_FLOW 原始 flow_x/y 为 dpix。ArduPilot 4.6.3 的兼容发送实现
不能直接按 generic MAVLink flow_comp_m_* 标签当成可信机体速度。
因此本程序展示原始量，方向与比例的定量诊断优先使用 BIN 的 OF。
OPTICAL_FLOW_RAD 的积分 rad 除以 integration_time_us/1e6 后才是 rad/s。
"""
import math
import config

MONITORED = {'HEARTBEAT','ATTITUDE','GLOBAL_POSITION_INT','LOCAL_POSITION_NED',
             'OPTICAL_FLOW','OPTICAL_FLOW_RAD','DISTANCE_SENSOR','RANGEFINDER',
             'VFR_HUD','SYS_STATUS','EKF_STATUS_REPORT','VIBRATION','RC_CHANNELS',
             'SERVO_OUTPUT_RAW','STATUSTEXT','AUTOPILOT_VERSION'}

def finite(value):
    try:
        value = float(value)
        return value if math.isfinite(value) else None
    except (TypeError, ValueError):
        return None

class MessageHandler:
    def __init__(self):
        self.range_id = config.RANGE_SENSOR_ID
        self.ardupilot_463 = False

    def values(self, kind, data):
        result = {}
        if kind == 'AUTOPILOT_VERSION':
            self.ardupilot_463 = int(data.get('flight_sw_version',0)) >> 8 == (4<<16 | 6<<8 | 3)
        elif kind == 'ATTITUDE':
            for axis in ('roll','pitch','yaw'):
                value = finite(data.get(axis))
                result[axis] = math.degrees(value) if value is not None else None
            for axis in ('rollspeed','pitchspeed','yawspeed'):
                result[axis] = finite(data.get(axis))
        elif kind == 'LOCAL_POSITION_NED':
            result = {f'v{axis}': finite(data.get(f'v{axis}')) for axis in 'xyz'}
        elif kind == 'GLOBAL_POSITION_INT':
            for axis in 'xyz':
                value = finite(data.get(f'v{axis}'))
                result[f'global_v{axis}'] = value / 100 if value is not None else None
            result['latitude'] = data.get('lat', 0) / 1e7
            result['longitude'] = data.get('lon', 0) / 1e7
        elif kind in ('OPTICAL_FLOW','OPTICAL_FLOW_RAD') and data.get('sensor_id') == config.FLOW_SENSOR_ID:
            prefix = 'flow_rad' if kind == 'OPTICAL_FLOW_RAD' else 'flow_raw'
            result[prefix + '_quality'] = finite(data.get('quality'))
            if kind == 'OPTICAL_FLOW_RAD':
                duration = data.get('integration_time_us', 0) / 1e6
                for axis in 'xy':
                    value = finite(data.get('integrated_' + axis))
                    result[prefix + '_' + axis] = value / duration if duration > 0 and value is not None else None
            else:
                for axis in 'xy':
                    result[prefix + '_' + axis] = finite(data.get('flow_' + axis))
                # Copter-4.6.3 GCS_Common.cpp: flow_rate_x/y直接为float角速率。
                # 仅确认版本且MAVLink2时使用，避免将MAVLink1补零误判为有效测量。
                if self.ardupilot_463 and data.get('_wire_version') == 2:
                    for axis in 'xy':
                        result['flow_rate_'+axis] = finite(data.get('flow_rate_'+axis))
                    result['flow_rate_quality'] = finite(data.get('quality'))
        elif kind == 'DISTANCE_SENSOR' and data.get('orientation') == config.DOWNWARD_ORIENTATION:
            if self.range_id is None:
                self.range_id = data.get('id')
            if data.get('id') == self.range_id:
                distance = finite(data.get('current_distance'))
                result['range'] = distance / 100 if distance is not None and distance != 65535 else None
                result['range_min'] = data.get('min_distance', 0) / 100
                result['range_max'] = data.get('max_distance', 0) / 100
        elif kind == 'VIBRATION':
            result = {f'vibe_{axis}': finite(data.get('vibration_' + axis)) for axis in 'xyz'}
        elif kind == 'EKF_STATUS_REPORT':
            result = {'ekf_flags': data.get('flags'), **{name: finite(data.get(name)) for name in
                      ('velocity_variance','pos_horiz_variance','pos_vert_variance','compass_variance','terrain_alt_variance')}}
        elif kind == 'RC_CHANNELS':
            for channel in range(1, 19):
                value = data.get(f'chan{channel}_raw')
                result[f'rc{channel}'] = value if value not in (None, 0, 65535) else None
        elif kind == 'SERVO_OUTPUT_RAW':
            # port=0 对应输出组；不同 port 不允许混成同一条曲线。
            if data.get('port', 0) == 0:
                result = {f'out{i}': data.get(f'servo{i}_raw') or None for i in range(1, 17)}
        elif kind == 'VFR_HUD':
            result = {name: finite(data.get(name)) for name in ('airspeed','groundspeed','alt','climb','throttle')}
        elif kind == 'SYS_STATUS':
            battery = data.get('voltage_battery', 65535)
            result['battery_v'] = battery / 1000 if battery != 65535 else None
            result['sensor_health'] = data.get('onboard_control_sensors_health')
        return result
