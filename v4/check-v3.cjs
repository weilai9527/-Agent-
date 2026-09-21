const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const listeners={},store=new Map(),app={innerHTML:''},root={dataset:{}};
let stops=0,permissionError=false,deferredPermission=null;
class FakeRecorder{
 constructor(){this.state='inactive';this.mimeType='audio/webm'}
 start(){this.state='recording'}
 stop(){this.state='inactive';queueMicrotask(()=>{this.ondataavailable({data:new Blob(['audio sample'],{type:'audio/webm'})});this.onstop()})}
}
const context=vm.createContext({document:{documentElement:root,querySelector:s=>s==='#app'?app:null,addEventListener:(name,fn,capture)=>{(listeners[name]??=[]).push({fn,capture})}},sessionStorage:{getItem:k=>store.get(k),setItem:(k,v)=>store.set(k,v),removeItem:k=>store.delete(k)},location:{_hash:'#login',get hash(){return this._hash},set hash(v){this._hash=v.startsWith('#')?v:'#'+v}},window:{addEventListener(){},MediaRecorder:FakeRecorder},navigator:{mediaDevices:{getUserMedia:async()=>{if(permissionError)throw Object.assign(new Error(),{name:'NotAllowedError'});if(deferredPermission)await deferredPermission;return{getTracks:()=>[{stop(){stops++}}]}}}},MediaRecorder:FakeRecorder,Blob,URL,setTimeout,clearTimeout,setInterval(){},console});
const run=s=>vm.runInContext(s,context);
for(const file of ['app.js','edition.js','voice.js'])run(fs.readFileSync(file,'utf8'));
async function click(dataset){let stopped=false;const e={stopImmediatePropagation(){stopped=true},target:{closest(selector){if(selector.includes('[data-voice]'))return{dataset};if(selector==='[data-action]'&&dataset.action)return{dataset};if(selector==='[data-v2]'&&dataset.v2)return{dataset};return null}}};for(const {fn} of [...listeners.click].sort((a,b)=>Number(!!b.capture)-Number(!!a.capture))){await fn(e);if(stopped)break}}
(async()=>{
 run("user='demo';messages=[{role:'ai',text:questions[0]},{role:'self',text:'文字回答'}];mode='text'");context.location.hash='#interview';
 await click({action:'mode'});assert.equal(run('mode'),'voice');assert(!app.innerHTML.includes('id="chat-form"'));
 await run('recordAnswer()');assert.equal(run('voiceState.recording'),true);
 await run('stopRecording()');assert.equal(run('voiceState.answers.length'),1);assert.equal(stops,1);assert.equal(run('messages.length'),2);
 await click({action:'mode'});assert.equal(run('mode'),'text');assert(app.innerHTML.includes('文字回答'));
 await click({action:'mode'});assert(app.innerHTML.includes('<audio controls'));assert.equal(run('voiceState.round'),0);
 await click({voice:'next'});assert.equal(run('voiceState.round'),1);
 permissionError=true;await run('recordAnswer()');assert(run('voiceState.error').includes('权限'));assert.equal(run('voiceState.recording'),false);permissionError=false;
 await run('recordAnswer()');await click({action:'finish'});assert.equal(run('history[0].audio.length'),2);assert.equal(run('history[0].mode'),'voice');assert(app.innerHTML.includes('待评估'));
 context.location.hash='#interview';run("mode='text'");await click({action:'finish'});assert.equal(run('history[0].mode'),'text');assert(app.innerHTML.includes('文字回答'));
 await click({action:'report',source:'history',id:'1'});assert(app.innerHTML.includes('语音面试复盘'));assert(app.innerHTML.includes('<audio controls'));
 context.location.hash='#interview';run("mode='voice';voiceState.round=3");let grant;deferredPermission=new Promise(r=>grant=r);const pending=run('recordAnswer()');await click({action:'mode'});grant();await pending;assert.equal(run('voiceState.recording'),false);assert.equal(run('mode'),'text');assert(stops>=3);
 assert(!fs.readFileSync('app.js','utf8').includes('SpeechRecognition'));
 console.log('PASS: independent modes, audio capture, playback, permission denial, microphone release, pending-permission cancellation, separate history and unscored reports.');
})().catch(error=>{console.error(error);process.exitCode=1});

