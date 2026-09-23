import assert from 'node:assert/strict';
import test from 'node:test';

import {
  createAliyunRtcAudioSession,
  handoffAliyunRtcSession,
  createAliyunRtcTranscriptAssembler,
  ensureAiAgentMessagingReady,
  extractQuestionFromAgentTranscript,
  formatAliyunRtcStartError,
  findLatestInterviewQuestion,
  shouldPersistAliyunAgentTurn,
} from './aliyunRtc.js';

test('handoff waits for old session to stop and new role to be saved before starting', async () => {
  const order = [];
  await handoffAliyunRtcSession({
    stop: async () => { order.push('stop'); return { status: 'stopped' }; },
    prepare: async () => { order.push('save new role and question'); },
    start: async () => { order.push('start fresh task'); },
    isCancelled: () => false,
  });
  assert.deepEqual(order, ['stop', 'save new role and question', 'start fresh task']);
});

test('handoff never starts another model when stopping or saving the new role fails', async () => {
  for (const status of ['stop_failed', 'stopping', 'stopped']) {
    let started = false;
    await assert.rejects(handoffAliyunRtcSession({
      stop: async () => ({ status }),
      prepare: async () => { throw new Error('save failed'); },
      start: async () => { started = true; },
      isCancelled: () => false,
    }));
    assert.equal(started, false);
  }
});

test('leaving during role preparation cancels automatic reconnect', async () => {
  let cancelled = false;
  let started = false;
  await handoffAliyunRtcSession({
    stop: async () => ({ status: 'stopped' }),
    prepare: async () => { cancelled = true; },
    start: async () => { started = true; },
    isCancelled: () => cancelled,
  });
  assert.equal(started, false);
});

test('startup errors explain how to recover without dumping provider responses', () => {
  const message = formatAliyunRtcStartError(new Error('remote task missing: CLIENT_ERROR_TASK_NOT_FOUND Response: internal details'));
  assert.match(message, /重新连接/);
  assert.doesNotMatch(message, /Response|CLIENT_ERROR|internal/);
  assert.match(formatAliyunRtcStartError(new Error('启动确认超时')), /超时/);
  assert.equal(formatAliyunRtcStartError(new Error('请允许麦克风权限')), '请允许麦克风权限');
  assert.match(formatAliyunRtcStartError(new Error('Network error, please check your network connectivity')), /网络或代理/);
});

function startupHarness(failures, { failAt = 'join', cleanupThrows = false } = {}) {
  const calls = { created: 0, left: 0, closed: 0, published: 0 };
  const sdk = {
    checkSystemRequirements: () => true,
    createClient() {
      const index = calls.created++;
      return {
        on() {}, off() {},
        async join() {
          if (failAt === 'join' && failures[index]) throw failures[index];
          return { remoteUsers: [] };
        },
        async publish() {
          calls.published += 1;
          if (failAt === 'publish' && failures[index]) throw failures[index];
        },
        async unpublish() {},
        leave() {
          calls.left += 1;
          if (cleanupThrows) throw new Error('cleanup failed');
        },
      };
    },
    async createMicrophoneAudioTrack() { return { close() { calls.closed += 1; } }; },
  };
  return { sdk, calls, credentials: {} };
}

test('cleans failed join before retrying on a fresh client', async () => {
  const network = Object.assign(new Error('Network error'), { code: 40001 });
  const harness = startupHarness([network]);
  const stages = [];
  const session = await createAliyunRtcAudioSession({
    ...harness,
    onStartupStage: (stage) => {
      stages.push(stage);
      if (stage === 'join_retry') assert.equal(harness.calls.left, 1);
    },
  });
  assert.equal(harness.calls.created, 2);
  assert.equal(harness.calls.published, 1);
  assert.ok(stages.includes('join_retry'));
  await session.leave();
  assert.equal(harness.calls.left, 2);
  assert.equal(harness.calls.closed, 1);
});

test('network retry is bounded and cleanup errors do not replace the cause', async () => {
  const network = Object.assign(new Error('Network error'), { code: 40001 });
  const harness = startupHarness([network, network], { cleanupThrows: true });
  await assert.rejects(createAliyunRtcAudioSession(harness), (error) => {
    assert.equal(error.rtcStage, 'join');
    assert.equal(error.code, 40001);
    assert.equal(error.cause, network);
    return true;
  });
  assert.equal(harness.calls.created, 2);
  assert.equal(harness.calls.left, 2);
});

test('authentication failures and publish failures are not automatically retried', async () => {
  for (const failAt of ['join', 'publish']) {
    const failure = new Error(failAt === 'join' ? 'token is invalid' : 'Network error');
    const harness = startupHarness([failure], { failAt });
    await assert.rejects(createAliyunRtcAudioSession(harness), (error) => error.rtcStage === failAt);
    assert.equal(harness.calls.created, 1);
    assert.equal(harness.calls.left, 1);
    assert.equal(harness.calls.closed, failAt === 'publish' ? 1 : 0);
  }
});

