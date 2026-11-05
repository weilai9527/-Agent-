export function newRequestId() {
  // 校内 HTTP 页面可能不能调用 randomUUID，但仍可用 getRandomValues 生成请求编号。
  if (crypto.randomUUID) return crypto.randomUUID();
  return Array.from(crypto.getRandomValues(new Uint8Array(16)), (byte) => byte.toString(16).padStart(2, '0')).join('');
}

// 教学服务按任务和学生去重。相同已领取次数对应同一次新领取，跨标签页或丢失响应时沿用同一编号。
export function claimRequestId(usedAttempts) {
  return 'student-ui-' + (usedAttempts + 1);
}

// 超时时服务端可能已经提交。相同内容重试时复用请求编号，操作人身份仍由网关签名决定。
export function keyedWrite(previous, payload) {
  const signature = JSON.stringify(payload);
  const request_id = previous?.signature === signature ? previous.request_id : newRequestId();
  return { signature, request_id };
}

export function postJson(request, path, body) {
  return request(path, { method: 'POST', body: JSON.stringify(body) });
}

export function localDate(value) {
  return new Date(value).toLocaleString('zh-CN', { dateStyle: 'medium', timeStyle: 'short' });
}

export function futureDeadline(value) {
  const date = new Date(value);
  if (!(date.getTime() > Date.now())) throw new Error('请选择晚于当前时间的截止时间。');
  return date.toISOString();
}

export function readError(error) {
  return (typeof error.data?.detail === 'string' && error.data.detail) || error.message || '读取失败，请重试。';
}
