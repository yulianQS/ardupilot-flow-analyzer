"""真实页面与遥测缓存的地面采样回归测试，不连接飞控。"""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtWidgets import QApplication
import config
from analysis.capture_checks import filter_capture, motion_errors
from analysis.realtime import RealtimeStore
from gui.ground_check_page import GroundCheckPage
from gui.mtf02p_page import MTF02PPage


def feed(store, now, quality=45, x=0., y=.12, rate=0., attitude=True):
    if attitude:
        store.add(now, 'ATTITUDE', dict(roll=0., pitch=0., yaw=0.,
                  rollspeed=rate, pitchspeed=0., yawspeed=0.))
    store.add(now, 'OPTICAL_FLOW_RAD', dict(sensor_id=config.FLOW_SENSOR_ID,
              quality=quality, integration_time_us=100000,
              integrated_x=x*.1, integrated_y=y*.1))


class CaptureQualityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.pages = []

    def tearDown(self):
        for page in self.pages:
            page.close()
            page.deleteLater()
        self.app.processEvents()

    def direction_page(self):
        page = MTF02PPage()
        self.pages.append(page)
        page.source.setCurrentIndex(1)
        return page

    def capture(self, page, store, start=100., quality=45, x=0., y=.12,
                brief_rotation=False, stale_attitude=False):
        ground = isinstance(page, GroundCheckPage)
        def update(now):
            if ground:
                page.update_data(store, now, False, True)
            else:
                page.update_data(store, now, False)
        feed(store, start, quality, x, y)
        update(start)
        with patch('time.monotonic', return_value=start):
            page.begin()
        for i in range(1, 51 if ground else 31):
            now = start+i/10
            feed(store, now, quality, x, y, rate=.2 if brief_rotation and i==2 else 0.,
                 attitude=not stale_attitude)
            update(now)

    def test_quality_45_completes_four_directions_with_warning(self):
        page, store = self.direction_page(), RealtimeStore()
        for i, (x, y) in enumerate(((0., .12), (0., -.12), (-.12, 0.), (.12, 0.))):
            self.capture(page, store, start=100.+i*10, x=x, y=y)
            self.assertEqual(page.step, i+1)
        self.assertIn('X/Y交换候选：否', page.result.text())
        self.assertIn('中位 45', page.result.text())
        self.assertIn('仅供动作响应排查', page.result.text())
        self.assertFalse(page.quality_min.isEnabled())
        page.reset()
        self.assertTrue(page.quality_min.isEnabled())
        self.assertEqual(config.FLOW_QUALITY_MIN, 100)

    def test_strict_quality_and_zero_quality_are_still_rejected(self):
        for threshold, quality in ((100, 45), (1, 0), (30, 20)):
            page = self.direction_page()
            page.quality_min.setValue(threshold)
            self.capture(page, RealtimeStore(), quality=quality)
            self.assertEqual(page.step, 0)
            self.assertIn('保留 0', page.result.text())
            self.assertIn('筛选后样本不足', page.result.text())

    def test_zero_motion_does_not_produce_direction_verdict(self):
        page, store = self.direction_page(), RealtimeStore()
        for i in range(4):
            self.capture(page, store, start=100.+i*10, x=0., y=0.)
        self.assertIn('信号太弱', page.result.text())
        self.assertNotIn('X/Y交换候选：否', page.result.text())

    def test_brief_rotation_remains_invalid_after_recovery(self):
        page = self.direction_page()
        self.capture(page, RealtimeStore(), brief_rotation=True)
        self.assertEqual(page.step, 0)
        self.assertIn('横滚角速度 0.200rad/s', page.result.text())
        self.assertNotIn('数据缺失', page.result.text())

    def test_stale_attitude_is_distinct_from_motion(self):
        page = self.direction_page()
        self.capture(page, RealtimeStore(), stale_attitude=True)
        self.assertEqual(page.step, 0)
        self.assertIn('超过2秒未更新', page.result.text())
        self.assertNotIn('超出 ±', page.result.text())

    def test_ground_check_preserves_raw_samples_and_export_threshold(self):
        page = GroundCheckPage()
        self.pages.append(page)
        page.confirm.setChecked(True)
        page.step = 1
        page.quality_min.setValue(40)
        store = RealtimeStore()
        self.capture(page, store)
        self.assertEqual(page.step, 2)
        self.assertGreaterEqual(len(page.captures['forward']), 8)
        self.assertIn('中位 45', page.records[0]['result'])
        self.capture(page, store, start=110., quality=20)
        self.assertEqual(page.captures['backward'], [])
        self.assertGreater(len(page.records[1]['samples']['flow_x']), 0)
        with tempfile.TemporaryDirectory(dir=config.DATA_DIR) as directory:
            path = Path(directory)/'capture.json'
            with patch('gui.ground_check_page.QFileDialog.getSaveFileName', return_value=(str(path), 'JSON')):
                page.export()
            saved = json.loads(path.read_text(encoding='utf-8'))
            self.assertEqual(saved['quality_local_threshold'], 40)
            self.assertEqual(saved['records'][1]['samples']['quality'][0][1], 20)
        self.assertFalse(page.quality_min.isEnabled())
        page.reset()
        self.assertTrue(page.quality_min.isEnabled())

    def test_ground_check_reports_rotation_axis(self):
        page = GroundCheckPage()
        self.pages.append(page)
        page.confirm.setChecked(True)
        page.step = 1
        self.capture(page, RealtimeStore(), brief_rotation=True)
        self.assertEqual(page.step, 1)
        self.assertIn('横滚角速度 0.200rad/s', page.status.text())

    def test_invalid_and_unaligned_values_are_not_admitted(self):
        samples, _ = filter_capture([(1, .1), (2, .2), (3, .3), (4, float('nan'))],
                                    [(1, 0), (2, 0), (4, 0)],
                                    [(1, 45), (2, 999), (3, 45), (4, 45)], 30)
        self.assertEqual(samples, [(.1, 0)])
        self.assertIn('rollspeed', motion_errors(RealtimeStore(), 100))


if __name__ == '__main__':
    unittest.main()
