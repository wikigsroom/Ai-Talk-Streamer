"""Validate MC documents and data contracts without starting application services."""
from copy import deepcopy
from datetime import datetime, timezone
from importlib.metadata import version
from pathlib import Path
from urllib.parse import unquote
import hashlib
import json
import re
import subprocess
from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / 'docs/technical/mc-live-v1'
CONTRACTS = BASE / 'contracts'


def check():
    branch = subprocess.check_output(['git', 'branch', '--show-current'], cwd=ROOT, text=True).strip()
    assert branch == 'mc', 'MC checks must run on mc'
    load = lambda name: json.loads((CONTRACTS / name).read_text(encoding='utf-8'))
    schema, api, examples = load('game.schema.json'), load('openapi.json'), load('examples.json')
    Draft202012Validator.check_schema(schema)
    validators = {name: Draft202012Validator({'$schema': schema['$schema'], '$ref': '#/$defs/' + name,
                  '$defs': schema['$defs']}, format_checker=FormatChecker()) for name in schema['$defs']}
    by_name = {case['name']: case for case in examples['cases']}
    assert len(by_name) == len(examples['cases'])
    for case in examples['cases']:
        validators[case['definition']].validate(case['value'])
    negative_names = []

    def reject(name, sample, mutate):
        case = deepcopy(by_name[sample])
        mutate(case['value'])
        assert list(validators[case['definition']].iter_errors(case['value'])), name
        negative_names.append(name)

    reject('intent_goal_has_no_shell', 'intent-result-goal', lambda v: v['goal'].update(shell='invalid'))
    reject('application_request_has_no_command', 'application-start-request', lambda v: v.update(command='invalid'))
    reject('application_request_has_no_root', 'application-start-request', lambda v: v.update(root='private'))
    reject('application_timeout_is_bounded', 'application-start-request', lambda v: v.update(timeout=1801))
    reject('application_timeout_is_not_boolean', 'application-start-request', lambda v: v.update(timeout=True))
    reject('application_status_does_not_accept_timeout', 'application-status-request', lambda v: v.update(timeout=10))
    reject('application_result_has_no_private_paths', 'application-readiness', lambda v: v.update(executable='private'))
    reject('application_result_does_not_grant_auto', 'application-readiness', lambda v: v.update(automatic_input_authorized=True))
    reject('application_job_has_no_arbitrary_action', 'application-job', lambda v: v.update(action='shell'))
    reject('application_state_is_not_complete_delivery', 'application-console-state', lambda v: v.update(full_application_lifecycle_complete=True))
    reject('application_console_close_does_not_stop_services', 'application-console-stop', lambda v: v.update(live_services_stopped=True))
    reject('intent_goal_requires_count', 'intent-result-goal', lambda v: v['goal'].pop('count'))
    reject('intent_goal_count_positive', 'intent-result-goal', lambda v: v['goal'].update(count=0))
    reject('intent_clarify_has_no_goal', 'intent-result-clarify', lambda v: v.update(goal=by_name['intent-result-goal']['value']['goal']))
    reject('intent_clarify_requires_question', 'intent-result-clarify', lambda v: v.update(question=None))
    reject('intent_none_has_no_text', 'intent-result-none', lambda v: v.update(question='untrusted'))
    reject('intent_pending_requires_source', 'audience-intent-pending', lambda v: v.update(source_event_ids=[]))
    reject('intent_sources_bounded', 'audience-intent-pending', lambda v: v.update(source_event_ids=[f'source-{i}' for i in range(5)]))
    reject('intent_source_hash_required', 'audience-intent-pending', lambda v: v.update(source_hash='invalid'))
    reject('intent_raw_text_not_persisted', 'audience-intent-pending', lambda v: v.update(raw_text='viewer message'))
    reject('intent_resolve_requires_goal', 'audience-intent-resolve', lambda v: v.pop('goal'))
    reject('intent_dismiss_has_no_goal', 'audience-intent-dismiss', lambda v: v.update(goal=by_name['intent-result-goal']['value']['goal']))
    reject('intent_config_interval_bounded', 'audience-intent-config', lambda v: v['patch']['audience_intents'].update(min_interval_ms=0))
    reject('intent_config_no_tools', 'audience-intent-config', lambda v: v['patch']['audience_intents'].update(tools=['shell']))
    reject('intent_pending_limit_fixed', 'audience-intent-status', lambda v: v.update(pending_limit=32))
    reject('auto_requires_epoch', 'control-auto', lambda v: v.pop('expected_control_epoch'))
    reject('gather_positive_count', 'task-start', lambda v: v['goal'].update(count=0))
    reject('unknown_goal_field_rejected', 'task-start', lambda v: v['goal'].update(shell='invalid'))
    reject('planting_requires_explicit_cell', 'plant-wheat-goal', lambda v: v.pop('target'))
    reject('planting_target_has_dimension', 'plant-wheat-goal', lambda v: v['target'].pop('dimension'))
    reject('planting_target_uses_block_coordinates', 'plant-wheat-goal', lambda v: v['target'].update(x=1.25))
    reject('planting_target_cannot_change_eating', 'plant-carrot-goal', lambda v: v.update(purpose='eat'))
    reject('planting_target_disallows_arbitrary_blocks', 'plant-wheat-goal', lambda v: v.update(item_id='minecraft:stone'))
    reject('planting_target_disallows_mod_seeds', 'plant-wheat-goal', lambda v: v.update(item_id='mod:wheat_seeds'))
    reject('planting_target_rejects_extra_fields', 'plant-wheat-goal', lambda v: v['target'].update(command='invalid'))
    reject('success_requires_evidence', 'task-complete', lambda v: v.update(evidence=[]))
    reject('success_requires_verified_effect', 'task-complete', lambda v: v.update(effect_status='unknown'))
    reject('room_side_enum', 'room-side', lambda v: v['patch']['overlay'].update(mc_chat_side='middle'))
    reject('automation_requires_auto_and_lease', 'state-manual', lambda v: v.update(automation_ready=True))
    reject('fresh_requires_connected', 'state-manual', lambda v: v.update(connected=False))
    reject('vision_single_concurrency', 'default-config', lambda v: v['vision'].update(max_concurrency=2))
    reject('query_kind_payload_match', 'recipe-query', lambda v: v.update(params={'goal': {'skill': 'return_base', 'base_id': 'x'}}))
    reject('ws_known_message_types_only', 'bridge-hello', lambda v: v.update(type='arbitrary_command'))
    reject('wire_control_operation_correlation', 'bridge-control_request', lambda v: v['payload'].pop('operation_id'))
    reject('lease_requires_b_heartbeat_reference', 'bridge-lease_grant', lambda v: v['payload'].pop('based_on_heartbeat_seq'))
    reject('vote_requires_two_options', 'vote-create', lambda v: v.update(options=v['options'][:1]))
    reject('vote_duration_bounded', 'vote-create', lambda v: v.update(duration_seconds=121))
    reject('converted_suggestion_requires_task', 'suggestion-converted-fixture', lambda v: v.update(task_id=None))
    reject('unconverted_suggestion_has_no_task', 'suggestion-accepted', lambda v: v.update(task_id='invalid-linked-task'))
    reject('active_vote_has_no_winner', 'vote-active', lambda v: v.update(winning_option_id='logs'))
    reject('cancel_vote_has_no_selection', 'vote-close', lambda v: v.update(action='cancel', selected_option_id='logs'))
    reject('ledger_query_one_task_bound', 'ledger-query', lambda v: v['params'].update(task_ids=['task-a', 'task-b']))
    reject('base_position_must_come_from_observation', 'base-create', lambda v: v.update(position={'x': 0, 'y': 0, 'z': 0}))
    reject('checkpoint_requires_released_inputs', 'checkpoint-record', lambda v: v['snapshot'].update(inputs_released=False))
    reject('ledger_found_requires_task', 'ledger-result', lambda v: v['entries'][0].update(task=None))
    reject('disposition_acknowledges_unknown', 'task-disposition-request', lambda v: v.update(acknowledge_unknown=False))
    reject('disposition_requires_released_inputs', 'task-disposition', lambda v: v['observed_context'].update(inputs_released=False))
    reject('world_goal_bounded_steps', 'world-goal-create', lambda v: v.update(steps=v['steps'] * 17))
    reject('completed_step_requires_proof', 'world-goal', lambda v: v['steps'][0].update(state='completed'))
    reject('observation_proof_has_no_task', 'world-goal-proof', lambda v: v.update(task_id='invented-task'))
    reject('frame_dimensions_bounded', 'frame-observation', lambda v: v.update(width=1921))
    reject('vision_requires_unknowns', 'vision-result', lambda v: v.pop('unknowns'))
    reject('vision_source_is_explicit', 'vision-result', lambda v: v.update(source='observed_game_fact'))
    reject('vision_age_nonnegative', 'vision-result', lambda v: v.update(age_ms=-1))
    reject('vision_lock_hash_is_sha256', 'vision-runtime-lock', lambda v: v['model'].update(sha256='not-a-hash'))
    reject('vision_purpose_is_allowlisted', 'observation-query', lambda v: v['params'].update(purpose='shell'))
    reject('audience_dispatch_requires_revision', 'suggestion-dispatch', lambda v: v.pop('expected_revision'))
    reject('audience_origin_requires_vote_reference', 'audience-suggestion', lambda v: v['origin'].update(kind='vote'))
    reject('audience_source_count_has_origin', 'audience-suggestion', lambda v: v.pop('origin'))
    reject('audience_feedback_cannot_claim_spoken', 'audience-feedback', lambda v: v.update(speech_status='spoken'))
    reject('audience_success_requires_evidence', 'audience-feedback', lambda v: v.update(evidence=[]))
    reject('audience_summary_is_bounded', 'audience-summary', lambda v: v.update(suggestions=v['suggestions']*17))
    reject('recipe_is_not_inventory_verification', 'recipe-result', lambda v: v.update(inventory_checked=True))
    reject('recipe_unknowns_required', 'recipe-result', lambda v: v.update(unknown_fields=[]))
    reject('recipe_choices_are_bounded', 'recipe-result', lambda v: v.update(recipes=v['recipes']*17))
    reject('recipe_alternatives_are_unique', 'recipe-result', lambda v: v['recipes'][0]['slots'][0].update(alternatives=['minecraft:iron_ingot']*2))
    reject('base_selection_requires_world_revision', 'base-select', lambda v: v.pop('expected_world_revision'))
    reject('base_selection_does_not_take_coordinates', 'base-select', lambda v: v.update(position={'x': 1, 'y': 64, 'z': 1}))
    reject('public_task_cannot_supply_base_coordinates', 'return-base-request', lambda v: v.update(base_target=by_name['base-target']['value']))
    reject('public_query_cannot_supply_base_coordinates', 'return-base-query', lambda v: v['params'].update(base_target=by_name['base-target']['value']))
    reject('return_base_task_requires_bound_target', 'return-base-task', lambda v: v.pop('base_target'))
    reject('return_base_wire_requires_bound_target', 'return-base-wire-start', lambda v: v['payload'].pop('base_target'))
    reject('return_base_query_wire_requires_bound_target', 'return-base-wire-query', lambda v: v['payload'].pop('base_target'))
    reject('base_reference_has_no_coordinates', 'base-ref', lambda v: v.update(position=by_name['base-target']['value']['position']))
    reject('non_base_task_has_no_base_reference', 'task-start', lambda v: v.update(base_ref=by_name['base-ref']['value']))
    reject('non_base_task_has_no_base_target', 'task-complete', lambda v: v.update(base_target=by_name['base-target']['value']))
    reject('base_target_source_is_operator_observed', 'base-target', lambda v: v.update(source='model_guessed'))
    reject('narration_answer_requires_completion_proof', 'narration-answered-proof', lambda v: v.pop('completion_event_seq'))
    reject('narration_queue_requires_request', 'narration-task-pending', lambda v: v.update(state='queued'))
    reject('narration_kind_matches_group', 'narration-task-pending', lambda v: v.update(group='gift'))
    reject('narration_retry_is_bounded', 'narration-task-pending', lambda v: v.update(attempt=3))
    reject('narration_cancel_has_no_prompt', 'narration-cancel', lambda v: v.update(text='untrusted extra field'))
    reject('narration_active_queue_is_bounded', 'narration-page', lambda v: v.update(active_items=[by_name['narration-task-pending']['value']] * 17))
    reject('feedback_answer_requires_completion_proof', 'suggestion-feedback-speech-answered', lambda v: v.pop('speech_completion_event_seq'))
    reject('feedback_speech_state_is_explicit', 'suggestion-feedback-speech-queued', lambda v: v.update(speech_status='probably_played'))
    reject('narration_merge_sources_bounded', 'narration-merged-gifts', lambda v: v.update(source_ids=[f'gift-{i}' for i in range(33)]))
    reject('narration_merge_sources_unique', 'narration-merged-gifts', lambda v: v.update(source_ids=['gift-a', 'gift-a']))
    reject('narration_topic_key_has_no_raw_text', 'narration-merged-gifts', lambda v: v.update(topic_key='观众原话'))
    reject('narration_wait_nonnegative', 'narration-merged-gifts', lambda v: v.update(waiting_ms=-1))
    reject('narration_cooldown_bounded', 'narration-merged-gifts', lambda v: v.update(cooldown_remaining_ms=15001))
    reject('narration_scheduler_page_required', 'narration-page', lambda v: v.pop('scheduler'))
    reject('scheduler_merge_window_bounded', 'narration-scheduler-config', lambda v: v.update(merge_window_ms=5001))
    reject('scheduler_aging_step_positive', 'narration-scheduler-config', lambda v: v.update(aging_step_ms=0))
    reject('scheduler_topic_interval_minimum', 'narration-scheduler-config', lambda v: v.update(topic_cooldown_ms=2999))
    reject('scheduler_critical_age_bounded', 'narration-scheduler-config', lambda v: v.update(interrupt_fresh_ms=3001))
    reject('scheduler_interrupt_cooldown_minimum', 'narration-scheduler-config', lambda v: v.update(interrupt_cooldown_ms=4999))
    reject('scheduler_has_no_prompt', 'narration-scheduler-config', lambda v: v.update(prompt='ignore facts'))
    reject('scheduler_interrupt_is_not_completion', 'narration-interruption', lambda v: v['last_interruption'].update(status='completed'))
    reject('scheduler_next_has_no_text', 'narration-interruption', lambda v: v.update(next_narration_id='下一条播报正文'))
    reject('unknown_gift_cannot_claim_count_one', 'room-gift-unknown', lambda v: v.update(gift_count=1))
    reject('gift_count_not_boolean', 'room-gift-unknown', lambda v: v.update(gift_count=True))
    reject('gift_known_count_not_null', 'room-gift-unknown', lambda v: v['platform_fields']['field_status'].update({'gift.count': 'known'}))
    reject('sc_fen_is_integral', 'room-sc-reported', lambda v: v['platform_fields']['superchat'].update(amount_fen=30.1))
    reject('sc_currency_is_explicit', 'room-sc-reported', lambda v: v['platform_fields']['superchat'].update(currency='unknown'))
    reject('unverified_source_has_no_paid_role_claims', 'room-sc-reported', lambda v: v['platform_fields'].update(quality='unverified'))
    reject('guard_level_is_platform_enum', 'room-sc-reported', lambda v: v['platform_fields']['roles'].update(guard_level=99))
    reject('emoji_image_is_https_bilibili_host', 'room-emote-reported', lambda v: v['platform_fields']['emoji'].update(image_url='https://evil.example/image.png'))
    reject('public_message_has_no_raw_user_id', 'room-sc-reported', lambda v: v.update(user_id='raw-platform-id'))
    reject('deleted_message_cannot_be_visible', 'room-sc-deleted', lambda v: v.update(hidden=False))
    reject('platform_delete_targets_not_empty', 'platform-sc-deletion', lambda v: v.update(deletion_target_ids=[]))
    reject('platform_delete_targets_bounded', 'platform-sc-deletion', lambda v: v.update(deletion_target_ids=[str(i) for i in range(101)]))
    reject('platform_delete_ids_preserve_strings', 'platform-sc-deletion', lambda v: v.update(deletion_target_ids=[9223372036854775801]))
    reject('platform_delete_source_is_selected_collector', 'platform-sc-deletion', lambda v: v.update(source='local_relay'))
    reject('platform_delete_has_no_shell', 'platform-sc-deletion', lambda v: v.update(shell='untrusted'))
    reject('support_count_is_not_negative', 'audience-support-current', lambda v: v.update(visible_events=-1))
    reject('support_count_is_not_boolean', 'audience-support-current', lambda v: v.update(visible_viewers=True))
    reject('support_ledger_is_bounded', 'audience-support-current', lambda v: v.update(tracked_events=4097))
    reject('unavailable_support_must_be_unknown', 'audience-support-unavailable', lambda v: v.update(visible_events=0))
    reject('available_support_requires_counts', 'audience-support-current', lambda v: v.update(visible_events=None))
    reject('support_coverage_is_explicit', 'audience-support-current', lambda v: v.update(coverage='guessed'))
    reject('support_has_no_platform_uid', 'audience-support-current', lambda v: v.update(user_id='private-platform-id'))
    reject('support_requires_evaluation_time', 'audience-support-current', lambda v: v.pop('evaluated_at'))
    reject('support_is_for_audience_origin', 'audience-suggestion-current-support', lambda v: v['origin'].update(kind='vote', vote_id='vote-example'))
    reject('support_requires_historical_count', 'audience-suggestion-current-support', lambda v: v.pop('support_count'))
    reject('support_global_budget_is_bounded', 'audience-support-budget', lambda v: v.update(tracked_events=32769))
    reject('support_budget_is_server_owned', 'audience-support-budget', lambda v: v.update(total_limit=1000000))
    reject('history_import_requires_current_world', 'history-import-request', lambda v: v.pop('world_session_id'))
    reject('history_source_is_whitelisted', 'history-query', lambda v: v['params'].update(source='sqlite_master'))
    reject('history_page_limit_is_bounded', 'history-query', lambda v: v['params'].update(limit=21))
    reject('history_partial_offset_is_bounded', 'history-query', lambda v: v['params'].update(offset=131072))
    reject('history_window_is_nonnegative', 'history-query', lambda v: v['params'].update(through=-1))
    reject('history_query_has_no_sql', 'history-query', lambda v: v['params'].update(sql='untrusted'))
    reject('history_chunk_retains_original_context', 'history-chunk', lambda v: v.pop('source_boot_id'))
    reject('history_chunk_hash_is_sha256', 'history-chunk', lambda v: v.update(payload_sha256='bad'))
    reject('history_chunk_has_a_byte_bound', 'history-chunk', lambda v: v.update(data_base64='AAAA' * 8193))
    reject('history_payload_size_is_bounded', 'history-chunk', lambda v: v.update(payload_bytes=131073))
    reject('history_page_summary_is_bounded', 'history-page', lambda v: v.update(items=v['items'] * 101))
    reject('history_capacity_is_server_owned', 'history-status', lambda v: v['limits'].update(entries=200001))
    reject('maintenance_summary_count_positive', 'maintenance-summary-payload', lambda v: v['value'].update(count=0))
    reject('maintenance_summary_has_no_raw_text', 'maintenance-summary-payload', lambda v: v['value'].update(raw_text='untrusted'))
    reject('retired_proof_is_not_a_full_goal', 'maintenance-retired-payload', lambda v: v['value']['summary'].update(goal={'skill': 'gather'}))
    reject('retired_proof_requires_known_effect', 'maintenance-retired-payload', lambda v: v['value']['summary'].update(effect_status='unknown'))
    reject('maintenance_run_requires_original_backup', 'maintenance-run-payload', lambda v: v['value'].update(originals_in_backup=False))
    reject('maintenance_run_cannot_claim_reclaimed_bytes', 'maintenance-run-payload', lambda v: v['value'].update(disk_bytes_reclaimed=True))
    reject('maintenance_chunk_has_no_delivery_ack', 'maintenance-summary-chunk', lambda v: v.update(acked_at=1))
    reject('maintenance_chunk_has_no_delivery_sequence', 'maintenance-summary-chunk', lambda v: v.update(sequence=1))
    reject('maintenance_global_run_has_no_invented_world', 'maintenance-run-chunk', lambda v: v.update(world_session_id='guessed-world'))
    reject('maintenance_summary_has_no_invented_boot', 'maintenance-summary-chunk', lambda v: v.update(source_boot_id='guessed-boot'))
    reject('retired_proof_keeps_original_boot', 'maintenance-retired-chunk', lambda v: v.update(source_boot_id=None))
    reject('maintenance_source_order_is_fixed', 'maintenance-import-completed', lambda v: v.update(source_order=['reliable', 'retired_tasks']))
    reject('maintenance_source_is_whitelisted', 'maintenance-summary-payload', lambda v: v.update(source='metadata'))

    reject('maintenance_request_has_no_command', 'maintenance-request-preview', lambda v: v.update(command='invalid'))
    reject('maintenance_request_has_no_path_override', 'maintenance-request-preview', lambda v: v.update(root='invalid'))
    reject('maintenance_action_whitelisted', 'maintenance-request-preview', lambda v: v.update(action='shell'))
    reject('maintenance_apply_requires_reviewed_hash', 'maintenance-request-apply', lambda v: v.pop('plan_sha256'))
    reject('maintenance_plan_not_a_path', 'maintenance-request-apply', lambda v: v.update(plan_file='../plan.json'))
    reject('maintenance_hash_exact_lowercase', 'maintenance-request-apply', lambda v: v.update(plan_sha256='A' * 64))
    reject('maintenance_result_has_no_raw_tasks', 'maintenance-result-preview', lambda v: v.update(task_ids=['private-task']))
    reject('maintenance_result_has_no_native_paths', 'maintenance-result-preview', lambda v: v.update(application_database='private'))
    reject('maintenance_job_has_no_raw_request', 'maintenance-job-running-apply', lambda v: v.update(request={'root':'private'}))
    reject('maintenance_plan_counts_nonnegative', 'maintenance-plan', lambda v: v['counts'].update(tasks=-1))
    reject('maintenance_state_does_not_claim_lifecycle', 'maintenance-state', lambda v: v.update(unified_lifecycle_available=True))
    reject('maintenance_queue_capacity_fixed', 'maintenance-state', lambda v: v['capacity'].update(pending=17))
    refs = []

    def walk(value, source):
        if isinstance(value, dict):
            if '$ref' in value:
                target, _, pointer = value['$ref'].partition('#')
                document = json.loads((source.parent / target).read_text(encoding='utf-8')) if target else (
                    schema if source.name == 'game.schema.json' else api)
                node = document
                for component in pointer.lstrip('/').split('/') if pointer else []:
                    node = node[unquote(component).replace('~1', '/').replace('~0', '~')]
                refs.append(value['$ref'])
            for item in value.values():
                walk(item, source)
        elif isinstance(value, list):
            for item in value:
                walk(item, source)

    walk(schema, CONTRACTS / 'game.schema.json')
    walk(api, CONTRACTS / 'openapi.json')
    assert api['openapi'] == '3.1.0'
    identifiers, statuses = [], {}
    for route, methods in api['paths'].items():
        for method, operation in methods.items():
            assert method in {'get', 'post'}
            identifiers.append(operation['operationId'])
            params = [p for p in operation.get('parameters', []) if p['in'] == 'path']
            assert set(re.findall(r'\{([^}]+)\}', route)) == {p['name'] for p in params}
            assert all(p.get('required') is True for p in params)
            status = operation['x-implementation-status']
            statuses[status] = statuses.get(status, 0) + 1
            if route.startswith('/api/dsh/game/'):
                expected = 'implemented_protocol_tests_only'
                assert status == expected
                if status != 'planned':
                    assert operation['x-game-runtime-acceptance'] == 'not_run'
    # Includes the locally implemented narration routes; this checks contract
    # structure and does not establish real game/model/playback acceptance.
    assert len(set(identifiers)) == len(identifiers) == 67
    maintenance_routes = [route for route in api['paths'] if route.startswith('/api/mc-maintenance/')]
    assert len(maintenance_routes) == 7
    for route in maintenance_routes:
        for operation in api['paths'][route].values():
            assert operation['servers'][0]['url'] == 'http://127.0.0.1:3093'
            assert operation['x-game-runtime-acceptance'] == 'not_run' and operation['security'] == []
    application_routes = [route for route in api['paths'] if route.startswith('/api/mc-runtime/')]
    assert len(application_routes) == 6 and sum(len(api['paths'][route]) for route in application_routes) == 7
    for route in application_routes:
        for operation in api['paths'][route].values():
            assert operation['servers'][0]['url'] == 'http://127.0.0.1:3093'
            assert operation['x-game-runtime-acceptance'] == 'not_run' and operation['security'] == []
    base_select = api['paths']['/api/dsh/game/worlds/{world_id}/bases/{base_id}/select']['post']
    assert base_select['requestBody']['content']['application/json']['schema']['$ref'].endswith('/BaseSelectRequest')
    task_filters = api['paths']['/api/dsh/game/tasks']['get'].get('parameters', [])
    assert any(p['in'] == 'query' and p['name'] == 'world_id' and not p.get('required', False)
               for p in task_filters)
    kinds = set(schema['$defs']['BridgeEnvelope']['properties']['type']['enum'])
    assert kinds == {c['value']['type'] for c in examples['cases'] if c['definition'] == 'BridgeEnvelope'}
    config = by_name['default-config']['value']['control']
    assert config['lease_ttl_ms'] >= 3 * config['heartbeat_ms']
    assert config['accept_within_ms'] <= config['state_stale_ms']
    markdown = sorted(BASE.rglob('*.md')) + [ROOT / p for p in (
        'docs/README.md', 'docs/MC直播总方案.md', 'docs/design/mc-landscape-v1/README.md',
        'docs/design/mc-landscape-v1/人物素材重制规范.md', 'AGENTS.md', 'backend/game/README.md',
        'game-adapters/minecraft/fabric/README.md')]
    links = 0
    for file in markdown:
        text = file.read_text(encoding='utf-8-sig')
        fence = None
        for number, line in enumerate(text.splitlines(), 1):
            assert not re.search(r'[\t ]+$', line), (file, number, 'trailing whitespace')
            found = re.match(r'^\s*(`{3,}|~{3,})', line)
            if found:
                marker = found.group(1)[0]
                if fence is None:
                    fence = marker
                elif marker == fence:
                    fence = None
        assert fence is None, (file, 'unclosed fence')
        for link in re.finditer(r'!?\[[^\]]*\]\(([^)]+)\)', text):
            target = link.group(1).strip().strip('<>')
            if re.match(r'^[a-zA-Z][a-zA-Z0-9+.-]*:', target):
                continue
            target = unquote(target.split('#', 1)[0].split('?', 1)[0])
            if target:
                assert (file.parent / target).resolve().exists(), (file, target)
                links += 1
    plan = json.loads((BASE / '完整交付清单.json').read_text(encoding='utf-8'))
    implementation = json.loads((BASE / 'implementation-status.json').read_text(encoding='utf-8'))
    base_ids = re.findall(r'^\| (V\d{2}) \|', (BASE / '07-实施与验收.md').read_text(encoding='utf-8'), re.M)
    full_text = (BASE / '08-完整交付规划.md').read_text(encoding='utf-8')
    completion_ids = re.findall(r'^\| (C\d{2}) \|', full_text, re.M)
    domain_ids = re.findall(r'^\| (D\d{2}) ', full_text, re.M)
    assert base_ids == [f'V{i:02d}' for i in range(1, 45)]
    assert completion_ids == [f'C{i:02d}' for i in range(1, 25)]
    assert domain_ids == [f'D{i:02d}' for i in range(1, 16)]
    assert plan['user_facing_release_count'] == 1
    assert [d['id'] for d in implementation['required_domains']] == domain_ids
    assert all(d['required'] for d in implementation['required_domains'])
    assert [c['id'] for c in implementation['acceptance']] == base_ids + completion_ids
    remaining_text = (BASE / '实现进度.md').read_text(encoding='utf-8').split('## 全系统剩余事项\n', 1)[1]
    remaining_rows = {match.group(1): match.group(2).strip() for match in re.finditer(
        r'^\| (D\d{2}) \| [^|]+ \| ([^|]+) \|$', remaining_text, re.M)}
    assert remaining_rows == {item['id']: item['remaining'] for item in implementation['required_domains']}
    flows = plan['operation_flows']
    flow_ids = re.findall(r'^\| (F\d{2}) ', full_text, re.M)
    binding_ids = re.findall(r'^\| (Q\d{2}) ', full_text, re.M)
    assert flow_ids == [f'F{i:02d}' for i in range(1, 13)]
    assert [f['id'] for f in flows] == flow_ids
    assert plan['runtime_binding_items'] == binding_ids == [f'Q{i:02d}' for i in range(1, 9)]
    execution_ids = re.findall(r'^\| (E\d{2}) ', full_text, re.M)
    assert plan['execution_constraints'] == execution_ids == [f'E{i:02d}' for i in range(1, 9)]
    assert plan['internal_builds_are_product_deliveries'] is False
    assert len(plan['release_manifest_required_fields']) == len(set(plan['release_manifest_required_fields'])) == 18
    assert {d for f in flows for d in f['domains']} == set(domain_ids)
    assert {a for f in flows for a in f['acceptance']} == set(base_ids + completion_ids)
    assert (ROOT / plan['operation_flow_source']).resolve() == (BASE / '08-完整交付规划.md').resolve()
    assert plan['plan_revision'] == implementation['plan_revision'] == '1.2'
    blueprint_path = (ROOT / plan['blueprint_source']).resolve()
    assert blueprint_path == (BASE / '09-全端实现蓝图.md').resolve()
    blueprint_text = blueprint_path.read_text(encoding='utf-8')
    assert re.findall(r'^\| (D\d{2}) \|', blueprint_text, re.M) == domain_ids
    assert len(re.findall(r'^## \d+\.', blueprint_text, re.M)) == plan['blueprint_document_sections'] == 16
    blueprint = plan['engineering_blueprint']
    assert [item['id'] for item in blueprint] == domain_ids
    defined_cases = set(base_ids + completion_ids)
    source_anchor_count = 0
    for item in blueprint:
        assert item['required'] is True
        assert item['acceptance'] and set(item['acceptance']) <= defined_cases
        assert len(item['acceptance']) == len(set(item['acceptance']))
        assert item['source_anchors']
        for anchor in item['source_anchors']:
            target = (ROOT / anchor).resolve()
            assert target.is_relative_to(ROOT) and target.exists(), (item['id'], anchor)
            source_anchor_count += 1
    assert {case for item in blueprint if item['id'] != 'D15' for case in item['acceptance']} == defined_cases
    assert blueprint[-1]['acceptance'] == base_ids + completion_ids
    assert plan['acceptance']['minimum_takeover_cycles'] == 20
    assert plan['acceptance']['next_day_recovery_required'] is True
    material = plan['materials']
    assert material['total_clips'] == len(material['packs']) * material['clips_per_pack'] == 100
    assert material['total_source_seconds'] == material['total_clips'] * material['planned_clip_seconds'] == 800
    layout_bytes = (ROOT / plan['layout_source']).read_bytes()
    layout_hash = hashlib.sha256(layout_bytes).hexdigest()
    assert layout_hash == '6d3e60cc91934dd44017f65f992cc4c820f52d84fffb2a3d90da759f3acd9f76'
    result = {'classification': 'DOCUMENT_AND_CONTRACT_VALIDATION_ONLY', 'result': 'PASS',
              'recorded_at': datetime.now(timezone.utc).isoformat(), 'branch': branch,
              'jsonschema_version': version('jsonschema'), 'schema_definitions': len(schema['$defs']),
              'valid_examples': len(examples['cases']), 'negative_contract_cases': len(negative_names),
              'negative_case_names': negative_names, 'ws_types_with_examples': len(kinds),
              'http_operations': len(identifiers), 'implementation_labels': statuses, 'local_json_refs': len(refs),
              'markdown_files_checked': len(markdown), 'local_markdown_links': links,
              'acceptance_cases_defined': 68, 'runtime_acceptance_cases_run_by_this_check': 0,
              'operation_flows_mapped': len(flow_ids), 'runtime_binding_items_defined': len(binding_ids),
              'single_release_execution_constraints_defined': len(execution_ids),
              'plan_revision': plan['plan_revision'], 'blueprint_domains_mapped': len(blueprint),
              'blueprint_document_sections': plan['blueprint_document_sections'],
              'blueprint_source_anchors_checked': source_anchor_count,
              'blueprint_non_audit_acceptance_coverage': len(defined_cases),
              'config_cross_field_example_checks': 2, 'mandatory_delivery_domains': 15,
              'canonical_layout_unchanged': True, 'canonical_layout_sha256': layout_hash,
              'openapi_check_scope': 'structure, operation identifiers, path parameters, labels, local JSON pointers',
              'full_openapi_spec_validator_run': False, 'application_services_started_by_this_check': False}
    (CONTRACTS / 'verification.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({k: result[k] for k in ('result', 'valid_examples', 'negative_contract_cases', 'http_operations',
                                          'markdown_files_checked', 'local_markdown_links')}, ensure_ascii=False))


if __name__ == '__main__':
    check()
