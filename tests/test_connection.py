"""模拟USB拔线和Heartbeat丢失，不要求用户实际拔插飞控。"""
import time
import unittest
from unittest.mock import patch
from types import SimpleNamespace
from pymavlink import mavutil
from PySide6.QtCore import QCoreApplication
import config
from mavlink.connection import ConnectionWorker

class FakeMav:
    def __init__(self):
        self.sent = []
    def __getattr__(self,name):
        return lambda *args:self.sent.append((name,args))

def heartbeat():
    codec = mavutil.mavlink.MAVLink(None,srcSystem=1,srcComponent=1)
    message = codec.heartbeat_encode(2,3,0,5,3)
    message.pack(codec)
    return message

class FakeConnection:
    def __init__(self,disconnect=False,initial=True):
        self.mav = FakeMav()
        self.items = [heartbeat()] if initial else []
        self.closed = False
        self.disconnect = disconnect
    def recv_match(self,**kwargs):
        if self.items:
            return self.items.pop(0)
        if self.disconnect:
            raise OSError('USB disconnected')
        time.sleep(0.01)
        return None
    def close(self):
        self.closed = True

class ConnectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QCoreApplication.instance() or QCoreApplication([])

    def test_usb_disconnect_and_reconnect(self):
        for _ in range(2):
            connection = FakeConnection(disconnect=True)
            worker = ConnectionWorker('COM15',connection_factory=lambda *a,**k:connection)
            states,errors = [],[]
            worker.state.connect(lambda state,data:states.append(state))
            worker.error.connect(errors.append)
            worker.run()
            self.assertIn('CONNECTED',states)
            self.assertEqual(states[-1],'DISCONNECTED')
            self.assertTrue(connection.closed)
            self.assertIn('USB disconnected',errors[0])
            self.assertFalse(any(name=='command_long_send' for name,args in connection.mav.sent))

    def test_missing_heartbeat_and_stream_stall(self):
        for initial in (False,True):
            connection = FakeConnection(initial=initial)
            worker = ConnectionWorker('COM15',connection_factory=lambda *a,**k:connection)
            errors = []
            worker.error.connect(errors.append)
            with patch.object(config,'HEARTBEAT_TIMEOUT_S',0.06):
                start = time.monotonic()
                worker.run()
                self.assertLess(time.monotonic()-start,1.0)
            self.assertTrue(errors)
            self.assertTrue(connection.closed)

    def test_busy_port_message(self):
        def busy(*args,**kwargs):
            raise PermissionError('Access is denied')
        worker = ConnectionWorker('COM15',connection_factory=busy)
        errors = []
        worker.error.connect(errors.append)
        worker.run()
        self.assertIn('COM15 可能被 Mission Planner 或其他程序占用，请先断开 Mission Planner。',errors[0])

    def test_logs_denied_when_armed(self):
        worker = ConnectionWorker('COM15')
        worker.armed = True
        worker.download = SimpleNamespace(active=False)
        errors = []
        worker.error.connect(errors.append)
        worker.request('logs')
        worker._actions()
        self.assertIn('DISARMED',errors[0])

if __name__ == '__main__':
    unittest.main()
