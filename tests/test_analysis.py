"""已知数据验证单位、对齐、方向、日志版本缺字段和保守诊断。"""
import struct
import tempfile
import unittest
from pathlib import Path
import numpy as np
import pandas as pd
import config
from analysis.bin_parser import Series,LogDataset,parse_bin
from analysis.loiter_diagnosis import diagnose
from analysis.optical_flow import evaluate_direction
from analysis.ekf import align,flow_body_velocity,body_to_ned

class AnalysisTests(unittest.TestCase):
    def test_axis_sign_and_ned_rotation(self):
        x,y = flow_body_velocity(0,1,0,0,2)
        self.assertEqual((x,y),(2,0))
        north,east = body_to_ned(x,y,90)
        self.assertAlmostEqual(north,0,places=7)
        self.assertAlmostEqual(east,2)

    def test_cursor_and_alignment_do_not_bridge_gap(self):
        source = Series(np.array([0.,1.,10.]),np.array([1.,2.,3.]),'m','test')
        self.assertIsNone(source.at(5))
        self.assertTrue(np.isnan(align(source,np.array([5.]))[0]))
        mode = Series(np.array([1.,10.]),np.array([5.,9.]),'mode','MODE',True)
        self.assertEqual(mode.at(6),5)
        self.assertIsNone(mode.at(0))

    def test_direction_standard_axes_not_falsely_swapped(self):
        captures = {'forward':[(0,0.2)]*10,'backward':[(0,-0.2)]*10,
                    'right':[(-0.2,0)]*10,'left':[(0.2,0)]*10}
        result = evaluate_direction(captures,'rad/s')
        self.assertIn('X/Y交换候选：否',result)
        self.assertIn('X反向候选：否',result)
        self.assertIn('Y反向候选：否',result)
        captures['right'] = [(0.2,0)]*10
        captures['left'] = [(-0.2,0)]*10
        self.assertIn('X反向候选：是',evaluate_direction(captures,'rad/s'))
        self.assertIn('Insufficient Data',evaluate_direction(captures,'dpix'))

    def test_missing_fields_not_diagnosed_as_healthy(self):
        data = LogDataset('synthetic',{'MODE':pd.DataFrame({'t':[0.,5.,5.1,20.],'ModeNum':[0,5,5,9]})},{'MODE':4},20,0)
        report = diagnose(data)
        self.assertEqual(len(report.events),1)
        self.assertEqual(report.events[0].time_s,5)
        self.assertTrue(all(item.status=='Insufficient Data' for item in report.events[0].findings))

    def test_yaw_wrap_and_ekf_lane_separation(self):
        times = np.linspace(5,6,21)
        data = LogDataset('synthetic',{'MODE':pd.DataFrame({'t':[0,5,15],'ModeNum':[0,5,9]}),
            'ATT':pd.DataFrame({'t':times,'Yaw':np.mod(np.linspace(359,361,21),360)}),
            'XKF1':pd.DataFrame({'t':[5,5,6,6],'C':[0,1,0,1],'VN':[0,100,0,100],'VE':[0,100,0,100]})}, {},15,0)
        self.assertEqual(data.signals(0)['vx'].value.tolist(),[0,0])
        yaw = next(item for item in diagnose(data).events[0].findings if item.check.startswith('10.'))
        self.assertEqual(yaw.status,'NORMAL')

    def test_real_dataflash_format_parser_and_corruption(self):
        # 只构建很小的协议fixture，生产解析没有任何手写二进制解码器。
        with tempfile.TemporaryDirectory(dir=config.DATA_DIR) as directory:
            path = Path(directory)/'fixture.BIN'
            fmt = b'\xa3\x95\x80'+struct.pack('<BB4s16s64s',150,3+8+4,b'OF',b'Qf',b'TimeUS,flowX')
            data = fmt+b''.join(b'\xa3\x95\x96'+struct.pack('<Qf',2_000_000+i*100_000,i/10) for i in range(10))
            path.write_bytes(data)
            parsed = parse_bin(path)
            self.assertEqual(parsed.counts['OF'],10)
            self.assertAlmostEqual(parsed.duration,0.9)
            self.assertAlmostEqual(parsed.signals()['flow_x'].value[-1],0.9,places=6)
            self.assertNotIn('range',parsed.signals())
            path.write_bytes(b'invalid')
            with self.assertRaises(ValueError):
                parse_bin(path)

if __name__ == '__main__':
    unittest.main()
