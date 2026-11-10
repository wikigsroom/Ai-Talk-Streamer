"""One explicitly enabled live session across real runs and bounded outages.

This owner never fabricates a game result, changes a save, selects an item or
reopens a public broadcast. Ordinary retry/menu keys follow the pinned game
and the observed writable slot 3; explicit human takeover cancels them.
All mutations run under StrategyHost.action_lock; native callbacks only publish
their immutable terminal receipt and cannot acquire that lock in reverse order.
"""
from copy import deepcopy
import time

from .common import AdmissionError
from .combat_progress import CombatProgress


RECOVERABLE_CORE_ERRORS = frozenset({None, 'MODEL_TIMEOUT', 'MODEL_RATE_LIMIT',
    'MODEL_TRANSPORT_FAILED', 'MODEL_UPSTREAM_UNAVAILABLE', 'CURRENT_GAME_UNAVAILABLE',
    'CORE_NATIVE_STATE_NOT_FRESH', 'CORE_DECISION_CHANGED', 'CORE_PLAN_CONTEXT_CHANGED',
    'FRESH_CORE_DECISION_REQUIRED', 'CORE_TURN_DID_NOT_SUBMIT_A_CHOICE'})
RECOVERABLE_FAULTS = frozenset({'NAIMEI_CORE_UNAVAILABLE', 'GAME_BRIDGE_STALE',
    'LIVE_MEDIA_UNAVAILABLE', 'GAME_SIMULATION_STALLED', 'CORE_TURN_STALLED'})


def run_identity(snapshot):
    identity = snapshot.get('identity') or {}
    return tuple(identity.get(k) for k in ('controller', 'seed', 'restart', 'bridge'))


