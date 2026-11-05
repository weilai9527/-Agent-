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

export function matchesAliyunRtcQuestion(turn, question) {
  if (turn?.speaker !== 'agent' || !turn.end || !question?.id) return false;
  const normalize = (value) => String(value || '').normalize('NFKC')
    .toLowerCase().replace(/[\s\p{P}]+/gu, '');
  const expected = normalize(question.content);
  return Boolean(expected && normalize(turn.text) === expected);
}

export function createAliyunRtcTranscriptAssembler({ createTurnId = defaultTurnId } = {}) {
  const turns = new Map();

  return {
    consume(message) {
      if (message?.reasoning || !['user', 'agent'].includes(message?.userType)) return null;
      const speaker = message?.userType === 'user' ? 'candidate' : 'agent';
      const text = String(message?.message || '').trim();
      const buffered = turns.get(speaker);

      // dingrtc-aiagent 可能用空字幕并设置 end=true 来表示
      // 最终句子边界。不能丢弃该标记，因为它用于
      // 把缓冲中的候选人转写内容提交为可保存的回答。
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

      // 用户字幕是当前句子的识别结果，SDK 已在回调前累积智能体片段。
      // 用最新文本更新当前句，保留本轮 ID 以绑定保存顺序。
      const current = { turnId: buffered ? buffered.turnId : createTurnId(), text };
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

// 供应商可能先结束候选人字幕，而更早的面试官字幕仍在传输；
// 应在题目开始时绑定归属，并按真实对话顺序
// 提交业务轮次，不依赖哪一方的结束标记先到。
export function createRtcCaptionStream(candidate, agent, captureQuestion) {
  const assembler = createAliyunRtcTranscriptAssembler();
  const questionByTurn = new Map();
  let lastCandidateId = null;
  let agentOwner = null;
  let speakingAgent = false;
  let deferred = [];

  function emitCandidate(turn) {
    if (!turn) return;
    if (captureQuestion) {
      turn = { ...turn, question: questionByTurn.get(turn.turnId) ?? null };
      questionByTurn.delete(turn.turnId);
    }
    if (speakingAgent && turn.turnId !== agentOwner) deferred.push(turn);
    else candidate(turn);
  }

  function finishAgent(turn) {
    if (!turn) return;
    if (lastCandidateId === agentOwner) emitCandidate(assembler.finalize('candidate'));
    agent(turn, agentOwner);
    speakingAgent = false;
    deferred.forEach(candidate);
    deferred = [];
  }

  return {
    consume(message) {
      const turn = assembler.consume(message);
      if (!turn) return null;
      if (turn.speaker === 'candidate') {
        // 同一句的后续字幕只更新文字，始终保留开始作答时对应的题目。
        if (captureQuestion && !questionByTurn.has(turn.turnId)) {
          questionByTurn.set(turn.turnId, captureQuestion());
        }
        lastCandidateId = turn.turnId;
        if (turn.end) emitCandidate(turn);
      } else {
        if (!speakingAgent) {
          speakingAgent = true;
          agentOwner = lastCandidateId;
        }
        if (turn.end) finishAgent(turn);
      }
      return turn;
    },
    flush() {
      finishAgent(assembler.finalize('agent'));
      emitCandidate(assembler.finalize('candidate'));
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

// 播放语音通知不会替换云端模型的角色或历史对话。
// 准备并启动新角色之前，先确认旧会话已经停止。
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
  // isInSession 和 initAgent 是阿里云官方 dingrtc-aiagent 的运行时字段，
  // 但类型声明将它们标为私有。1.0.10 版本插件偶尔会漏掉
  // 频道连接成功的状态变化；这时音频仍可使用，
  // 但不会发出字幕消息或面试官状态事件。
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
  return Number(error?.code) === 40001
    || /network error|networkerror|failed to fetch|fetch failed|network request failed/i.test(String(error?.message || ''));
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
  let remoteMuted = false;
  const setRemoteMuted = (muted) => {
    remoteMuted = muted;
    remoteTracks.forEach((track) => track.setVolume?.(muted ? 0 : 1));
  };
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
      // DingRTC 网页端通过频道的混合音频流接收远端声音；
      // 按参与者用户标识订阅会被拒绝，错误信息为
      // “only support subscribe mcu audio”，即仅支持订阅混合音频。
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
        if (remoteMuted) track.setVolume?.(0);
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
      try { aiAgentClient.detach?.(); } catch { /* 继续释放实时音视频资源。 */ }
    }

    if (microphoneTrack) {
      if (joined) {
        try {
          await client.unpublish(microphoneTrack);
        } catch {
          // 信令连接可能已断开，但仍需释放设备。
        }
      }
      try { microphoneTrack.close(); } catch { /* 仍然执行退出频道。 */ }
      microphoneTrack = null;
    }

    remoteTracks.forEach((track) => {
      try { track.stopPlay?.(); } catch { /* 释放剩余的音轨。 */ }
    });
    remoteTracks.clear();
    mcuAudioSubscription = null;
    // join() 可能在创建信令资源后失败；开发包的 leave()
    // 也会清理尚未完全连接的客户端，因此不能仅在连接成功后调用。
    try { await client.leave(); } catch { /* 保留最初的启动错误。 */ }
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

    // 订阅候选人加入频道之前已经发布的远端音频。
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

  return { client, microphoneTrack, aiAgentClient, setRemoteMuted, leave };
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
