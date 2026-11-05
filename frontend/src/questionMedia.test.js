import assert from 'node:assert/strict';
import test from 'node:test';
import { clipMessage, confirmPendingVideo, fetchQuestionClip, questionRecorder } from './questionMedia.js';

const expires = () => Math.floor(Date.now() / 1000) + 110;
const token = () => ({ app_id: 'app', channel_id: 'channel', user_id: 'candidate', token: 'test', expires_at: expires() });
const receipt = state => ({ state, question_id: 'question', recording_id: 'clip' });

function scenario({ reply, cameraPermission, publishError } = {}) {
  const log = [];
  const states = [];
  const track = { on() {}, off() {}, play: () => log.push('preview'), close: () => log.push('camera closed') };
  const sdk = {
    checkSystemRequirements: () => true,
    createClient: () => ({
      on() {}, off() {}, join: async data => { assert.equal(data.uid, 'candidate'); log.push('joined'); },
      publish: async () => { if (publishError) throw publishError; log.push('published'); },
      leave: async () => log.push('left'),
    }),
    createCameraVideoTrack: async () => { await cameraPermission; return track; },
  };
  const request = async (path, options) => {
    assert.equal(options.method, 'POST');
    log.push(path);
    if (path.endsWith('/token')) return token();
    if (reply) return reply(path);
    return receipt(path.endsWith('/start') ? 'recording' : 'processing');
  };
  const recorder = questionRecorder({ request, interviewId: 'interview', questionId: 'question',
    getSdk: async () => sdk, onState: (state, message) => states.push([state, message]) });
  return { log, states, recorder };
}

test('真实发布后才向本题申请录制，并先关闭设备再确认云端停录', async () => {
  const { log, states, recorder } = scenario();
  await recorder.start();
  assert.equal(states.at(-1)[0], 'recording');
  await Promise.all([recorder.stop(), recorder.stop()]);
  assert.deepEqual(log, [
    '/api/interviews/interview/media/video/token', 'joined', 'published', 'preview',
    '/api/interviews/interview/media/questions/question/recording/start', 'camera closed', 'left',
    '/api/interviews/interview/media/questions/question/recording/stop',
  ]);
  assert.match(states.at(-1)[1], /正在处理/);
});

test('SDK 发布失败时释放摄像头，不产生云端录制或成功提示', async () => {
  const { log, states, recorder } = scenario({ publishError: new Error('发布失败') });
  await recorder.start();
  assert.ok(log.includes('camera closed'));
  assert.ok(log.includes('left'));
  assert.equal(log.some(item => item.includes('/recording/')), false);
  assert.equal(states.some(([state]) => state === 'recording'), false);
  assert.match(states.at(-1)[1], /发布失败/);
});

test('学生切题后到达的摄像头授权被立即释放', async () => {
  let allowCamera;
  const cameraPermission = new Promise(resolve => { allowCamera = resolve; });
  const { log, recorder } = scenario({ cameraPermission });
  const opening = recorder.start();
  await new Promise(resolve => setImmediate(resolve));
  assert.ok(log.includes('joined'));
  await recorder.stop();
  allowCamera();
  await opening;
  assert.ok(log.includes('camera closed'));
  assert.equal(log.includes('published'), false);
});

test('开始录制回执异常也会按原题停录，失败可重试', async () => {
  let stopped = false;
  const { log, states, recorder } = scenario({ reply(path) {
    if (path.endsWith('/start')) return { ...receipt('recording'), question_id: 'other' };
    if (!stopped) { stopped = true; throw Object.assign(new Error('down'), { status: 503 }); }
    return receipt('ready');
  } });
  await assert.rejects(recorder.start(), /尚未确认/);
  assert.equal(states.at(-1)[0], 'unconfirmed');
  assert.equal(states.some(([state]) => state === 'recording'), false);
  await recorder.stop();
  assert.match(states.at(-1)[1], /可回放/);
  assert.equal(log.filter(item => item.endsWith('/stop')).length, 2);
});

test('回执在取消之后到达时，仍须完成该题停录', async () => {
  let admit;
  const pending = new Promise(resolve => { admit = resolve; });
  const { log, states, recorder } = scenario({ reply: path => path.endsWith('/start') ? pending : receipt('ready') });
  const beginning = recorder.start();
  await new Promise(resolve => setImmediate(resolve));
  const leaving = recorder.stop();
  assert.ok(log.includes('camera closed'));
  admit(receipt('recording'));
  await Promise.all([leaving, beginning]);
  assert.equal(states.some(([state]) => state === 'recording'), false);
  assert.equal(log.filter(item => item.endsWith('/stop')).length, 1);
});

test('回放只接受绑定本题、尚未过期的 HTTPS 授权', async () => {
  const good = { question_id: 'Q 1', recording_id: 'clip', url: 'https://store.invalid/video', expires_at: expires() };
  const grant = await fetchQuestionClip(async path => {
    assert.equal(path, '/api/interviews/i/media/questions/Q%201/playback');
    return good;
  }, 'i', 'Q 1');
  assert.equal(grant.url, good.url);
  for (const patch of [{ question_id: 'other' }, { url: 'http://wrong.invalid/clip' }, { expires_at: 1 }]) {
    await assert.rejects(fetchQuestionClip(async () => ({ ...good, ...patch }), 'i', 'Q 1'));
  }
  assert.match(clipMessage({ status: 404 }, true), /没有可查看/);
  assert.match(clipMessage({ status: 409 }, true), /暂未就绪/);
  assert.match(clipMessage({ status: 503 }, true), /暂时不可用/);
});

test('切回语音前重新核实上一题停录，回执丢失时保留标记并拒绝切换', async () => {
  const { recorder } = scenario({ reply(path) {
    if (path.endsWith('/start')) return receipt('recording');
    throw Object.assign(new Error('down'), { status: 503 });
  } });
  await recorder.start();
  await assert.rejects(recorder.stop(), /尚未确认/);
  let requests = 0;
  const retry = async path => {
    requests++;
    assert.equal(path, '/api/interviews/interview/media/questions/question/recording/stop');
    if (requests === 1) throw Object.assign(new Error('unknown'), { status: 404 });
    return receipt('processing');
  };
  await assert.rejects(confirmPendingVideo(retry, 'interview'), /尚未确认/);
  await confirmPendingVideo(retry, 'interview');
  await confirmPendingVideo(retry, 'interview');
  assert.equal(requests, 2);
});
