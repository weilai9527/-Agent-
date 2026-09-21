const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const events = {};
const store = new Map();
const app = {innerHTML:''};
const root = {dataset:{}};
const ctx = vm.createContext({document:{documentElement:root,querySelector:s=>s==='#app'?app:null,addEventListener:(k,f)=>(events[k]??=[]).push(f)},sessionStorage:{getItem:k=>store.get(k),setItem:(k,v)=>store.set(k,v),removeItem:k=>store.delete(k)},location:{hash:'#login'},window:{addEventListener(){}},setTimeout,clearTimeout,URL,console});
vm.runInContext(fs.readFileSync('app.js','utf8'),ctx);
vm.runInContext(fs.readFileSync('edition.js','utf8'),ctx);
assert(app.innerHTML.includes('夜间模式'));
function click(data){const event={target:{closest:s=>s==='[data-v2]'?{dataset:{v2:data.action,...data}}:null}};for(const f of events.click)f(event)}
click({action:'theme'});
assert.equal(root.dataset.theme,'night');
assert.equal(store.get('astra-v2-theme'),'night');
assert(app.innerHTML.includes('日间模式'));
vm.runInContext("user='demo'",ctx);
for(const theme of ['day','night']){
  root.dataset.theme=theme;
  for(const route of ['home','phone','custom','portrait','me','resume','history','analysis','report','interview']){
    ctx.location.hash='#'+route;vm.runInContext('render()',ctx);
    assert(app.innerHTML.includes('退出登录'),`${theme}/${route}`);
    assert(!app.innerHTML.includes('undefined'),`${theme}/${route}`);
  }
}
ctx.location.hash='#custom';
for(const level of ['应届','低级','中级','高级']){
  click({action:'level',value:level});
  assert.equal(vm.runInContext('Object.keys(selection).length',ctx),0);
  for(let i=0;i<5;i++){
    click({action:'dimension',id:String(i)});
    const choice=vm.runInContext(`config[level][${i}][0]`,ctx);
    click({action:'value',value:choice});
    assert.equal(vm.runInContext('activeDimension',ctx),i);
  }
  assert.equal(vm.runInContext('Object.keys(selection).length',ctx),5);
  assert(app.innerHTML.includes('开始面试 ↗'));
  click({action:'dimension',id:'2'});
  assert.equal(vm.runInContext('activeDimension',ctx),2);
}
console.log('PASS: dual themes, 20 themed route renders, all four configuration paths, reset and revisit.');

