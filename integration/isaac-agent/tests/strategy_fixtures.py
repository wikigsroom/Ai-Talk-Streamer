"""Explicit synthetic scenarios derived from recorded room geometry; never game progress."""
from copy import deepcopy
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]

def scenario(domain='route'):
    raw=json.loads((ROOT/'tests/fixtures/sharp-plug-same-frame-native113.json').read_text(encoding='utf8'))['raw_state']
    raw=deepcopy(raw)
    raw.update(frame=100,start_seed=130130,stage=1,stage_type=0,dimension=0,room_index=97,room_visit_sequence=1,
               restart_count=0,room_clear=True,room_cleared_frame=0,room_entered_frame=0,room_entry_age_frames=100,
               enemies=[],projectiles=[],danger_effects=[],hazards=[],damage_events=[],player_dead=False,
               held_cards=[],held_pills=[],held_trinkets=[],pickups=[],coins=20,keys=3,bombs=5,bomb_active=False,
               bomb_placed=False,active_item=0,active_charge=0,progression_target='satan')
    raw['player'].update(pos={'x':320,'y':280},vel={'x':0,'y':0},hp=12,red_hearts=8,max_hearts=8,soul_hearts=4,black_hearts=4)
    raw['layout'].update(room_type='default',is_boss=False,blocked=[],danger_grid_indices=[],grid_events=[],bomb_walls=[])
    raw['layout']['doors']=[dict(slot=1,pos={'x':320,'y':120},target_room_index=84,target_room_type='default',
        target_clear=False,target_is_boss=False,door_locked=False,door_lock_known=True,door_open=True,door_open_known=True,grid_index=7)]
    raw['strategy']={'source':'synthetic_replay','bridge_generation':'fixture-1','inventory_known':True,
        'inventory':[{'id':1,'count':1,'name':'The Sad Onion'}],'inventory_revision':'1x1',
        'actives':[],'pockets':[],'pickups':[], 'map':[{'index':97,'visited':1,'type':1}],
        'health':{'exact':True,'units':'half_hearts','character_type':0,'red_hearts':8,'max_hearts':8,'soul_hearts':4,
                  'black_hearts_bitmask':4,'bone_hearts':0,'rotten_hearts':0},
        'sacrifice':{'known':False,'count':None},'room_type':'default','paused':False}
    e=raw['strategy']
    if domain in {'active','active_special'}:
        item=34 if domain=='active' else 105
        e['actives']=[{'slot':0,'id':item,'charge':6,'battery':0,'max_charges':6,'ready':True}]
        if domain=='active':
            raw['room_clear']=False
            raw['enemies']=[{'id':10,'type':12,'variant':0,'pos':{'x':520,'y':280},'vel':{'x':0,'y':0},'hp':10,'vulnerable':True,'is_boss':False}]
    if domain in {'pickup','active_special','deal'}:
        item={'id':7,'spawn_seed':7007,'type':5,'variant':100,'subtype':1,'pos':{'x':320,'y':240},'grid_index':52,
              'price':-1 if domain=='deal' else 0,'options_index':1,'quality':3,'name':'The Sad Onion','locally_eligible':True,
              'is_collectible':True,'pickup_kind':'collectible'}
        e['pickups']=[item];raw['pickups']=[deepcopy(item)]
    if domain=='pill': e['pockets']=[{'slot':0,'kind':'pill','id':1,'identified':True,'effect':14,'effect_name':'PILLEFFECT_SPEED_UP','effect_supported':True}]
    if domain=='card': e['pockets']=[{'slot':0,'kind':'card','id':22}]
    if domain=='planetarium': raw['layout']['doors'][0].update(target_room_type='planetarium')
    if domain=='bomb_entry':
        raw['layout']['bomb_walls']=[{'slot':0,'pos':{'x':80,'y':280},'site':{'x':140,'y':280},'grid_index':91,'room_type':'secret','bombed':False}]
    if domain=='dice':
        e['room_type']='dice';raw['layout']['room_type']='dice'
        e['dice']={'face':4,'grid_index':97,'pos':{'x':320,'y':280},'entity_id':77,'spawn_seed':777}
    if domain=='sacrifice':
        e['room_type']='sacrifice';raw['layout']['room_type']='sacrifice'
        e['sacrifice']={'known':True,'count':2,'spike_index':97,'pos':{'x':320,'y':280}}
    if domain=='terrain':
        raw['layout']['grid_events']=[{'id':-45,'grid_index':45,'kind':'spike','timed':True,'active':False,'pos':{'x':160,'y':240},'state':0}]
    return raw

if __name__=='__main__':
    target=ROOT/'logs/build/replay-route.json';target.parent.mkdir(parents=True,exist_ok=True)
    target.write_text(json.dumps(scenario('pickup'),ensure_ascii=False,indent=2),encoding='utf8')
    print(target)
