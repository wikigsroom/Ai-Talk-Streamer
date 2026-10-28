'use strict';
(() => {
  const $ = s => document.querySelector(s), $$ = s => [...document.querySelectorAll(s)], room = window.adminRoom = new RoomClient();
  let state, studio, platforms, dsh, currentPage = 'overview', previousAgentJob = '', agentHistory = [], messageMap = new Map(), chatMap = new Map(), closed = false;
  const titles = { overview: '让每一次相遇，都有温度。', music: '声音，刚刚好的距离。', visual: '把日光，留在小房间。', messages: '认真听，也认真回应。', agent: '镜头之外，聊聊心里话。', logs: '让直播，安心地继续。' };
  const time = at => new Date(at).toLocaleTimeString('zh-CN', { hour12: false });
  const duration = s => Math.floor(Math.max(0, s) / 60) + ':' + Math.floor(Math.max(0, s) % 60).toString().padStart(2, '0');
  const node = (tag, className, text) => { const el = document.createElement(tag); if (className) el.className = className; if (text != null) el.textContent = text; return el; };
  const empty = text => node('div', 'empty', text);
  const valueAt = (o, path) => path.split('.').reduce((v, k) => v?.[k], o);
  function feedback(text, error = false) { const el = $('#feedback'); el.textContent = text; el.classList.toggle('error', error); el.hidden = false; clearTimeout(feedback.timer); feedback.timer = setTimeout(() => { el.hidden = true; }, error ? 14000 : 4500); }
  function friendly(error) {
    const code = error.message || String(error);
    return ({ BROADCAST_NOT_LIVE: '本地会话尚未开始。请先点击“开始本地会话”，等正式播放端就绪后再播报。', ROOM_CONFIG_CONFLICT_REFRESH: '另一页面已修改设置，已刷新最新值，请重新操作。', AGENT_BUSY: '知夏正在回复上一条私聊，请等待或取消。', CHANNEL_COMPATIBILITY_REQUIRED: 'LLM 渠道尚未就绪，请到平台连接页检查渠道。', BGM_AUTOPLAY_BLOCKED: '播放端的浏览器阻止了自动播放，请刷新直播姬素材并启用素材音频。' })[code] || '操作未完成：' + code;
  }
  async function run(work, text) { try { const value = await work(); if (text) feedback(text); return value; } catch (error) { feedback(friendly(error), true); return null; } }
  async function api(path, body) { const r = await fetch('/api/dsh/' + path, { method: body ? 'POST' : 'GET', headers: body ? { 'Content-Type': 'application/json' } : {}, ...(body ? { body: JSON.stringify(body) } : {}) }); const v = await r.json(); if (!r.ok) throw Error(v.error || 'SERVICE_UNAVAILABLE'); return v; }
  function page(name) { currentPage = name; $$('.nav').forEach(b => { b.classList.toggle('active', b.dataset.page === name); b.setAttribute('aria-current', b.dataset.page === name ? 'page' : 'false'); }); $$('[data-view]').forEach(s => s.hidden = s.dataset.view !== name); $('#pageTitle').textContent = titles[name]; if (name === 'agent') void loadAgent(); if (name === 'logs') void loadLogs(); if (name !== 'music') { $('#audition').pause(); $('#audition').hidden = true; } }
  $$('[data-page],[data-goto]').forEach(b => b.addEventListener('click', () => page(b.dataset.page || b.dataset.goto)));
  function button(text, action, id, className) { const b = node('button', className, text); b.type = 'button'; b.dataset.action = action; if (id) b.dataset.id = id; return b; }
  function syncInputs() {
    $$('[data-setting]').forEach(el => { if (el === document.activeElement) return; const v = valueAt(state.settings, el.dataset.setting); if (el.type === 'checkbox') el.checked = v; else { el.value = v; displayRange(el); } });
    $$('[data-value]').forEach(el => { if (el !== document.activeElement && !el.dataset.dirty) el.value = valueAt(state.settings, el.dataset.value); });
    if (!$('#moderationForm').dataset.dirty) { $('#blockedWords').value = state.settings.moderation.blocked_words.join('\n'); $('#blockedNames').value = state.settings.moderation.blocked_names.join('\n'); }
    $$('[data-filter]').forEach(b => b.classList.toggle('selected', b.dataset.filter === state.settings.filters.preset));
    $$('[data-theme]').forEach(b => b.classList.toggle('selected', b.dataset.theme === state.settings.overlay.theme));
    if ($('#repeatMode') !== document.activeElement) $('#repeatMode').value = state.music.repeat; $('#shuffleMusic').checked = state.music.shuffle;
  }
  function displayRange(el) { const output = el.parentElement.querySelector('output'); if (!output) return; const key = el.dataset.setting || ''; const n = Number(el.value); output.textContent = key.endsWith('_ms') ? n + ' ms' : key.includes('volume') || key.endsWith('level') || key.endsWith('opacity') ? Math.round(n * 100) + '%' : key.endsWith('lifetime') ? n + ' 秒' : key.endsWith('comments') ? n + ' 条' : n.toFixed(2); }
  let configChain = Promise.resolve();
  function configure(patch) { const next = configChain.then(() => room.configure(patch)); configChain = next.catch(() => {}); return run(() => next); }
  $$('[data-setting]').forEach(el => {
    if (el.type === 'range') el.addEventListener('input', () => displayRange(el));
    el.addEventListener('change', () => { const [group, key] = el.dataset.setting.split('.'), value = el.type === 'checkbox' ? el.checked : Number(el.value), patch = { [group]: { [key]: value } }; if (group === 'filters') patch.filters.preset = 'custom'; void configure(patch); });
  });
  $$('[data-value]').forEach(el => el.addEventListener('input', () => { el.dataset.dirty = '1'; }));
  $('#identityForm').addEventListener('submit', e => { e.preventDefault(); void run(async () => { const patch = Object.fromEntries([...new FormData(e.currentTarget)]); await room.configure({ identity: patch }); $$('[data-value]').forEach(el => delete el.dataset.dirty); }, '房间标题、话题与公告已更新。'); });
  $$('[data-filter]').forEach(b => b.addEventListener('click', () => void configure({ filters: state.presets[b.dataset.filter] })));
  $$('[data-theme]').forEach(b => b.addEventListener('click', () => void configure({ overlay: { theme: b.dataset.theme } })));
  function music(action, extra = {}) { return run(() => room.post('music', { action, ...extra })); }
  $$('[data-music]').forEach(b => b.addEventListener('click', () => { let action = b.dataset.music; if (action === 'toggle') action = state.music.playing ? 'pause' : 'play'; void music(action); }));
  $('#repeatMode').addEventListener('change', e => void music('repeat', { value: e.target.value })); $('#shuffleMusic').addEventListener('change', e => void music('shuffle', { value: e.target.checked }));
  $('#musicSeek').addEventListener('change', e => void music('seek', { seconds: Number(e.target.value) }));
  function renderMusic() {
    const track = state.tracks.find(t => t.id === state.music.track_id); $('#nowTrack').textContent = track?.name || '歌单为空'; $('#musicState').textContent = state.music.playing ? '播放中 · ' + (state.music.repeat === 'one' ? '单曲循环' : '歌单') : '音乐已暂停';
    const signature = JSON.stringify([state.tracks, state.music.track_id]); if (renderMusic.signature === signature) return; renderMusic.signature = signature;
    $('#playlist').replaceChildren(...state.tracks.map((t, i) => { const row = node('div', 'track' + (t.id === state.music.track_id ? ' active' : '')); row.append(node('span', 'track-num', String(i + 1).padStart(2, '0'))); const info = node('div', 'track-info'); info.append(node('strong', '', t.name), node('small', '', (t.builtin ? '原创内置' : '本地上传') + ' · ' + duration(t.duration) + ' · ' + (t.bytes / 1024 / 1024).toFixed(1) + ' MB')); row.append(info); const actions = node('div', 'track-actions'); actions.append(button('播放', 'track-play', t.id), button('仅后台试听', 'track-audition', t.id), button('↑', 'track-up', t.id), button('↓', 'track-down', t.id)); if (!t.builtin) actions.append(button('删除', 'track-delete', t.id)); row.append(actions); return row; }));
  }
  function renderMixer() {
    const p = state.player;
    $('#mixerHealth').textContent = !p?.connected ? '等待正式播放端回报。若已打开直播姬，请刷新浏览器素材。' : '正式播放端：' + (p.muted ? '总静音' : p.audio_state === 'running' ? '音频运行中' : p.audio_state) + ' · BGM ' + (p.music_playing ? '正在播放' : '暂停') + ' · 人声避让 ' + (p.ducked ? '已压低音乐' : '待机') + (p.error ? ' · 错误：' + p.error : '');
  }
  function content(m) { return m.type === 'gift' ? '送来 ' + m.gift_name + ' × ' + m.gift_count : m.type === 'follow' ? '关注了直播间' : m.text || '来到直播间'; }
  function renderMessages() {
    messageMap = new Map(state.messages.map(m => [m.id, m]));
    const recent = state.messages.filter(m => !room.blocked(m)).slice(-4).reverse(); $('#recentMessages').replaceChildren(...(recent.length ? recent.map(m => { const el = node('div', 'recent-item'); el.append(node('strong', '', m.nickname), node('span', '', (m.test ? '[测试] ' : '') + content(m)), node('time', '', time(m.received_at))); return el; }) : [empty('暂时还没有消息。开播后，观众的评论与礼物会出现在这里。')]));
    const featured = state.board.featured; $('#featuredMessage').replaceChildren(); if (featured) $('#featuredMessage').append(node('small', '', featured.nickname + (featured.test ? ' · 本地测试' : '')), node('div', '', featured.text)); else $('#featuredMessage').append(empty('当前没有留言上墙。可以从收件箱选择一条，或添加导播留言。'));
    const query = $('#messageSearch').value.toLocaleLowerCase(), type = $('#messageType').value;
    const messages = state.messages.filter(m => (!query || (m.nickname + m.text + m.gift_name).toLocaleLowerCase().includes(query)) && (type === 'hidden' ? room.blocked(m) : type === 'all' || m.type === type)).reverse(); $('#inboxCount').textContent = state.messages.length + ' 条';
    const signature = JSON.stringify([messages, state.board.pinned_id, state.board.featured_id]); if (renderMessages.signature === signature) return; renderMessages.signature = signature;
    $('#inbox').replaceChildren(...(messages.length ? messages.map(m => { const el = node('article', 'message-item' + (room.blocked(m) ? ' is-hidden' : '')); const heading = node('div', 'message-heading'); heading.append(node('strong', '', m.nickname), node('span', 'badge', m.test ? '本地测试' : m.notice_kind === 'superchat' ? '醒目留言' : ({ comment: '评论', gift: '礼物', note: '导播留言', follow: '关注' }[m.type] || m.type)), node('time', '', time(m.received_at))); if (m.answered) heading.append(node('span', 'badge', '已答'));
      el.append(heading, node('div', 'message-content', content(m))); const actions = node('div', 'message-actions');
      if (!room.blocked(m)) actions.append(button(state.board.featured_id === m.id ? '正在上墙' : '留言上墙', 'message-feature', m.id), button(state.board.pinned_id === m.id ? '已置顶' : '置顶', 'message-pin', m.id));
      if (m.text) actions.append(button('填入回复', 'message-reply', m.id)); if (!m.answered) actions.append(button('标记已答', 'message-answered', m.id)); actions.append(button(m.hidden ? '恢复显示' : '隐藏', m.hidden ? 'message-restore' : 'message-hide', m.id), button('屏蔽昵称', 'message-block', m.id)); el.append(actions); return el; }) : [empty('没有符合条件的消息。')]));
  }
  async function loadAgent() {
    return run(async () => { const v = await api('room/agent'); agentHistory = v.history; renderAgent(); });
  }
  function renderAgent() {
    chatMap = new Map(); $('#agentHistory').replaceChildren(...(agentHistory.length ? agentHistory.map((turn, i) => { const el = node('div', 'chat-turn ' + turn.role); el.append(node('small', '', (turn.role === 'user' ? '你 · 导播' : '林知夏') + ' / ' + time(turn.at)), node('p', '', turn.text)); if (turn.role === 'assistant') { chatMap.set(String(i), turn.text); el.append(button('送到直播播报 ↗', 'agent-speak', String(i))); } return el; }) : [empty('这里是后台私聊。可以先讨论话题，再决定把哪句话送到直播间。')])); $('#agentHistory').scrollTop = $('#agentHistory').scrollHeight;
  }
  function render() {
    if (!room.state || closed) return; state = room.state;
    $('#connection').classList.toggle('online', room.connected); $('#connection').lastChild.textContent = room.connected ? '控制已连接' : '正在重连'; $('#revision').textContent = '设置版本 ' + state.revision;
    const broadcast = state.broadcast, live = broadcast?.state === 'LIVE'; $('#sessionState').textContent = !broadcast ? '本地会话 · 未开始' : '本地会话 · ' + ({ LIVE: '运行中', PAUSED: '暂停', PREPARING: '准备中', RECOVERING: '等待播放端恢复', DRAINING: '正在结束' }[broadcast.state] || broadcast.state);
    $('#startSession').textContent = ['PAUSED', 'RECOVERING'].includes(broadcast?.state) ? '恢复本地会话' : '开始本地会话'; $('#startSession').disabled = !!broadcast && !['PAUSED', 'RECOVERING'].includes(broadcast.state); $('#pauseSession').disabled = !live; $('#endSession').disabled = !broadcast;
    $('#speechStatus').textContent = state.active ? '当前回复：' + state.active.status + ' · ' + state.active.request_id : live ? '会话已就绪，可以播报。' : '先开始本地会话，再发送角色播报。';
    $('#askAgent').disabled = state.agent.job?.status === 'RUNNING'; $('#agentStatus').textContent = state.agent.job?.status === 'RUNNING' ? '知夏正在思考… 私聊不会进入直播语音。' : state.agent.job?.status === 'FAILED' ? '本次私聊失败：' + state.agent.job.error : state.agent.job?.status === 'CANCELLED' ? '已取消本次生成。' : '';
    const jobKey = JSON.stringify([state.agent.session, state.agent.job?.id, state.agent.job?.status]); if (jobKey !== previousAgentJob) { previousAgentJob = jobKey; void loadAgent(); }
    syncInputs(); renderMusic(); renderMixer(); renderMessages(); renderRuntime();
  }
  $('#messageSearch').addEventListener('input', renderMessages); $('#messageType').addEventListener('change', renderMessages);
  document.addEventListener('click', e => {
    const b = e.target.closest('[data-action]'); if (!b || !state) return; const { action, id } = b.dataset;
    if (action === 'track-play') void music('play', { track_id: id });
    else if (action === 'track-audition') { const t = state.tracks.find(t => t.id === id); $('#audition').src = t.url; $('#audition').hidden = false; void run(() => $('#audition').play()); }
    else if (action === 'track-delete') { if (confirm('删除这首上传的音乐及原文件？')) void run(() => room.post('tracks/delete', { id })); }
    else if (['track-up', 'track-down'].includes(action)) { const ids = state.tracks.map(t => t.id), at = ids.indexOf(id), next = at + (action === 'track-up' ? -1 : 1); if (next >= 0 && next < ids.length) { [ids[at], ids[next]] = [ids[next], ids[at]]; void music('order', { ids }); } }
    else if (action === 'message-reply') { const m = messageMap.get(id); page('overview'); $('#speechText').value = '回复' + m.nickname + '：' + m.text; $('#speechMode').value = 'chat'; $('#speechText').focus(); }
    else if (action === 'message-block') { const m = messageMap.get(id); void configure({ moderation: { blocked_names: [...new Set([...state.settings.moderation.blocked_names, m.nickname])] } }); }
    else if (action.startsWith('message-')) void run(() => room.post('messages', { action: action.slice(8), id }));
    else if (action === 'agent-speak') { const text = chatMap.get(id); page('overview'); $('#speechText').value = text; $('#speechMode').value = 'echo'; $('#speechText').focus(); feedback('已填入播报框；请检查后点击“送到直播播报”。'); }
  });
  $('#speechForm').addEventListener('submit', e => { e.preventDefault(); const text = $('#speechText').value.trim(), mode = $('#speechMode').value; void run(async () => { const r = await room.post('speak', { text, mode, idempotency_key: crypto.randomUUID() }); $('#speechText').value = ''; feedback('已进入角色回复队列：' + r.request_id); }); });
  $('#cancelSpeech').addEventListener('click', () => void run(() => api('cancel', {}), '已停止当前回复。'));
  $('#panic').addEventListener('click', () => void run(() => room.post('panic', {}), '已取消当前及待播回复、暂停音乐并将节目总静音。可在“音乐与声音”取消总静音。'));
  $('#startSession').addEventListener('click', async e => { e.target.disabled = true; await run(() => api('platforms/bilibili/' + (['PAUSED', 'RECOVERING'].includes(state.broadcast?.state) ? 'resume' : 'start'), {}), '本地交互会话已就绪。公开开播请在官方直播姬操作。'); await room.refresh().catch(() => {}); });
  $('#pauseSession').addEventListener('click', () => void run(async () => { await api('broadcast/pause', { broadcast_id: state.broadcast.broadcast_id, expected_revision: state.broadcast.revision }); await room.refresh(); }, '本地会话已暂停。'));
  $('#endSession').addEventListener('click', () => void run(async () => { await api('platforms/bilibili/stop', {}); await room.refresh(); }, '本地会话已结束；平台公开直播状态请在官方直播姬确认。'));
  $('#previewStart').addEventListener('click', () => { $('#preview').src = '/output.html?renderer=preview&buffer_ms=4000&rev=room-1'; $('#preview').hidden = false; $('#previewCover').hidden = true; $('#previewStop').hidden = false; });
  function stopPreview() { $('#preview').src = 'about:blank'; $('#preview').hidden = true; $('#previewCover').hidden = false; $('#previewStop').hidden = true; }
  $('#previewStop').addEventListener('click', stopPreview);
  $('#noteForm').addEventListener('submit', e => { e.preventDefault(); void run(async () => { await room.post('messages', { action: 'create', text: $('#noteText').value, nickname: $('#noteName').value, feature: $('#noteFeature').checked }); $('#noteText').value = ''; }, '留言已保存。'); });
  for (const [id, action] of [['nextMessage', 'next'], ['unfeature', 'unfeature'], ['unpin', 'unpin'], ['clearTests', 'clear_tests']]) $('#' + id).addEventListener('click', () => void run(() => room.post('messages', { action })));
  $('#moderationForm').addEventListener('input', () => { $('#moderationForm').dataset.dirty = '1'; });
  $('#moderationForm').addEventListener('submit', e => { e.preventDefault(); const split = id => $('#' + id).value.split('\n').map(s => s.trim()).filter(Boolean); void run(async () => { await room.configure({ moderation: { blocked_words: split('blockedWords'), blocked_names: split('blockedNames') } }); delete $('#moderationForm').dataset.dirty; }, '过滤规则已保存。'); });
  $$('[data-test]').forEach(b => b.addEventListener('click', () => void run(() => room.post('test-event', { type: b.dataset.test }), '已发送带“本地测试”标记的测试事件。')));
  $('#refreshInbox').addEventListener('click', () => void run(() => room.refresh()));
  $('#agentForm').addEventListener('submit', e => { e.preventDefault(); void run(async () => { await room.post('agent', { action: 'ask', text: $('#agentText').value }); $('#agentText').value = ''; await loadAgent(); }); });
  $('#cancelAgent').addEventListener('click', () => void run(() => room.post('agent', { action: 'cancel' })));
  $('#newAgent').addEventListener('click', () => void run(async () => { await room.post('agent', { action: 'new' }); await loadAgent(); }, '已开启新的后台对话。历史数据按本地保留策略保存。'));
  $('#musicUpload').addEventListener('change', e => {
    const file = e.target.files[0]; if (!file) return; if (file.size > 128 * 1024 * 1024) { feedback('单个音乐文件不能超过 128 MB。', true); return; }
    const xhr = new XMLHttpRequest(); xhr.open('POST', '/api/dsh/room/tracks/upload?name=' + encodeURIComponent(file.name)); xhr.setRequestHeader('Content-Type', 'application/octet-stream'); xhr.timeout = 300000;
    $('#uploadProgress').hidden = false; e.target.disabled = true; xhr.upload.onprogress = event => { if (event.lengthComputable) $('#uploadProgress').value = event.loaded / event.total * 100; };
    const done = () => { $('#uploadProgress').hidden = true; e.target.disabled = false; e.target.value = ''; };
    xhr.onload = () => { done(); if (xhr.status >= 200 && xhr.status < 300) { feedback('音乐已校验并加入歌单。'); void room.refresh(); } else { let error; try { error = JSON.parse(xhr.responseText).error; } catch { error = 'UPLOAD_FAILED'; } feedback('上传失败：' + error, true); } };
    xhr.onerror = xhr.ontimeout = () => { done(); feedback('上传中断，请检查连接并重试。', true); }; xhr.send(file);
  });
  $('#exportConfig').addEventListener('click', () => void run(async () => { const v = await api('room/export'), url = URL.createObjectURL(new Blob([JSON.stringify(v, null, 2)], { type: 'application/json' })), a = document.createElement('a'); a.href = url; a.download = 'zhixia-room-settings.json'; a.click(); setTimeout(() => URL.revokeObjectURL(url), 1000); }));
  $('#importConfig').addEventListener('change', e => { const file = e.target.files[0]; if (!file) return; void run(async () => { if (file.size > 128 * 1024) throw Error('ROOM_CONFIG_FILE_TOO_LARGE'); const data = JSON.parse(await file.text()); await room.post('import', { ...data, expected_revision: state.revision }); }, '房间设置已导入。'); e.target.value = ''; });
  $('#resetConfig').addEventListener('click', () => { if (confirm('恢复默认画面、混音和过滤设置？音乐文件及消息不会删除。')) void run(() => room.post('reset', { expected_revision: state.revision }), '已恢复默认装修。'); });
  async function loadLogs() { await refreshRuntime(); return run(async () => { const v = await api('room/audit'); $('#auditLog').replaceChildren(...v.audit.map(row => { const el = node('div', 'audit-row'); el.append(node('time', '', new Date(row.at).toLocaleString('zh-CN', { hour12: false }))); const detail = node('div', '', row.action); detail.append(node('code', '', JSON.stringify(row.detail))); el.append(detail); return el; })); }); }
  function renderRuntime() {
    const voice = studio?.voice, gpuName = studio?.gpu?.name?.replace(/^NVIDIA\s+(GeForce\s+)?/, '') || '推理设备';
    $('#avatarState').textContent = gpuName + '　' + (studio?.avatar_ready ? '人物在线' : '等待服务'); $('#receiverState').textContent = '正式播放端　' + (platforms?.output_player?.connected ? '在线' : '等待接收'); $('#voiceState').textContent = (voice?.voice_id || 'O07') + ' / ' + (voice?.engine || 'OmniVoice');
    $('#runtimeTopology').textContent = gpuName + ' 生成 · 官方直播姬输出 · O07 主音色 / F07 备用';
    if (!state) return;
    const rows = [['角色', '女A / 林知夏'], ['人物生成', studio?.avatar_ready ? gpuName + ' · Ready' : '未就绪'], ['当前语音', (voice?.voice_id || '—') + ' / ' + (voice?.engine || '—')], ['备用语音 F07', voice?.workers?.F07?.ready ? 'Ready' : '未就绪'], ['正式接收端', platforms?.output_player?.receiver_id || '未连接'], ['音频上下文', platforms?.output_player?.audio_state || '未连接'], ['画面尺寸', platforms?.output_player ? platforms.output_player.width + ' × ' + platforms.output_player.height : '—'], ['后台事件连接', room.connected ? 'SSE 在线' : '重连 / 定期校验'], ['DSH 人格 / 渠道', dsh?.health?.persona_injection_ready ? 'Ready' : '待检查'], ['记忆服务', dsh?.health?.memory_ready ? 'Ready' : '待检查'], ['回复队列', dsh?.queued?.length ?? '—'], ['混音设置版本', state.player?.config_revision ?? '尚无回报'], ['存储状态', state.storage_error || '正常']];
    $('#runtimeDetails').replaceChildren(...rows.map(([label, value]) => { const el = node('div', 'runtime-row'); el.append(node('span', '', label), node('span', '', value)); return el; }));
  }
  async function refreshRuntime() {
    const results = await Promise.allSettled([fetch('/api/studio/status', { signal: AbortSignal.timeout(8000) }).then(r => r.json()), api('platforms/status'), api('status')]);
    if (closed) return; if (results[0].status === 'fulfilled') studio = results[0].value; if (results[1].status === 'fulfilled') platforms = results[1].value; if (results[2].status === 'fulfilled') dsh = results[2].value; renderRuntime();
  }
  $('#refreshLogs').addEventListener('click', () => void loadLogs());
  const transportTimer = setInterval(() => { void refreshRuntime(); }, 6000);
  const progressTimer = setInterval(() => {
    if (!state || closed) return; const track = state.tracks.find(t => t.id === state.music.track_id); if (!track) return;
    let position = state.music.position + (state.music.playing ? Math.max(0, (room.now() - state.server_time) / 1000) : 0); if (state.music.repeat === 'one') position %= track.duration; position = Math.min(track.duration, position);
    if ($('#musicSeek') !== document.activeElement) { $('#musicSeek').max = track.duration; $('#musicSeek').value = position; } $('#seekTime').textContent = duration(position) + ' / ' + duration(track.duration);
  }, 500);
  room.addEventListener('change', render); room.addEventListener('connection', render); room.start().then(render).catch(e => feedback(friendly(e), true)); void refreshRuntime();
  addEventListener('beforeunload', () => { closed = true; clearInterval(transportTimer); clearInterval(progressTimer); clearTimeout(feedback.timer); $('#audition').pause(); stopPreview(); room.close(); });
})();
