function connectionMessage(state, reason) {
  const normalized = String(state || '').toLowerCase();
  if (normalized === 'connected') return '阿里云 RTC 信令连接已建立';
  if (normalized === 'reconnecting') return '阿里云 RTC 连接中断，正在重连';
  if (normalized === 'disconnected') return `阿里云 RTC 已断开${reason ? `：${reason}` : ''}`;
  return `RTC 连接状态：${state || '未知'}`;
}

function defaultTurnId() {
  if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID();
  return `rtc-turn-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function mergeTranscriptText(previous, next) {
  const prior = String(previous || '').trim();
  const incoming = String(next || '').trim();
  if (!prior) return incoming;
  if (!incoming || prior.endsWith(incoming)) return prior;
  if (incoming.startsWith(prior)) return incoming;
  return `${prior}${incoming}`;
}

export function findLatestInterviewQuestion(messages = []) {
  for (let index = messages.length - 1; index >= 0; index -= 1) {
    const message = messages[index];
    if (
      message?.sender_type === 'agent'
      && ['question', 'follow_up'].includes(message?.message_type)
      && String(message?.content || '').trim()
    ) {
      return message;
    }
  }
  return null;
}

export function extractQuestionFromAgentTranscript(value) {
  const text = String(value || '').replace(/\s+/g, ' ').trim();
  if (!text) return '';
  const questionEnd = Math.max(text.lastIndexOf('？'), text.lastIndexOf('?'));
  if (questionEnd < 0) return text;
  const beforeQuestion = text.slice(0, questionEnd);
  const previousBoundary = Math.max(
    beforeQuestion.lastIndexOf('。'),
    beforeQuestion.lastIndexOf('！'),
    beforeQuestion.lastIndexOf('!'),
    beforeQuestion.lastIndexOf('？'),
    beforeQuestion.lastIndexOf('?')
  );
  return text.slice(previousBoundary + 1, questionEnd + 1).trim() || text;
}

function comparableQuestion(value) {
  return extractQuestionFromAgentTranscript(value)
    .toLowerCase()
    .replace(/[\s。，！？；：“”‘’,.!?;:'"`~、-]/g, '');
}

export function shouldPersistAliyunAgentTurn(turn, latestQuestion, nextAction = 'ask_follow_up') {
  if (nextAction !== 'ask_follow_up' || turn?.speaker !== 'agent' || !turn?.end) return false;
  const spokenQuestion = extractQuestionFromAgentTranscript(turn.text);
  if (!spokenQuestion) return false;
  return comparableQuestion(spokenQuestion) !== comparableQuestion(latestQuestion?.content);
}

export function createAliyunRtcTranscriptAssembler({ createTurnId = defaultTurnId } = {}) {
  const turns = new Map();

  return {
    consume(message) {
      if (message?.reasoning) return null;
      const speaker = message?.userType === 'user' ? 'candidate' : 'agent';
      const text = String(message?.message || '').trim();
      const buffered = turns.get(speaker);

      // dingrtc-aiagent may send the final sentence boundary as an empty
      // transcription with end=true. Do not discard that marker: it is what
      // turns the buffered candidate transcript into a persistable answer.
      if (!text) {
        if (!message?.end || !buffered?.text) return null;
        turns.delete(speaker);
        return {
          speaker,
          turnId: buffered.turnId,
          text: buffered.text,
          end: true,
        };
      }

      const current = buffered || { turnId: createTurnId(), text: '' };
      current.text = mergeTranscriptText(current.text, text);
      const result = {
        speaker,
        turnId: current.turnId,
        text: current.text,
        end: Boolean(message?.end),
      };
      if (result.end) turns.delete(speaker);
      else turns.set(speaker, current);
      return result;
    },
    finalize(speaker = 'candidate') {
      const current = turns.get(speaker);
      if (!current?.text) return null;
      turns.delete(speaker);
      return {
        speaker,
        turnId: current.turnId,
        text: current.text,
        end: true,
      };
    },
    reset() {
      turns.clear();
    },
  };
}

async function loadSdk() {
  const module = await import('dingrtc');
  return module.default || module;
}

async function loadAiAgentSdk() {
  const module = await import('dingrtc-aiagent');
  return module.default || module;
}

const wait = (milliseconds) => new Promise((resolve) => setTimeout(resolve, milliseconds));