test('cancelling during retry does not open another connection', async () => {
  const harness = startupHarness([new Error('Network error')]);
  let cancelled = false;
  await assert.rejects(createAliyunRtcAudioSession({
    ...harness,
    isCancelled: () => cancelled,
    onStartupStage: (stage) => { if (stage === 'join_retry') cancelled = true; },
  }), /Network error/);
  assert.equal(harness.calls.created, 1);
  assert.equal(harness.calls.left, 1);
});


test('finds only the latest real interview question', () => {
  assert.deepEqual(
    findLatestInterviewQuestion([
      { id: 'q1', sender_type: 'agent', message_type: 'question', content: '第一题' },
      { id: 'a1', sender_type: 'candidate', message_type: 'answer', content: '第一题回答' },
      { id: 'q2', sender_type: 'agent', message_type: 'follow_up', content: '当前追问' },
      { id: 's1', sender_type: 'agent', message_type: 'system', content: '面试官切换提示' },
    ]),
    { id: 'q2', sender_type: 'agent', message_type: 'follow_up', content: '当前追问' }
  );
  assert.equal(findLatestInterviewQuestion([]), null);
});


test('extracts the actual question from an RTC agent spoken turn', () => {
  assert.equal(
    extractQuestionFromAgentTranscript('好的，这个经历很有代表性。那么你当时如何协调现场节奏？'),
    '那么你当时如何协调现场节奏？'
  );
  assert.equal(extractQuestionFromAgentTranscript('请介绍你的项目'), '请介绍你的项目');
});


test('persists only a new autonomous RTC follow-up', () => {
  const latestQuestion = { content: '你当时如何协调现场节奏？' };
  assert.equal(
    shouldPersistAliyunAgentTurn(
      { speaker: 'agent', end: true, text: '你当时如何协调现场节奏?' },
      latestQuestion
    ),
    false
  );
  assert.equal(
    shouldPersistAliyunAgentTurn(
      { speaker: 'agent', end: true, text: '好的。这次经历最后的结果如何？' },
      latestQuestion
    ),
    true
  );
  assert.equal(
    shouldPersistAliyunAgentTurn(
      { speaker: 'agent', end: true, text: '这次经历最后的结果如何？' },
      latestQuestion,
      'switch_agent'
    ),
    false
  );
});


test('assembles partial captions into one stable final RTC turn', () => {
  let nextId = 0;
  const assembler = createAliyunRtcTranscriptAssembler({ createTurnId: () => `turn_${++nextId}` });

  assert.deepEqual(
    assembler.consume({ message: '我负责', userType: 'user', end: false }),
    { speaker: 'candidate', turnId: 'turn_1', text: '我负责', end: false }
  );
  assert.deepEqual(
    assembler.consume({ message: '我负责核心模块', userType: 'user', end: true }),
    { speaker: 'candidate', turnId: 'turn_1', text: '我负责核心模块', end: true }
  );
  assert.equal(assembler.consume({ message: '内部思考', userType: 'agent', reasoning: true, end: true }), null);
  assert.deepEqual(
    assembler.consume({ message: '请继续介绍', userType: 'agent', end: true }),
    { speaker: 'agent', turnId: 'turn_2', text: '请继续介绍', end: true }
  );
});


test('uses an empty end marker to finalize the buffered candidate transcript', () => {
  const assembler = createAliyunRtcTranscriptAssembler({ createTurnId: () => 'turn_empty_end' });

  assert.deepEqual(
    assembler.consume({ message: '我负责核心模块', userType: 'user', end: false }),
    { speaker: 'candidate', turnId: 'turn_empty_end', text: '我负责核心模块', end: false }
  );
  assert.deepEqual(
    assembler.consume({ message: '', userType: 'user', end: true }),
    { speaker: 'candidate', turnId: 'turn_empty_end', text: '我负责核心模块', end: true }
  );
});


test('can flush a buffered candidate transcript before leaving the RTC channel', () => {
  const assembler = createAliyunRtcTranscriptAssembler({ createTurnId: () => 'turn_flush' });

  assembler.consume({ message: '这是挂断前的最后一句', userType: 'user', end: false });
  assert.deepEqual(
    assembler.finalize('candidate'),
    { speaker: 'candidate', turnId: 'turn_flush', text: '这是挂断前的最后一句', end: true }
  );
  assert.equal(assembler.finalize('candidate'), null);
});


test('repairs a missed AI Agent messaging-session initialization', async () => {
  const client = {
    isInSession: false,
    initCalls: 0,
    async initAgent() {
      this.initCalls += 1;
      this.isInSession = true;
    },
  };

  assert.equal(
    await ensureAiAgentMessagingReady(client, { timeoutMs: 0 }),
    true
  );
  assert.equal(client.initCalls, 1);
});


