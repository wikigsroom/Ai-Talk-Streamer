from copy import deepcopy
import unittest

from integration.issac.readiness import verified_drink_pause


class DrinkReadiness(unittest.TestCase):
    def sample(self):
        identity={'controller':'current','seed':123,'room':83,'stage':1,'bridge':'current','visit':2}
        return {'state':{'connected':True,'age_ms':50,'identity':identity,
                  'data':{'frame':900,'room':{'paused':True,'clear':True,'dead':False}}},
            'game':{'armed':False,'control_revision':8},'studio':{'ready':True,'natural_action':{
                'kind':'drink','control_revision':8,'identity':deepcopy(identity),'created_unix':1000,'expires_unix':1060,
                'native_receipt':{'normal_game_pause_acknowledged':True,'stable_frame':900,
                    'native':{'frame':900,'paused':True,'dead':False,'players':1,'seed':123,'room':83,'stage':1}}}}}

    def test_only_current_actual_bounded_stable_safe_pause_counts(self):
        original=self.sample();self.assertTrue(verified_drink_pause(original,1001))
        changes=[('state','age_ms',1500),('state','connected',False),('game','armed',True),
            ('game','control_revision',9),('studio','ready',False)]
        for group,key,value in changes:
            sample=deepcopy(original);sample[group][key]=value
            self.assertFalse(verified_drink_pause(sample,1001),(group,key))
        for key,value in [('expires_unix',1061),('created_unix',1002),('kind','operator_pause'),
                ('identity',{'seed':123}),('control_revision',9),('native_receipt',{})]:
            sample=deepcopy(original);sample['studio']['natural_action'][key]=value
            self.assertFalse(verified_drink_pause(sample,1001),key)
        for key,value in [('paused',False),('clear',False),('dead',True)]:
            sample=deepcopy(original);sample['state']['data']['room'][key]=value
            self.assertFalse(verified_drink_pause(sample,1001),key)
        for key,value in [('frame',901),('seed',124),('room',84),('stage',2),('players',0)]:
            sample=deepcopy(original);sample['studio']['natural_action']['native_receipt']['native'][key]=value
            self.assertFalse(verified_drink_pause(sample,1001),key)
        self.assertFalse(verified_drink_pause(original,1060));self.assertFalse(verified_drink_pause({},1001))
        sample=deepcopy(original);sample['state']['data']['frame']=901
        self.assertFalse(verified_drink_pause(sample,1001))