// A spoken notification does not replace the cloud model's role/history.
// Confirm the old session has stopped before preparing and starting a new role.
export async function handoffAliyunRtcSession({ stop, prepare, start, isCancelled }) {
  const stopped = await stop();
  if (isCancelled()) return;
  if (stopped?.status !== 'stopped') {
    throw new Error('上一位语音面试官尚未退出，请稍后重新连接；已保存的回答会保留。');
  }
  await prepare();
  if (isCancelled()) return;
  await start();
}

export async function ensureAiAgentMessagingReady(aiAgentClient, {
  timeoutMs = 2000,
  pollIntervalMs = 50,
} = {}) {
  // isInSession/initAgent are currently runtime fields of Alibaba's official
  // dingrtc-aiagent package, although its .d.ts marks them private. The 1.0.10
  // plugin can occasionally miss the channel's connected transition; audio
  // still works in that state, but no message/agent-status events are emitted.
  if (!aiAgentClient || !Object.prototype.hasOwnProperty.call(aiAgentClient, 'isInSession')) {
    return true;
  }
  const deadline = Date.now() + Math.max(0, timeoutMs);
  while (!aiAgentClient.isInSession && Date.now() < deadline) {
    await wait(Math.max(10, pollIntervalMs));
  }
  if (!aiAgentClient.isInSession && typeof aiAgentClient.initAgent === 'function') {
    await aiAgentClient.initAgent();
  }
  return Boolean(aiAgentClient.isInSession);
}

function isRtcNetworkError(error) {
  return Number(error?.code) === 40001 || /network error|networkerror/i.test(String(error?.message || ''));
}

export async function createAliyunRtcAudioSession(options) {
  for (let attempt = 1; attempt <= 2; attempt += 1) {
    try {
      const session = await createAliyunRtcAudioSessionOnce(options);
      if (options.isCancelled?.()) {
        await session.leave();
        throw new Error('语音连接已取消');
      }
      return session;
    } catch (error) {
      if (attempt === 2 || options.isCancelled?.() || error.rtcStage !== 'join' || !isRtcNetworkError(error)) {
        throw error;
      }
      options.onStartupStage?.('join_retry');
      await wait(600);
      if (options.isCancelled?.()) throw error;
    }
  }
}

