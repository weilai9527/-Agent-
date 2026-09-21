import assert from 'node:assert/strict';
import test from 'node:test';

import {
  createAliyunRtcAudioSession,
  createAliyunRtcTranscriptAssembler,
  ensureAiAgentMessagingReady,
  extractQuestionFromAgentTranscript,
  findLatestInterviewQuestion,
  shouldPersistAliyunAgentTurn,
} from './aliyunRtc.js';


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
