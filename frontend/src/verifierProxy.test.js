import assert from 'node:assert/strict';
import { EventEmitter } from 'node:events';
import test from 'node:test';
import config from '../vite.config.js';

test('只代理公开验真 GET，不转发校内凭据和来源页面', () => {
  const [context, options] = Object.entries(config.server.proxy).find(([path]) => path.startsWith('^/verify/'));
  const serial = '0123456789abcdef'.repeat(2);
  const path = '/verify/' + serial;
  const match = new RegExp(context);
  assert.equal(match.test(path), true);
  for (const other of ['/verify/', path + '/applications', path + '?token=ignored', '/applications']) {
    assert.equal(match.test(other), false);
  }
  assert.equal(options.bypass({ method: 'POST', headers: {} }), false);
  assert.equal(options.bypass({ method: 'GET', headers: { 'transfer-encoding': 'chunked' } }), false);
  assert.equal(options.bypass({ method: 'GET', headers: { 'content-length': '12' } }), false);
  assert.equal(options.bypass({ method: 'GET', headers: {} }), undefined);

  const proxy = new EventEmitter();
  const headers = new Map(Object.entries({ host: 'verifier.test', accept: 'text/html',
    cookie: 'identity_student_session=fixture', authorization: 'Bearer fixture',
    'x-school-id': 'untrusted', referer: 'http://school.test/student' }));
  options.configure(proxy);
  proxy.emit('proxyReq', { getHeaderNames: () => [...headers.keys()], removeHeader: (name) => headers.delete(name) });
  assert.deepEqual([...headers.keys()], ['host', 'accept']);
  const response = { headers: { 'set-cookie': 'unexpected=fixture', 'cache-control': 'no-store' } };
  proxy.emit('proxyRes', response);
  assert.deepEqual(response.headers, { 'cache-control': 'no-store' });
});