async function createAliyunRtcAudioSessionOnce({
  credentials,
  onConnectionState,
  onRemoteAudio,
  onRemoteUserCount,
  onAgentStatus,
  onAgentMessage,
  onAgentMessagingReady,
  onStartupStage,
  sdk,
  aiAgentSdk,
}) {
  const DingRTC = sdk || await loadSdk();
  if (!DingRTC.checkSystemRequirements()) {
    throw new Error('当前浏览器不支持阿里云 RTC，请使用最新版 Chrome 或 Edge。');
  }

  const client = DingRTC.createClient();
  const remoteTracks = new Set();
  let mcuAudioSubscription = null;
  let microphoneTrack = null;
  let aiAgentClient = null;
  let joined = false;
  let closed = false;
  let stage = 'plugin';
  const setStage = (next) => {
    stage = next;
    onStartupStage?.(next);
  };

  const updateRemoteUserCount = () => {
    onRemoteUserCount?.(client.remoteUsers?.length || 0);
  };

  const handleConnectionState = (currentState, _previousState, reason) => {
    onConnectionState?.({
      state: String(currentState || '').toLowerCase(),
      message: connectionMessage(currentState, reason),
    });
  };

  const handleRemoteUserChange = () => updateRemoteUserCount();

  const handleAgentStatus = (status) => onAgentStatus?.(status);

  const handleAgentMessage = (message) => onAgentMessage?.(message);

  const handleUserPublished = async (user, mediaType, auxiliary) => {
    if (closed || mediaType !== 'audio') return;
    try {
      // DingRTC Web receives remote audio through the channel's mixed MCU
      // stream. Subscribing by a participant user ID is rejected with
      // "only support subscribe mcu audio".
      if (!mcuAudioSubscription) {
        mcuAudioSubscription = client.subscribe('mcu', mediaType, auxiliary);
      }
      const track = await mcuAudioSubscription;
      if (closed) {
        track.stopPlay?.();
        return;
      }
      if (!remoteTracks.has(track)) {
        remoteTracks.add(track);
        track.play();
      }
      onRemoteAudio?.(user);
    } catch (error) {
      mcuAudioSubscription = null;
      if (!closed) {
        onConnectionState?.({
          state: 'warning',
          message: `远端音频订阅失败：${error.message || '未知错误'}`,
        });
      }
    }
  };

  client.on('connection-state-change', handleConnectionState);
  client.on('user-joined', handleRemoteUserChange);
  client.on('user-left', handleRemoteUserChange);
  client.on('user-published', handleUserPublished);

  const leave = async () => {
    if (closed) return;
    closed = true;

    client.off('connection-state-change', handleConnectionState);
    client.off('user-joined', handleRemoteUserChange);
    client.off('user-left', handleRemoteUserChange);
    client.off('user-published', handleUserPublished);

    if (aiAgentClient) {
      aiAgentClient.off('agent-status', handleAgentStatus);
      aiAgentClient.off('message', handleAgentMessage);
      try { aiAgentClient.detach?.(); } catch { /* Continue releasing RTC resources. */ }
    }

    if (microphoneTrack) {
      if (joined) {
        try {
          await client.unpublish(microphoneTrack);
        } catch {
          // The signaling connection may already be gone; still release the device.
        }
      }
      try { microphoneTrack.close(); } catch { /* Still leave the channel. */ }
      microphoneTrack = null;
    }

    remoteTracks.forEach((track) => {
      try { track.stopPlay?.(); } catch { /* Release the remaining tracks. */ }
    });
    remoteTracks.clear();
    mcuAudioSubscription = null;
    // join() can fail after opening signaling resources. The SDK's leave()
    // also resets a partially connected client; do not gate it on success.
    try { await client.leave(); } catch { /* Preserve the original startup error. */ }
    joined = false;
  };

  try {
    if (credentials.ai_agent?.enabled) {
      const AiAgentClient = aiAgentSdk || await loadAiAgentSdk();
      aiAgentClient = new AiAgentClient(credentials.ai_agent.user_id);
      aiAgentClient.on('agent-status', handleAgentStatus);
      aiAgentClient.on('message', handleAgentMessage);
      client.register(aiAgentClient);
    }

    setStage('join');
    const joinResult = await client.join({
      appId: credentials.app_id,
      token: credentials.token,
      uid: credentials.user_id,
      channel: credentials.channel_id,
      userName: credentials.user_name || '候选人',
    });
    joined = true;
    onRemoteUserCount?.(joinResult.remoteUsers?.length || 0);

    if (aiAgentClient) {
      setStage('messaging');
      const messagingReady = await ensureAiAgentMessagingReady(aiAgentClient);
      onAgentMessagingReady?.(messagingReady);
      if (!messagingReady) {
        throw new Error('阿里云 RTC 字幕通道初始化失败，请重新接通后再开始回答。');
      }
    }

    // Subscribe to users that published audio before the candidate joined.
    await Promise.all(
      (joinResult.remoteUsers || [])
        .filter((user) => user.hasAudio)
        .map((user) => handleUserPublished(user, 'audio', false))
    );

    setStage('microphone');
    microphoneTrack = await DingRTC.createMicrophoneAudioTrack();
    setStage('publish');
    await client.publish(microphoneTrack);
  } catch (error) {
    await leave();
    const failure = new Error(String(error?.message || error || 'RTC 启动失败'), { cause: error });
    failure.name = error?.name || 'Error';
    failure.code = error?.code;
    failure.rtcStage = stage;
    throw failure;
  }

  return { client, microphoneTrack, aiAgentClient, leave };
}

export function formatAliyunRtcStartError(error) {
  const message = String(error?.message || error || '');
  if (isRtcNetworkError(error)) {
    return '暂时无法连接阿里云语音服务，请检查网络或代理后点击“开始回答”重试；也可以切换文字继续面试，已保存的进度会保留。';
  }
  if (/remote task missing|CLIENT_ERROR_TASK_NOT_FOUND|task does not exist/i.test(message)) {
    return '语音连接未建立，请点击“开始回答”重新连接，已保存的面试进度会保留。';
  }
  if (/启动确认超时|timeout|timed out/i.test(message)) {
    return '语音连接超时，请稍后点击“开始回答”重试。';
  }
  return message || '阿里云 RTC 连接失败，请稍后重试。';
}
