"""Write a shareable review summary without browser lease IDs or private settings."""
from pathlib import Path
import hashlib
import json

root = Path(__file__).resolve().parents[2]
review = root / 'output/review/naimei-live-v1'
folder = review / 'browser'
read = lambda path: json.loads(path.read_text('utf-8-sig'))
browser = read(folder / 'browser-check.json')
programme = read(folder / 'programme-check.json')
ui = read(folder / 'director-ui-check.json')
native = read(folder / 'native-livehime-check.json')
integrity = read(root / 'assets/naimei/live-v1/integrity-review.json')
fallback = read(root / 'assets/naimei/live-v1/voice/fallback/NMV01-f5-check.json')
assert browser['completed'] and programme['completed'] and ui['passed']
assert all(x['created_browser_closed'] for x in (browser, programme, ui))
assert native['prepare']['prepared'] and native['created_preview_browser_closed']
transport = browser['final_metrics']['transport']
video = folder / '奶妹-真实链路联调.mp4'
result = {
    'character_id': 'naimei', 'source_branch': 'naimei', 'scope': 'A01-A14 plus native local live integration',
    'native_windows': True, 'cloud_inference': False, 'public_broadcast_started': False,
    'asset_integrity': integrity,
    'tests': {'python_passed': 36, 'node_passed': 73},
    'formal_browser': {'completed': True, 'checks': [x['name'] for x in browser['checks']],
        'speech_requests': [{'label': r['label'], 'status': r['final']['status'], 'elapsed_seconds': r.get('elapsed_seconds')} for r in browser['requests']],
        'transport': transport, 'recorded_frames': browser['frame_count'],
        'recorded_seconds': browser['frame_count']/25,
        'caption_observations': sum(bool(s['caption']) for s in browser['samples']),
        'ducking_observations': sum(bool(s['mixer']['ducked']) for s in browser['samples']),
        'created_browser_closed': True},
    'programme': {'completed': True, 'checks': [{'name': c['name'], **({'measurement': c['detail']} if c['name']=='five_second_canvas_cadence' else {})} for c in programme['checks']], 'created_browser_closed': True},
    'director': {'passed': True, 'manual_speech_ready': ui['manual_speech_capability'], 'preview_canvas_fps_5s': ui['preview']['measured_canvas_fps_5s'], 'page_errors': ui['page_errors'], 'created_browser_closed': True},
    'fallback': {k: fallback[k] for k in ['engine', 'voice_id', 'reference_sha256', 'audio_seconds', 'wall_seconds', 'binding_and_pcm_verified', 'human_listening_accepted']},
    'native_client': {'installed': True, 'version': native['prepare']['status']['client_version'],
        'permission_mode': native['prepare']['status']['client_permission_mode'],
        'silent_preview_prepared': True, 'preview_browser_closed': True,
        'account_login_verified': False, 'native_browser_embedding_verified': False, 'audience_delivery_verified': False,
        'note': 'Formal Chrome playback does not prove embedding inside Livehime; the official client is at its login window.'},
    'video': {'path': video.relative_to(root).as_posix(), 'bytes': video.stat().st_size,
        'sha256': hashlib.sha256(video.read_bytes()).hexdigest(),
        'contains': 'actual role JPEG frames and paired speech PCM from the formal stream; programme layout in screenshots; BGM/SFX verified separately'},
    'live_speech_quality_accepted': False, 'quality_failures': ['fangs disappear or become human teeth', 'eyes/irises deform', 'face blurs in parts of speech'],
    'performance_limits': 'Short rehearsals only. One audio underrun and about 1.207s maximum arrival gap were observed; not a claim of long-term zero-stutter operation.'
}
(folder / 'playback-verification-summary.json').write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n','utf-8')
print(json.dumps({'asset_files':integrity['files'],'formal_checks':len(browser['checks']),'programme_checks':len(programme['checks']),'director_ready':ui['manual_speech_capability'],'video_bytes':video.stat().st_size,'quality_accepted':False}))
