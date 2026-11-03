"""Build local design fixtures, never runtime output or game evidence.

Run inside the mc checkout. No network, model, game, database or device access.
Only this directory receives generated files. The intact reference is copied;
browser crops demonstrate framing, not newly generated avatar assets.
"""
from __future__ import annotations

import hashlib
import csv
import json
import random
import shutil
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(name, data):
    (HERE / name).write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")



def motion_plan():
    """Inventory-only migration plan: no video generation or compatibility claim."""
    source = json.loads((ROOT / 'configs/vertical/materials/motion-index.json').read_text(encoding='utf-8'))
    strategies = {
        'idle': ('保留自然呼吸与眨眼；检查头部安全圆', '保留自然呼吸与眨眼；检查构图稳定'),
        'welcome': ('改为轻点头或脸侧小幅招呼；不能遮嘴', '重做肩部附近小幅招手；手掌不出框'),
        'explain': ('改为轻点头与眉眼回应；大摊掌不直接沿用', '重做胸前小摊掌；左右手均不得盖嘴'),
        'emphasis': ('面部和轻颔首为主；原大幅手势需改编', '低幅头肩与胸前强调；保证手指可辨识'),
        'listen': ('保留倾听语义；收敛头部位移并验证全帧', '保留倾听语义；稳定肩膀与视线'),
        'posture': ('改为上半身微调；膝前或袖口动作不宣称可见', '逐项重构为可见的上半身微动作'),
        'closing': ('轻微笑、点头告别；挥手仅脸侧小范围', '肩侧小幅告别；不横穿面部或出框'),
    }
    fields = ['legacy_id', 'legacy_title', 'category', 'legacy_start_frame', 'legacy_frames', 'circle_plan', 'landscape_plan', 'status']
    with (HERE / 'motion-reframe-plan.csv').open('w', encoding='utf-8-sig', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for clip in source['clips']:
            circle, landscape = strategies[clip['category']]
            writer.writerow({'legacy_id': clip['id'], 'legacy_title': clip['title'], 'category': clip['category'], 'legacy_start_frame': clip['start_frame'], 'legacy_frames': clip['frames'], 'circle_plan': circle, 'landscape_plan': landscape, 'status': 'PLANNED_NOT_GENERATED_NOT_VALIDATED'})
    assert len(source['clips']) == 50
    assert sum(c['id'].startswith('m') for c in source['clips']) == 48


def illustration():
    """Original vector scene: an illustrative aperture, NOT a Minecraft screenshot."""
    rng = random.Random(20261029)
    shapes = ['''<svg xmlns="http://www.w3.org/2000/svg" width="1472" height="828" viewBox="0 0 1472 828">
<defs><linearGradient id="sky" x2="0" y2="1"><stop stop-color="#9ac8db"/><stop offset="1" stop-color="#e0e6cc"/></linearGradient>
<linearGradient id="water" x2="1" y2="1"><stop stop-color="#78b7c6"/><stop offset="1" stop-color="#5c9dbb"/></linearGradient></defs>
<rect width="1472" height="828" fill="url(#sky)"/>
<g fill="#f2f6e9" opacity=".86"><path d="M90 118h174v26h92v31H90z"/><path d="M1120 88h168v24h76v26h-244z"/><path d="M606 52h116v18h82v23H606z"/></g>
<path d="M0 329h106v-65h109v41h81v-72h120v48h110v-24h91v59h114v-63h104v-39h100v77h133v-37h108v64h126v510H0z" fill="#99b29a"/>
<path d="M0 394h127v-39h120v-43h122v75h130v-33h148v34h129v-75h120v37h178v-34h119v60h139v452H0z" fill="#759276"/>
<rect y="426" width="1472" height="402" fill="#67845c"/>''']

    def point(i, j, z=0):
        return 736 + (i - j) * 38, 284 + (i + j) * 19 - z * 34

    def polygon(points, fill, stroke=None):
        value = ' '.join(f'{x:g},{y:g}' for x, y in points)
        shapes.append(f'<polygon points="{value}" fill="{fill}"' + (f' stroke="{stroke}" stroke-width=".6"' if stroke else '') + '/>')

    def block(i, j, z, top, left, right, height=34):
        x, y = point(i, j, z)
        polygon([(x - 38, y), (x, y + 19), (x, y + 19 + height), (x - 38, y + height)], left)
        polygon([(x, y + 19), (x + 38, y), (x + 38, y + height), (x, y + 19 + height)], right)
        polygon([(x, y - 19), (x + 38, y), (x, y + 19), (x - 38, y)], top)

    tree_sites = {(2, 3), (5, 2), (9, 2), (14, 4), (18, 5), (3, 9), (6, 10), (17, 10), (2, 16), (8, 17), (18, 17), (15, 20)}
    for depth in range(45):
        for i in range(23):
            j = depth - i
            if not 0 <= j < 23:
                continue
            x, y = point(i, j)
            if abs(i - (12 + (j // 6) % 2)) < 1.6:
                block(i, j, 0, rng.choice(['#75b2c2', '#82bec9', '#69aabe']), '#5a98ad', '#629eaf')
                if rng.random() > .48:
                    shapes.append(f'<path d="M{x-15} {y+2}h26" stroke="#d3edf0" stroke-width="2" opacity=".45"/>')
            else:
                top = rng.choice(['#90a96c', '#879f63', '#98af71', '#829b62', '#a4b87e'])
                block(i, j, 0, top, '#8b7954', '#736d4b')
                if rng.random() > .65:
                    shapes.append(f'<path d="M{x-10} {y+3}v-8m5 7v-12m6 12v-5" stroke="#5d7c4d" stroke-width="2" opacity=".6"/>')
            if (i, j) in tree_sites:
                for z in range(1, 4):
                    block(i, j, z, '#ab8c62', '#826647', '#6c543b')
                for di, dj in [(0, 0), (-.7, 0), (0, -.7), (.7, 0), (0, .7)]:
                    block(i+di, j+dj, 4.1, '#6d935b', '#50764b', '#426845', 44)
                block(i, j, 5.15, '#83a16b', '#618554', '#52734a', 39)
            if (i, j) == (8, 8):
                block(i, j, 1, '#c6a26d', '#9e7447', '#815d38', 39)
                xx, yy = point(i, j, 1)
                shapes.append(f'<path d="M{xx-19} {yy-9}l38 19m-38 0l38-19m-19-9v38" stroke="#755334" stroke-width="2"/>')
            if (i, j) == (9, 8):
                block(i, j, 1, '#bc925a', '#a37841', '#876334', 33)
                xx, yy = point(i, j, 1)
                shapes.append(f'<path d="M{xx} {yy+19}v16m-37-20l37 19 38-19" stroke="#614d30" stroke-width="3"/><rect x="{xx-4}" y="{yy+21}" width="8" height="9" fill="#d8caa1"/>')
    shapes.append('''<g opacity=".9" stroke="#f8fcf5" stroke-width="2"><path d="M725 414h22m-11-11v22"/></g>
<g transform="translate(438 744)"><rect width="594" height="66" rx="3" fill="#354638" opacity=".72"/>
<g fill="#c1c7b5" fill-opacity=".32" stroke="#d4dccb" stroke-opacity=".7">''')
    for i in range(9):
        shapes.append(f'<rect x="{8+i*65}" y="7" width="58" height="52"/>')
    shapes.append('''</g><rect x="8" y="7" width="58" height="52" fill="none" stroke="#f3ebc5" stroke-width="3"/>
<path d="M24 21h20v24H24z" fill="#b69a6b"/><path d="M28 21v24m6-24v24m6-24v24" stroke="#8a714c" stroke-width="2"/></g>
<rect x="20" y="788" width="217" height="26" rx="4" fill="#2a423d" opacity=".72"/>
<text x="31" y="807" fill="#f5f8f1" font-size="15" font-family="Microsoft YaHei, sans-serif">布局样稿 · 游戏非实机画面</text>
</svg>''')
    (HERE / "assets/game-illustration.svg").write_text('\n'.join(shapes), encoding="utf-8")


def main():
    active = subprocess.check_output(['git', 'branch', '--show-current'], cwd=ROOT, text=True).strip()
    if active != 'mc':
        raise RuntimeError('Design writes require the mc branch')
    assets = HERE / 'assets'
    assets.mkdir(exist_ok=True)
    avatar = ROOT / 'assets/vertical/student-dorm-720x1280.png'
    # The frozen JSON is authoritative; previews are derived copies, never a second design.
    canonical = ROOT / 'configs/layouts/mc-landscape-v1.json'
    layout = json.loads(canonical.read_text(encoding='utf-8'))
    assert layout['status'] == 'DESIGN_FROZEN' and layout['version'] == '1.0.0'
    assert layout['source_reference_sha256'] == digest(avatar), 'Reference changed; update the design version explicitly'
    shutil.copyfile(avatar, assets / 'avatar-reference.png')

    write_json('layout-spec.json', layout)
    (HERE / 'layout-spec.js').write_text('window.MC_LAYOUT = ' + json.dumps(layout, ensure_ascii=False, indent=2) + ';\n', encoding='utf-8')
    illustration()
    motion_plan()
    # Fully transparent base for a full-game overlay; not a production output page.
    (assets / 'programme-backplate.svg').write_text('''<svg xmlns="http://www.w3.org/2000/svg" width="1920" height="1080" viewBox="0 0 1920 1080"><title>Full-canvas transparent base; overlay elements are composed separately</title></svg>''', encoding='utf-8')
    evidence = []
    for relative, needles in [
        ('web/studio.html', ['9:16 / 720', 'vertical.css']),
        ('web/vertical.css', ['aspect-ratio:9/16']),
        ('web/room-overlay.js', ['w / 720', 'room-speech', 'renderCaption']),
        ('web/room-overlay.css', ['width:720px;height:1280px']),
        ('integration/obs.html', ['RoomOverlay', 'output/player', 'avatarVisual', 'renderer']),
        ('web/dsh-playback.js', ['runtime_epoch', 'progress', 'request_id']),
        ('web/local-stream.js', ['720', '1280', 'directOutput']),
        ('backend/room/defaults.mjs', ['mc_chat_side', 'max_comments', 'embedded', 'captions']),
        ('web/admin.html', ['overlay.mc_chat_side']),
        ('web/mc-chat-position.js', ['mc_chat_side', 'side_presets']),
        ('configs/layouts/mc-landscape-v1.json', ['DESIGN_FROZEN', 'side_presets']),
        ('scripts/receiver_service.py', ['output.html', 'output/player', 'player_metrics']),
        ('configs/characters/female-a.json', ['daylight', 'width', '林知夏']),
        ('docs/deployment/RTX3080_K02_RELEASE.md', ['720×1280', 'batch4', '唯一播放']),
    ]:
        p = ROOT / relative
        lines = p.read_text(encoding='utf-8-sig').splitlines()
        evidence.append({'path': relative, 'sha256': digest(p), 'line_evidence': {n: [i+1 for i, line in enumerate(lines) if n in line] for n in needles}})
    write_json('source-audit.json', {'branch': active, 'base_commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(), 'files': evidence, 'runtime_started': False, 'source_output_profile_changed': False})
    assert layout['regions']['game']['width'] * 9 == layout['regions']['game']['height'] * 16
    assert layout['avatar_variants']['landscape']['region']['width'] * 9 == layout['avatar_variants']['landscape']['region']['height'] * 16
    assert digest(assets / 'avatar-reference.png') == digest(avatar)
    for r in list(layout['regions'].values()) + [v['region'] for v in layout['avatar_variants'].values()]:
        assert r['x'] >= 0 and r['y'] >= 0 and r['x'] + r['width'] <= 1920 and r['y'] + r['height'] <= 1080
    for preset in layout['chat']['side_presets'].values():
        for r in preset.values():
            assert 0 <= r['x'] and r['x'] + r['width'] <= 1920
            assert 0 <= r['y'] and r['y'] + r['height'] <= 1080
    print('Built frozen MC layout v1.0.0 revision 4; left/right chat supported; new media and full MC runtime NOT implemented.')


if __name__ == '__main__':
    main()
