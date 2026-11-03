// A retry must identify the same answer to the same question, even if the
// first request committed before the connection was lost.
export function createAnswerSubmission({ questionId, content, sourceRef, previous }) {
  const source = sourceRef ? 'aliyun_rtc' : 'text';
  if (!sourceRef && previous?.question_id === questionId && previous.content === content) return previous;
  const id = sourceRef || globalThis.crypto?.randomUUID?.() || `text-${Date.now()}-${Math.random().toString(36).slice(2)}`;
  return { question_id: questionId, submission_id: id, content, source, transcript_text: sourceRef ? content : '' };
}

export async function postInterviewTurn(post, submission, validate) {
  async function send() {
    const response = await post(submission);
    if (validate && !validate(response)) throw new Error('面试进度响应不完整，请重试。');
    return response;
  }
  try {
    return await send();
  } catch (error) {
    if (error.status && error.status < 500) throw error;
    return send();
  }
}

// Keep captions in arrival order. A failed write stays at the head until an
// explicit retry, so later answers cannot overtake their spoken question.
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