test('joins, publishes microphone, subscribes remote audio, and releases resources', async () => {
  const events = new Map();
  const remoteTrack = {
    played: false,
    stopped: false,
    play() { this.played = true; },
    stopPlay() { this.stopped = true; },
  };
  const microphoneTrack = {
    closed: false,
    close() { this.closed = true; },
  };
  const remoteUser = { userId: 'agent_1', userName: '技术面试官', hasAudio: true };
  const calls = { join: null, published: null, unpublished: null, left: false };
  const client = {
    remoteUsers: [remoteUser],
    on(name, handler) { events.set(name, handler); },
    off(name) { events.delete(name); },
    async join(joinInfo) {
      calls.join = joinInfo;
      return { remoteUsers: [remoteUser], timeLeft: 600 };
    },
    async subscribe(userId, mediaType) {
      assert.equal(userId, 'mcu');
      assert.equal(mediaType, 'audio');
      return remoteTrack;
    },
    async publish(track) { calls.published = track; },
    async unpublish(track) { calls.unpublished = track; },
    leave() { calls.left = true; },
  };
  const sdk = {
    checkSystemRequirements: () => true,
    createClient: () => client,
    createMicrophoneAudioTrack: async () => microphoneTrack,
  };
  const remoteCounts = [];
  const playedUsers = [];

  const session = await createAliyunRtcAudioSession({
    credentials: {
      app_id: 'app_1',
      token: 'token_1',
      user_id: 'user_1',
      channel_id: 'interview_1',
      user_name: '候选人',
    },
    sdk,
    onRemoteUserCount: (count) => remoteCounts.push(count),
    onRemoteAudio: (user) => playedUsers.push(user.userId),
  });

  assert.deepEqual(calls.join, {
    appId: 'app_1',
    token: 'token_1',
    uid: 'user_1',
    channel: 'interview_1',
    userName: '候选人',
  });
  assert.equal(calls.published, microphoneTrack);
  assert.equal(remoteTrack.played, true);
  assert.deepEqual(playedUsers, ['agent_1']);
  assert.deepEqual(remoteCounts, [1]);

  await session.leave();
  assert.equal(calls.unpublished, microphoneTrack);
  assert.equal(microphoneTrack.closed, true);
  assert.equal(remoteTrack.stopped, true);
  assert.equal(calls.left, true);
  assert.equal(events.size, 0);
});


test('rejects unsupported browsers before creating a client', async () => {
  await assert.rejects(
    createAliyunRtcAudioSession({
      credentials: {},
      sdk: {
        checkSystemRequirements: () => false,
        createClient: () => {
          throw new Error('must not create client');
        },
      },
    }),
    /不支持阿里云 RTC/
  );
});


test('registers the AI agent plugin before joining and forwards captions and status', async () => {
  const clientEvents = new Map();
  const pluginEvents = new Map();
  const calls = { plugin: null, joinedAfterRegister: false };
  const microphoneTrack = { close() {} };

  class FakeAiAgentClient {
    constructor(userId) {
      this.userId = userId;
      this.detached = false;
    }
    on(name, handler) { pluginEvents.set(name, handler); }
    off(name) { pluginEvents.delete(name); }
    detach() { this.detached = true; }
  }

  const client = {
    remoteUsers: [],
    on(name, handler) { clientEvents.set(name, handler); },
    off(name) { clientEvents.delete(name); },
    register(plugin) { calls.plugin = plugin; },
    async join() {
      calls.joinedAfterRegister = Boolean(calls.plugin);
      return { remoteUsers: [] };
    },
    async publish() {},
    async unpublish() {},
    leave() {},
  };
  const statuses = [];
  const messages = [];

  const session = await createAliyunRtcAudioSession({
    credentials: {
      app_id: 'app_1',
      token: 'token_1',
      user_id: 'user_1',
      channel_id: 'interview_1',
      ai_agent: { enabled: true, user_id: 'agent_1' },
    },
    sdk: {
      checkSystemRequirements: () => true,
      createClient: () => client,
      createMicrophoneAudioTrack: async () => microphoneTrack,
    },
    aiAgentSdk: FakeAiAgentClient,
    onAgentStatus: (status) => statuses.push(status),
    onAgentMessage: (message) => messages.push(message),
  });

  assert.equal(calls.plugin.userId, 'agent_1');
  assert.equal(calls.joinedAfterRegister, true);
  pluginEvents.get('agent-status')('thinking');
  pluginEvents.get('message')({ message: '请介绍你的项目', userType: 'agent', end: true });
  assert.deepEqual(statuses, ['thinking']);
  assert.deepEqual(messages, [{ message: '请介绍你的项目', userType: 'agent', end: true }]);

  await session.leave();
  assert.equal(calls.plugin.detached, true);
  assert.equal(pluginEvents.size, 0);
});
