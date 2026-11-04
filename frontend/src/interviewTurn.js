// 重试必须对应同一道题的同一份回答，即使首次请求
// 已经提交成功，随后连接才断开。
export function createAnswerSubmission({ questionId, content, sourceRef, previous }) {
  const source = sourceRef ? 'aliyun_rtc' : 'text';
  if (!sourceRef && previous?.question_id === questionId && previous.content === content) return previous;
  const id = sourceRef || globalThis.crypto?.randomUUID?.() || `text-${Date.now()}-${Math.random().toString(36).slice(2)}`;
  return { question_id: questionId, submission_id: id, content, source, transcript_text: sourceRef ? content : '' };
}

export async function postInterviewTurn(post, submission, validate, options = {}) {
  const delay = options.delay || ((ms) => new Promise(resolve => setTimeout(resolve, ms)));
  const maxPendingAttempts = options.maxPendingAttempts ?? 60;
  async function send() {
    for (let attempt = 0; attempt <= maxPendingAttempts; attempt++) {
      const response = await post(submission);
      if (response?.processing) {
        if (attempt === maxPendingAttempts) throw Object.assign(new Error('回答仍在处理中，请稍后重试。'), { status: 503 });
        await delay(Math.max(100, Math.min(2000, Number(response.retry_after_ms) || 500)));
        continue;
      }
      if (validate && !validate(response)) throw new Error('面试进度响应不完整，请重试。');
      return response;
    }
  }
  try {
    return await send();
  } catch (error) {
    if (error.status && error.status < 500) throw error;
    return send();
  }
}

// 按到达顺序处理字幕；写入失败的字幕保留在队首，
// 等待明确重试，避免后续回答越过其对应的语音题目。
export function createRtcWriteQueue(onError) {
  const writes = [];
  let running = null;
  let failure = null;
  function run() {
    if (running) return running;
    running = Promise.resolve().then(async () => {
      while (writes.length) {
        await writes[0]();
        writes.shift();
      }
    }).catch(error => {
      failure = error;
      onError(error);
    }).finally(() => { running = null; });
    return running;
  }
  return {
    enqueue(write) {
      writes.push(write);
      if (!failure) void run();
    },
    async drain() {
      if (running) await running;
      if (writes.length) {
        failure = null;
        await run();
      }
      if (failure) throw failure;
    },
  };
}
