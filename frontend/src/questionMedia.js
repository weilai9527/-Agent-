function questionPath(interviewId, questionId) {
  return `/api/interviews/${encodeURIComponent(interviewId)}/media/questions/${encodeURIComponent(questionId)}`;
}

function post(request, path) {
  return request(path, { method: 'POST', keepalive: path.endsWith('/recording/stop'),
    signal: AbortSignal.timeout(20000) });
}

export function clipMessage(error, playback = false) {
  if (error.status === 401) return '登录已过期，请重新登录。';
  if (error.status === 403) return '当前账户没有这项媒体权限。';
  if (error.status === 404) return playback ? '本题没有可查看的录像。' : '未找到这场面试或本题的录制。';
  if (error.status === 409) return playback ? '片段暂未就绪，请稍后再试。' : '题目或录制状态已变化，请刷新当前题。';
  if (error.status === 429) return '学校媒体额度已用尽，可继续文字面试。';
  if (error.status >= 500) return '媒体服务暂时不可用，可继续文字面试。';
  if (error.name === 'NotAllowedError') return '摄像头权限未开启，可继续文字面试。';
  if (error.name === 'TimeoutError') return '媒体请求超时，请稍后重试。';
  return error.message || '媒体操作未完成。';
}

export async function fetchQuestionClip(request, interviewId, questionId) {
  const reply = await post(request, questionPath(interviewId, questionId) + '/playback');
  let url;
  try { url = new URL(reply?.url); } catch { throw new Error('回放授权无效，请重新获取。'); }
  if (url.protocol !== 'https:' || url.username || url.password || url.hash
      || reply.question_id !== questionId || !reply.recording_id
      || !Number.isInteger(reply.expires_at) || reply.expires_at * 1000 <= Date.now()) {
    throw new Error('回放授权无效或已过期，请重新获取。');
  }
  return { url: url.href, expiresAt: reply.expires_at * 1000 };
}

// 回执丢失或标签页重新加载时，只保留需要停录的题号。授权令牌和播放地址不落盘。
const pendingStops = new Map();
const stopKey = id => 'interview.video.pending-stop.' + id;
function pendingQuestion(id) {
  try { return pendingStops.get(id) || globalThis.sessionStorage?.getItem(stopKey(id)); }
  catch { return pendingStops.get(id); }
}
function markPending(id, question) {
  pendingStops.set(id, question);
  try { globalThis.sessionStorage?.setItem(stopKey(id), question); } catch { /* 隐私模式下仅保留内存标记。 */ }
}
function clearPending(id, question) {
  if (pendingQuestion(id) !== question) return;
  pendingStops.delete(id);
  try { globalThis.sessionStorage?.removeItem(stopKey(id)); } catch { /* 隐私模式下无持久标记。 */ }
}
function checkReceipt(reply, questionId, states) {
  if (reply?.question_id !== questionId || !reply.recording_id || !states.includes(reply.state)) {
    throw new Error('录制服务未确认本题状态。');
  }
  return reply.state;
}
async function confirmStopQuestion(request, interviewId, questionId) {
  if (!questionId || pendingQuestion(interviewId) !== questionId) return;
  try {
    const reply = await post(request, questionPath(interviewId, questionId) + '/recording/stop');
    const state = checkReceipt(reply, questionId, ['processing', 'ready']);
    clearPending(interviewId, questionId);
    return state;
  } catch (error) {
    throw new Error('上次云录制的停录状态尚未确认，可继续文字作答。' + clipMessage(error));
  }
}

export function confirmPendingVideo(request, interviewId) {
  return confirmStopQuestion(request, interviewId, pendingQuestion(interviewId));
}

const loadSdk = async () => (await import('dingrtc')).default;

