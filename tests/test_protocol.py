"""协议故障测试：所有传输使用内存假链路，不接触串口。"""
import random
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import config
from mavlink.safety import ReadOnlyLink
from mavlink.log_downloader import LogDownloader
from mavlink.message_handler import MessageHandler
from mavlink.parameter_reader import ParameterReader
from analysis.realtime import RealtimeStore

class FakeLink:
    def __init__(self):
        self.sent = []
    def send(self,*arguments):
        self.sent.append(arguments)

class ProtocolTests(unittest.TestCase):
    def test_read_only_blocks_all_control(self):
        link = ReadOnlyLink(SimpleNamespace(mav=object()))
        for method in ('command_long_send','command_int_send','param_set_send','set_mode_send',
                       'rc_channels_override_send','mission_count_send','log_erase_send','servo_output_raw_send'):
            with self.assertRaises(PermissionError):
                link.send(method)

    def test_out_of_order_duplicates_missing_retried(self):
        with tempfile.TemporaryDirectory(dir=config.DATA_DIR) as directory:
            link,done,errors,progress = FakeLink(),[],[],[]
            downloader = LogDownloader(link,1,1,progress.append,done.append,errors.append)
            data = bytes((i*7)%256 for i in range(307))
            downloader.start(8,len(data),directory)
            def send(offset,count=90,id=8):
                payload = data[offset:offset+count]
                downloader.accept(SimpleNamespace(id=id,ofs=offset,count=len(payload),data=payload))
            send(180)
            send(0)
            send(0)
            send(270)
            self.assertFalse(done)
            self.assertEqual(downloader.received_count,217)
            downloader.tick(downloader.last_request+config.LOG_RETRY_S+0.1)
            self.assertEqual(link.sent[-1][-2:],(90,90))
            send(90,id=9)
            self.assertFalse(done)
            send(90)
            self.assertEqual(Path(done[0]).read_bytes(),data)
            self.assertFalse(errors)
            self.assertEqual(progress[-1]['done'],len(data))

    def test_window_boundary_and_no_overwrite(self):
        with tempfile.TemporaryDirectory(dir=config.DATA_DIR) as directory,patch.object(config,'LOG_WINDOW_BYTES',180):
            path = Path(directory)/'log_0001.BIN'
            path.write_bytes(b'previous')
            done = []
            downloader = LogDownloader(FakeLink(),1,1,lambda x:None,done.append,lambda x:None)
            downloader.start(1,181,directory)
            for offset,length in [(90,90),(0,90),(180,1)]:
                downloader.accept(SimpleNamespace(id=1,ofs=offset,count=length,data=bytes([42])*length))
            self.assertEqual(path.read_bytes(),b'previous')
            self.assertEqual(Path(done[0]).read_bytes(),bytes([42])*181)

    def test_download_timeout_leaves_part_only(self):
        with tempfile.TemporaryDirectory(dir=config.DATA_DIR) as directory:
            errors = []
            downloader = LogDownloader(FakeLink(),1,1,lambda x:None,lambda x:self.fail('incomplete marked complete'),errors.append)
            downloader.start(3,120,directory)
            for _ in range(config.LOG_MAX_RETRIES+1):
                downloader.tick(downloader.last_request+config.LOG_RETRY_S+0.01)
            self.assertFalse(downloader.active)
            self.assertTrue(errors)
            self.assertFalse(list(Path(directory).glob('*.BIN')))
            self.assertTrue(list(Path(directory).glob('*.part')))

    def test_units_quality_zero_and_invalid_integration(self):
        handler = MessageHandler()
        sample = {'sensor_id':0,'quality':0,'integration_time_us':20000,'integrated_x':0.002,'integrated_y':-0.004}
        values = handler.values('OPTICAL_FLOW_RAD',sample)
        self.assertAlmostEqual(values['flow_rad_x'],0.1)
        self.assertEqual(values['flow_rad_quality'],0)
        sample['integration_time_us'] = 0
        self.assertIsNone(handler.values('OPTICAL_FLOW_RAD',sample)['flow_rad_x'])
        self.assertEqual(handler.values('DISTANCE_SENSOR',{'orientation':25,'id':0,'current_distance':63})['range'],0.63)
        self.assertEqual(handler.values('DISTANCE_SENSOR',{'orientation':0,'id':1,'current_distance':10}),{})

    def test_mavlink1_zeros_not_valid_extensions(self):
        handler = MessageHandler()
        handler.values('AUTOPILOT_VERSION',{'flight_sw_version':(4<<24)|(6<<16)|(3<<8)|128})
        sample = {'sensor_id':0,'quality':80,'flow_x':0,'flow_y':0,'flow_rate_x':0.3,'flow_rate_y':-0.2,'_wire_version':1}
        self.assertNotIn('flow_rate_x',handler.values('OPTICAL_FLOW',sample))
        sample['_wire_version'] = 2
        self.assertEqual(handler.values('OPTICAL_FLOW',sample)['flow_rate_x'],0.3)

    def test_stale_samples_become_na(self):
        store = RealtimeStore()
        store.add(100,'ATTITUDE',{'roll':1.0,'pitch':0,'yaw':0})
        self.assertAlmostEqual(store.get('roll',101),57.2957795)
        self.assertIsNone(store.get('roll',104))

    def test_parameter_retry_is_bounded(self):
        link = FakeLink()
        reader = ParameterReader(link,1,1)
        reader.pending = {'DOES_NOT_EXIST':[0,0]}
        missing = []
        for i in range(1,6):
            missing.extend(reader.tick(i*config.PARAM_RETRY_S))
        self.assertEqual(len(link.sent),config.PARAM_MAX_RETRIES)
        self.assertEqual(missing,['DOES_NOT_EXIST'])

if __name__ == '__main__':
    unittest.main()
