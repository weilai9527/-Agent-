const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const events = {};
const storage = new Map();
const app = { innerHTML: '' };
const context = vm.createContext({
  document: { querySelector: s => s === '#app' ? app : null, addEventListener: (k, fn) => events[k] = fn },
  sessionStorage: { getItem: k => storage.get(k), setItem: (k, v) => storage.set(k, v), removeItem: k => storage.delete(k) },
  location: { hash: '#login' }, window: { addEventListener() {} },
  setTimeout, clearTimeout, URL, console,
});
vm.runInContext(fs.readFileSync('app.js', 'utf8'), context);
assert(app.innerHTML.includes('输入学号'));
vm.runInContext("user='20260001'", context);
for (const route of ['home', 'phone', 'custom', 'portrait', 'me', 'resume', 'history', 'analysis', 'report', 'interview']) {
  context.location.hash = '#' + route;
  vm.runInContext('render()', context);
  assert(app.innerHTML.includes('退出登录'), route);
  assert(!app.innerHTML.includes('undefined'), route);
}
vm.runInContext("level='高级';selection={0:'技术二面',1:'互联网大厂',2:'系统设计',3:'严格',4:'沉默压迫'};", context);
context.location.hash = '#custom';
vm.runInContext('render()', context);
assert(app.innerHTML.includes('开始面试 ↗'));
vm.runInContext("messages=[{role:'ai',text:questions[0]}];answer('<img src=x onerror=alert(1)>')", context);
assert.equal(vm.runInContext('messages.length', context), 3);
assert.equal(vm.runInContext("esc('<script>')", context), '&lt;script&gt;');
assert.equal(vm.runInContext('Object.keys(config).length', context), 4);
assert(vm.runInContext('Object.values(config).every(x=>x.length===5)', context));
events.click({target:{closest:()=>({dataset:{action:'finish'}})}});
assert.equal(vm.runInContext('history.length', context), 1);
vm.runInContext("messages=[]", context);
events.click({target:{closest:()=>({dataset:{action:'report',source:'history',id:'0'}})}});
assert.equal(vm.runInContext('messages.length', context), 3);
assert.equal(storage.get('astra-report-new'), 'yes');
console.log('PASS: 10 routes, configuration, chat escaping, history snapshot and report restoration.');
