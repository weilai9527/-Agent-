const test = require('node:test');
const assert = require('node:assert/strict');
const React = require('react');
const { JSDOM } = require('jsdom');
const { buildSync } = require('esbuild');
const { Module } = require('node:module');
const path = require('node:path');

// 只模拟页面的网关响应；授权、持久队列及历史数据约束由独立服务集成测试覆盖。
function component(name) {
  const file = path.join(__dirname, '../src', name+'.jsx');
  const out = buildSync({entryPoints:[file], bundle:true, platform:'node', external:['react'], format:'cjs',write:false});
  const mod = new Module(file, module);
  mod.paths = module.paths;
  mod._compile(out.outputFiles[0].text,file);
  return mod.exports.default;
}

test('教师模板读者能查看策略，只有记录读者请求具体使用明细',async () => {
  const dom = new JSDOM('<main></main>');
  Object.assign(globalThis,{window:dom.window,document:dom.window.document,IS_REACT_ACT_ENVIRONMENT:true});
  const root = require('react-dom/client').createRoot(document.querySelector('main'));
  const Page = component('NativeAgentTemplates');
  const calls=[];
  const request=async url => {
    const params=new URL(url,'https://school.test').searchParams;
    calls.push(params);
    return {items:[{name:'技术面试官',type:'technical',focus:'后端',usageCount:3,strategy:params.get('name')?'复核论据':''}],
      recentUsage:params.get('recent')==='true'?[{instance_id:'x',candidate:'已授权学生',interview_id:'i'}]:[]};
  };
  try {
    for (const allowed of [false,true]) {
      await React.act(async()=>root.render(React.createElement(Page,{key:String(allowed),request,canReadInterviews:allowed})));
      await React.act(async()=>Array.from(document.querySelectorAll('button')).find(b=>b.textContent==='技术面试官').click());
      assert.match(document.body.textContent,/复核论据/);
      assert.equal(calls.at(-1).get('recent'),String(allowed));
      assert.equal(document.body.textContent.includes('已授权学生'),allowed);
    }
  } finally {await React.act(async()=>root.unmount());dom.window.close();}
});

test('连接日志跨学生页重新查询并清空已撤权记录',async () => {
  const dom=new JSDOM('<main></main>');
  Object.assign(globalThis,{window:dom.window,document:dom.window.document,IS_REACT_ACT_ENVIRONMENT:true});
  const root=require('react-dom/client').createRoot(document.querySelector('main'));
  const Page=component('NativeConnectionLogs');
  const calls=[];
  const request=async url=>{
    const params=new URL(url,'https://school.test').searchParams;
    calls.push(params);
    if(params.get('after_student')) throw new Error('授权已撤销');
    return {logs:[{id:'e',candidate:'甲班学生',interview_id:'i',event_type:'token_issued',level:'info',created_at:'2026-01-01'}],nextStudents:'s',hasMore:false,retentionDays:0};
  };
  try {
    await React.act(async()=>root.render(React.createElement(Page,{request})));
    assert.match(document.body.textContent,/甲班学生/);
    await React.act(async()=>Array.from(document.querySelectorAll('button')).find(b=>b.textContent==='下一页学生').click());
    assert.equal(calls.at(-1).get('after_student'),'s');
    assert.match(document.body.textContent,/授权已撤销/);
    assert.doesNotMatch(document.body.textContent,/甲班学生/);
  } finally {await React.act(async()=>root.unmount());dom.window.close();}
});