class LiveCycle:
    def __init__(self, host, *, clock=time.monotonic):
        self.host = host
        self.clock = clock
        self.enabled = False
        self.phase = 'observation_only'
        self.reason = None
        self.since = clock()
        self.run = None
        self.terminal = None
        self.completed_runs = 0
        self.retry_keys = 0
        self.recovery_attempts = 0
        self.recovery_receipt = None
        self.next_check = 0
        self.last_frame = None
        self.last_frame_at = clock()
        self.paused_at = None
        self.dead_since = None
        self.busy_at = None
        self.busy_marker = None
        self.media_failures = 0
        self.next_media_check = 0
        self.alert = None
        self.last_new_run = None
        self.recovery_history = []
        self.combat_progress = CombatProgress()

    def change(self, phase, reason=None):
        if (phase, reason) != (self.phase, self.reason):
            self.phase, self.reason, self.since = phase, reason, self.clock()
            self.host.audit.append('live_cycle_state', phase=phase, reason=reason,
                                   completed_runs=self.completed_runs)

    def status(self):
        return {'enabled': self.enabled, 'phase': self.phase, 'reason': self.reason,
                'phase_seconds': max(0, self.clock()-self.since),
                'completed_runs': self.completed_runs, 'ordinary_retry_keys': self.retry_keys,
                'recovery_attempts': self.recovery_attempts, 'alert': deepcopy(self.alert),
                'last_new_run': deepcopy(self.last_new_run),
                'combat_progress': self.combat_progress.status(),
                'public_broadcast_reopen_allowed': False}

    def stop(self, reason='operator_pause'):
        self.enabled = False
        self.recovery_receipt = None
        self.terminal = None
        self.change('operator_paused', reason)

    def start(self):
        self.enabled = True
        self.alert = None
        self.run = run_identity(self.host.service.snapshot)
        self.terminal = None
        self.recovery_attempts = 0
        self.last_frame = None
        self.last_frame_at = self.clock()
        self.paused_at = self.busy_at = None
        self.busy_marker = None
        self.dead_since = None
        self.media_failures = 0
        self.combat_progress.reset()
        self.host.runtime.controller.terminal_receipt = None
        self.next_media_check = self.clock()+3
        self.change('playing')

    def attention(self, reason):
        if getattr(self.host,'uninterrupted_gameplay',False):
            self.alert={'code':reason,'at_unix':time.time(),'gameplay_stopped':False,
                'operator_action_required':False,'component_repair_requested':True,'game_pause_requested':False}
            self.host.last_fault=reason
            self.host.audit.append('live_component_repair_requested',**self.alert)
            return
        self.enabled = False
        self.alert = {'code': reason, 'at_unix': time.time(), 'gameplay_stopped': True,
                      'operator_action_required': False, 'full_stack_restart_requested': True}
        self.change('restart_required', reason)
        self.host.last_fault = reason
        self.host.audit.append('live_cycle_attention', **self.alert)

    def hold_terminal(self, proof, *, observed_dead=False):
        """Preserve the real end reaction while withdrawing all gameplay input."""
        host = self.host
        host.native.protection.admit_current(host.native.process, host.native.progress())
        state = host.native.observe()
        if observed_dead:
            if state.get('dead') is not True:
                raise AdmissionError('REAL_NATIVE_DEATH_REQUIRED')
        else:
            identity = host.service.snapshot.get('identity') or {}
            if (proof.get('callback') != 'MC_POST_GAME_END'
                    or type(proof.get('is_game_over')) is not bool
                    or proof.get('start_seed') != identity.get('seed')
                    or proof.get('bridge_generation') != identity.get('bridge')
                    or proof.get('restart_count') != identity.get('restart')):
                raise AdmissionError('CURRENT_NATIVE_TERMINAL_PROOF_REQUIRED')
        self.run = run_identity(host.service.snapshot)
        self.terminal = {'seed': state['seed'], 'result':
                         ('death' if observed_dead or proof['is_game_over'] else 'ending'),
                         'proof': deepcopy(proof), 'observed_dead': observed_dead}
        host.runtime.controller.set_autopilot(False)
        host.service.configure(enabled=False, live=False)
        host.armed = False
        host.pause_pending = False
        if proof.get('manual_override') is True:
            host.strategy_automatic(False, required=False)
            self.stop('native_manual_override')
            return
        self.enabled = True
        self.retry_keys = 0
        self.next_check = self.clock()+10
        self.change('terminal_reaction', self.terminal['result'])
        # Core stays enabled for the original fact/voice/playback pipeline.
        # There are no offers and therefore no strategic actions in this hold.
        host.audit.append('live_terminal_held', terminal=self.terminal)

    def fault(self, reason, receipt=None):
        if getattr(self.host,'uninterrupted_gameplay',False):
            self.attention(reason)
            return
        if not self.enabled:
            return
        self.recovery_receipt = deepcopy(receipt)
        self.recovery_history = [at for at in self.recovery_history if self.clock()-at < 300]
        self.recovery_history.append(self.clock())
        self.recovery_attempts = 0
        self.next_check = self.clock()+2
        if len(self.recovery_history) > 3:
            self.attention('REPEATED_LIVE_FAULT_CIRCUIT_OPEN')
        elif reason not in RECOVERABLE_FAULTS:
            self.attention(reason)
        else:
            self.change('recovering', reason)

    def tick(self):
        if not self.enabled:
            return False
        try:
            return self._tick()
        except Exception as error:
            # One bad observer must not kill the watchdog and leave input armed.
            self.host.audit.append('live_cycle_check_failed', exception_type=type(error).__name__)
            if getattr(self.host,'uninterrupted_gameplay',False):
                self.attention('LIVE_CYCLE_NATIVE_CHECK_FAILED')
                return True
            try:
                self.host.control({'enabled': False, 'live': False}, origin='lifecycle')
            except Exception:
                pass
            self.attention('LIVE_CYCLE_NATIVE_CHECK_FAILED')
            return True

    def _tick(self):
        host, now = self.host, self.clock()
        if self.phase == 'recovering':
            self.recover()
            return True
        if self.phase in {'terminal_reaction', 'waiting_new_run', 'binding_new_run'}:
            self.next_run()
            return True
        if self.phase != 'playing':
            return False
        proof = getattr(host.runtime.controller, 'terminal_receipt', None)
        if proof and run_identity(host.service.snapshot) == self.run:
            self.hold_terminal(proof)
            return True
        if not host.armed:
            return False
        with host.service.lock:
            snapshot = deepcopy(host.service.snapshot)
        room, raw = snapshot.get('room') or {}, host.service.raw
        if room.get('dead'):
            # The game end callback normally follows the death animation. Use
            # two seconds of actual dead packets only if that callback is lost.
            self.dead_since = self.dead_since or now
            if now-self.dead_since >= 3:
                self.hold_terminal({}, observed_dead=True)
                return True
            return False
        self.dead_since = None
        if raw.get('strategy', {}).get('manual_override'):
            if getattr(host,'uninterrupted_gameplay',False):
                host.runtime.controller.set_autopilot(False);host.armed=False;self.enabled=False
            else:host.control({'enabled': False, 'live': False})
            self.change('operator_paused', 'native_manual_override')
            return True
        frame = snapshot.get('frame')
        if frame != self.last_frame:
            self.last_frame, self.last_frame_at = frame, now
        if room.get('paused'):
            self.paused_at = self.paused_at or now
            if now-self.paused_at > 15:
                # Never guess whether Escape would undo an operator pause.
                if not getattr(host,'uninterrupted_gameplay',False):
                    host.control({'enabled': False, 'live': False}, origin='lifecycle')
                self.attention('EXTERNAL_PAUSE_OR_FOCUS_LOSS')
                return True
        else:
            self.paused_at = None
            if now-self.last_frame_at > 15:
                host.watchdog_stop('GAME_SIMULATION_STALLED')
                return True
        view = {'connected': host.service.fresh(), 'age_ms': 0, 'data': snapshot}
        if self.combat_progress.update(view, enabled=host.armed and raw.get('enemy_observation_valid') is not False, now=now):
            if (self.alert or {}).get('code') != 'COMBAT_NO_DAMAGE_PROGRESS':
                host.watchdog_stop('COMBAT_NO_DAMAGE_PROGRESS')
            return True
        if now >= self.next_media_check:
            self.next_media_check = now+5
            try:
                core = host.core_status()
            except Exception:
                core = {}
            if self.core_turn_stalled(core,now):
                host.watchdog_stop('CORE_TURN_STALLED')
                return True
            healthy = host.live_media_ready()
            self.media_failures = 0 if healthy else self.media_failures+1
            if self.media_failures >= 3:
                host.watchdog_stop('LIVE_MEDIA_UNAVAILABLE')
                return True
        return False

    def core_turn_stalled(self,core,now):
        if not core.get('busy'):
            self.busy_at=self.busy_marker=None
            return False
        marker=(core.get('process_id'),core.get('continuous_session_id'),core.get('turns'))
        if self.busy_at is None or marker!=self.busy_marker:
            self.busy_at=now;self.busy_marker=marker
        budget=core.get('decision_budget_ms',55000)
        if type(budget) not in (int,float) or not 0<budget<=115000:budget=55000
        return now-self.busy_at>max(75,budget/1000+20)

    def next_run(self):
        host, now = self.host, self.clock()
        if now < self.next_check:
            return
        if host.native.manual_override():
            host.strategy_automatic(False, required=False)
            self.stop('native_manual_override')
            return
        ending=self.terminal['result']=='ending'
        if now-self.since > (120 if ending else 60):
            self.attention('NEXT_RUN_MENU_TIMEOUT')
            host.strategy_automatic(False, required=False)
            return
        progress=host.native.progress()
        host.native.protection.admit_current(host.native.process, progress)
        state = host.native.observe()
        if state['players'] == 1 and not state['dead'] and state['hp'] > 0 and state['seed'] != self.terminal['seed']:
            if self.phase != 'binding_new_run':
                host.strategy_automatic(False, required=False)
                # Reinstall only trusted input callbacks. This resets native
                # leases, inventory/route caches and the bridge incarnation.
                host.native.install_controller()
                self.change('binding_new_run')
                self.next_check = now+.5
                return
            snapshot = host.service.snapshot
            if (not host.service.fresh() or snapshot.get('identity', {}).get('seed') != state['seed']
                    or run_identity(snapshot) == self.run):
                self.next_check = now+.5
                return
            host.control({'enabled': True, 'live': True}, origin='lifecycle')
            self.completed_runs += 1
            self.last_new_run = {'previous_seed': self.terminal['seed'], 'seed': state['seed'],
                                 'at_unix': time.time(), 'slot': 3, 'ordinary_inputs_only': True}
            host.audit.append('live_next_run_verified', **self.last_new_run)
            self.start()
            return
        if state['players'] == 1 and not state['dead'] and state['seed'] == self.terminal['seed'] and self.terminal['result'] == 'death':
            # An extra life is a real continuation, not a new run. Do not send
            # another retry key into a resurrected living player.
            host.control({'enabled': True, 'live': True}, origin='lifecycle')
            host.audit.append('live_native_resurrection_verified', seed=state['seed'])
            self.start()
            return
        if self.phase == 'binding_new_run':
            raise AdmissionError('NEW_RUN_CHANGED_DURING_BINDING')
        if self.retry_keys >= (12 if ending else 5):
            self.attention('ORDINARY_NEXT_RUN_INPUT_NOT_ACCEPTED')
            host.strategy_automatic(False, required=False)
            return
        if self.phase == 'terminal_reaction':
            # Finish or cancel only this game's obsolete turn. Persona, long
            # memory, continuous DSH agent and actual spoken history survive.
            host.strategy_automatic(False, required=False)
            self.change('waiting_new_run', self.terminal['result'])
        key=self.ending_menu_key(progress) if ending else 'space'
        host.native.menu_key(key)
        self.retry_keys += 1
        self.next_check = now+3
        host.audit.append('live_ordinary_retry_input', key=key, attempt=self.retry_keys,
                          previous_seed=self.terminal['seed'])

    def ending_menu_key(self, progress):
        """Follow the observed title/file page, then bounded slot-3 startup.

        Credits permit only the original terminal-proof Space. Enter in an
        unknown surface requires our own observed FILE 3 selection plus the
        still-current native writable slot, just as fresh-start recovery does.
        """
        menu=self.host.native.menu_observation()
        if not isinstance(menu,dict):
            raise AdmissionError('REAL_NATIVE_ENDING_MENU_OBSERVATION_REQUIRED')
        page=menu.get('page')
        if page in {'title','opening_film'}:
            self.terminal['file3_selection_issued']=False
            return 'enter'
        if page=='file_select':
            self.terminal['file3_selection_issued']=False
            selected=menu.get('selected_file')
            if selected==3:
                self.terminal['file3_selection_issued']=True
                self.terminal['start_enter_count']=0
                return 'enter'
            if type(selected) is int and selected in {1,2}:
                return 'right'
            raise AdmissionError('OBSERVED_ENDING_FILE_SELECTION_REQUIRED')
        if self.terminal.get('file3_selection_issued'):
            if progress.get('slot')!=3 or progress.get('readonly') is not False:
                raise AdmissionError('ENDING_NATIVE_WRITABLE_SLOT3_REQUIRED')
            count=self.terminal.get('start_enter_count',0)+1
            if count>4:
                raise AdmissionError('BOUNDED_ENDING_SLOT3_STARTUP_EXHAUSTED')
            self.terminal['start_enter_count']=count
            return 'enter'
        return 'space'

    def recover(self):
        host, now = self.host, self.clock()
        if now < self.next_check:
            return
        if self.recovery_attempts >= 3 or now-self.since > 90:
            self.attention('LIVE_RECOVERY_EXHAUSTED')
            return
        self.recovery_attempts += 1
        self.next_check = now+(2, 5, 15)[self.recovery_attempts-1]
        try:
            core = host.core_status()
        except Exception:
            return
        if (core.get('last_error') not in RECOVERABLE_CORE_ERRORS
                or not host.approved_core(core)):
            self.attention(core.get('last_error') or 'APPROVED_CORE_IDENTITY_REQUIRED')
            return
        if core.get('ready') is not True or core.get('busy') or not host.live_media_ready() or not host.service.fresh():
            return
        host.native.protection.admit_current(host.native.process, host.native.progress())
        state = host.native.observe()
        if run_identity(host.service.snapshot) != self.run or state['seed'] != self.run[1]:
            self.attention('RECOVERY_RUN_IDENTITY_CHANGED')
            return
        ack = host.service.raw.get('strategy', {}).get('pause_ack') or {}
        receipt = self.recovery_receipt or {}
        if (not receipt.get('normal_game_pause_acknowledged')
                or not state['paused'] or state['dead']
                or state['frame'] != receipt.get('stable_frame')
                or ack.get('id') != receipt.get('pause_input_ack', {}).get('id')
                or host.service.raw.get('strategy', {}).get('manual_override')):
            self.attention('RECOVERY_OWNED_PAUSE_REQUIRED')
            return
        reason = self.reason
        host.control({'enabled': True, 'live': True}, origin='lifecycle')
        host.audit.append('live_transient_recovery_verified', reason=reason,
                          attempt=self.recovery_attempts, seed=state['seed'])
        self.start()
