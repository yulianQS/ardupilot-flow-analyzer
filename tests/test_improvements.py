import unittest
import numpy as np
import pandas as pd
from analysis.bin_parser import LogDataset,Series
from analysis.timeline_events import extract_events,active_bounds
from analysis.loiter_diagnosis import diagnose
from analysis.ground_check import assess_step

class ImprovementTests(unittest.TestCase):
    def test_late_loiter_action_and_estop_order(self):
        t=np.arange(0,41,.1)
        dataset=LogDataset('fixture',{
            'MODE':pd.DataFrame({'t':[0,40],'ModeNum':[5,9]}),
            'ATT':pd.DataFrame({'t':t,'DesPitch':np.where((t>=30)&(t<33),-28.,0.),'Pitch':np.where((t>=31)&(t<33),-20.,0.)}),
            'MSG':pd.DataFrame({'t':[0,33,34],'Message':['ArduCopter V4.6.3 (test)','RC9: MotorEStop HIGH','Crash: Disarming']}),
            'XKF5':pd.DataFrame({'t':t,'C':0,'NI':np.full(len(t),255)}),
        },{},2000,0)
        report=diagnose(dataset)
        self.assertEqual(report.events[0].window_end,40)
        action=next(f for f in report.events[0].findings if f.check.startswith('6.'))
        self.assertGreater(action.time_s,10)
        self.assertTrue(any(e['category']=='目标姿态' and e['time_s']==30 for e in report.timeline))
        labels=[e.category for e in extract_events(dataset) if e.time_s>=30]
        self.assertLess(labels.index('目标姿态'),labels.index('急停'))

    def test_unknown_firmware_never_assumes_ni_scaling(self):
        data=LogDataset('fixture',{'XKF5':pd.DataFrame({'t':[0,1],'C':[0,0],'NI':[100,255]})},{},1,0)
        self.assertEqual(data.signals()['flow_norm'].value.tolist(),[100,255])
        self.assertNotIn('flow_test_ratio',data.signals())
        data.frames['MSG']=pd.DataFrame({'t':[0],'Message':['ArduCopter V4.6.3 (abc)']})
        np.testing.assert_allclose(data.signals()['flow_test_ratio'].value,[1,2.55])

    def test_takeoff_is_labelled_as_firmware_judgement(self):
        data=LogDataset('fixture',{'EV':pd.DataFrame({'t':[5.],'Id':[28]}),
            'MSG':pd.DataFrame({'t':[0.],'Message':['ArduCopter V4.6.3 (abc)']})},{},5,0)
        event=next(e for e in extract_events(data) if e.category=='离地判定')
        self.assertIn('飞控判定',event.label)
        self.assertIn('实际操作',event.evidence)

    def test_plot_bounds_ignore_late_discrete_only_records(self):
        signals={'range':Series(np.array([0.,300.]),np.array([.1,.2]),'m','RFND'),
                 'mode':Series(np.array([0.,3000.]),np.array([5.,9.]),'','MODE',True)}
        self.assertEqual(active_bounds(signals),(0,300))

    def test_missing_ground_data_does_not_pass(self):
        for kind in ('height','rotation','static','forward'):
            self.assertIn('证据不足',assess_step(kind,{},'rad/s'))
        samples={'vx':[[i,12.] for i in range(10)],'vy':[[i,0.] for i in range(10)]}
        self.assertIn('明显偏大',assess_step('static',samples,'rad/s'))

    def test_events_do_not_merge_across_data_gaps(self):
        data=LogDataset('fixture',{}, {},12,0)
        signals={'vx':Series(np.array([0.,.1,10.,10.1]),np.array([3.,3.,3.,3.]),'m/s','XKF1')}
        self.assertEqual([e.time_s for e in extract_events(data,signals)],[0,10])

if __name__=='__main__':unittest.main()
