"""Distinguish a verified bounded safe drink from faults and operator pauses."""
import time


def verified_drink_pause(sample,now=None):
    state=sample.get('state') or {};game=sample.get('game') or {};studio=sample.get('studio') or {}
    action=studio.get('natural_action') or {};data=state.get('data') or {};room=data.get('room') or {}
    receipt=action.get('native_receipt') or {};native=receipt.get('native') or {};identity=state.get('identity') or {}
    now=time.time() if now is None else now
    created=action.get('created_unix');expires=action.get('expires_unix');frame=receipt.get('stable_frame')
    age=state.get('age_ms');revision=action.get('control_revision')
    return bool(action.get('kind')=='drink' and type(created) in (int,float) and type(expires) in (int,float)
        and 0<expires-created<=60 and created<=now<expires
        and state.get('connected') is True and type(age) in (int,float) and 0<=age<1500
        and studio.get('ready') is True and identity and identity==action.get('identity')
        and type(revision) is int and revision==game.get('control_revision') and game.get('armed') is False
        and receipt.get('normal_game_pause_acknowledged') is True
        and type(frame) is int and frame==data.get('frame')==native.get('frame')
        and room.get('paused') is True and room.get('clear') is True and room.get('dead') is False
        and native.get('paused') is True and native.get('dead') is False and native.get('players')==1
        and identity.get('seed')==native.get('seed') and identity.get('room')==native.get('room')
        and identity.get('stage')==native.get('stage'))