// 每个实例只处理一次开始操作，并固定绑定发起时的面试和题号。重试停录不会误停下一题。
export function questionRecorder({ request, interviewId, questionId, preview, onState, getSdk = loadSdk }) {
  const path = questionPath(interviewId, questionId);
  let client;
  let camera;
  let timer;
  let cancelled = false;
  let startReceipt;
  let stopping;
  let needsStop = false;
  let started = false;
  let reason = '';

  function lostConnection(state) {
    if (state === 'disconnected' && !cancelled) interrupt('视频连接已断开。');
  }
  function interrupt(message) {
    reason = message;
    stop().catch(() => {});
  }
  function cameraEnded() {
    interrupt('摄像头已断开。');
  }
  function releaseCamera() {
    if (camera) {
      const track = camera;
      camera = null;
      track.off('track-ended', cameraEnded);
      try { track.close(); } catch { track.getMediaStreamTrack()?.stop(); }
    }
  }
  async function leaveChannel() {
    releaseCamera();
    if (client) {
      const leaving = client;
      client = null;
      leaving.off('connection-state-change', lostConnection);
      await leaving.leave();
    }
  }
  async function start() {
    if (started || cancelled) return;
    started = true;
    onState('opening', '正在获取视频权限…');
    try {
      await confirmPendingVideo(request, interviewId);
      if (cancelled) return;
      const grant = await post(request, `/api/interviews/${encodeURIComponent(interviewId)}/media/video/token`);
      if (cancelled) return;
      const remaining = grant.expires_at * 1000 - Date.now();
      if (!grant.token || !grant.app_id || !grant.channel_id || !grant.user_id
          || !Number.isInteger(grant.expires_at) || remaining <= 0) {
        throw new Error('视频授权无效或已过期，请重试。');
      }
      // 仅在学生点击录制后申请摄像头；到期先关闭设备，续录需要新的授权。
      timer = setTimeout(() => interrupt('视频授权已到期。'), remaining);
      const sdk = await getSdk();
      if (cancelled) return;
      if (!sdk.checkSystemRequirements()) throw new Error('浏览器不支持发布视频，可继续文字面试。');
      const joining = sdk.createClient();
      client = joining;
      joining.on('connection-state-change', lostConnection);
      await joining.join({ appId: grant.app_id, channel: grant.channel_id, uid: grant.user_id, token: grant.token });
      if (cancelled) { await joining.leave(); return; }
      const track = await sdk.createCameraVideoTrack({ frameRate: 15, dimension: 'VD_640x480' });
      if (cancelled) { track.close(); return; }
      camera = track;
      camera.on('track-ended', cameraEnded);
      await joining.publish(camera);
      if (cancelled) return;
      camera.play(preview);
      onState('opening', '视频已发布，正在确认本题云录制…');
      // 若服务已受理但回执丢失，清理时仍要对同一题发 stop。
      markPending(interviewId, questionId);
      needsStop = true;
      startReceipt = post(request, path + '/recording/start').catch(error => {
        if ([400, 401, 403, 404, 409, 429].includes(error.status) || error.data?.code === 'media_provider_disabled') {
          needsStop = false;
          clearPending(interviewId, questionId);
        }
        throw error;
      });
      const state = checkReceipt(await startReceipt, questionId, ['recording', 'processing', 'ready']);
      if (cancelled) return;
      if (state === 'recording') {
        onState('recording', '本题正在云端录制（仅摄像头画面）。');
      } else {
        needsStop = false;
        clearPending(interviewId, questionId);
        reason = state === 'ready' ? '本题已有可回放的片段。' : '本题片段正在处理。';
        await stop();
      }
    } catch (error) {
      if (!cancelled) {
        reason = clipMessage(error);
        await stop();
      }
    }
  }

  function stop() {
    if (stopping) return stopping;
    cancelled = true;
    clearTimeout(timer);
    // 先释放本地轨道，即使供应商不可用也不会继续采集新画面。
    const leaving = leaveChannel().catch(() => {});
    stopping = (async () => {
      if (needsStop) {
        onState('stopping', '摄像头已关闭，正在核实云端停录…');
        await startReceipt.catch(() => {});
        try {
          const state = await confirmStopQuestion(request, interviewId, questionId);
          if (state) reason = [reason, state === 'ready' ? '本题录像可回放。' : '本题录像正在处理。'].filter(Boolean).join(' ');
        } catch (error) {
          onState('unconfirmed', '摄像头已关闭。' + error.message);
          throw error;
        }
        needsStop = false;
      }
      await leaving;
      onState('idle', reason || '摄像头已关闭。');
    })().finally(() => { stopping = null; });
    return stopping;
  }
  return { start, stop };
}
