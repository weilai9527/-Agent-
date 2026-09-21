// Voice practice keeps audio answers separate from the text conversation.
const voiceState={round:0,answers:[],recording:false,requesting:false,stream:null,recorder:null,started:0,error:'',speaking:false,pending:null,token:0};
let selectedPractice=null,textDraft='';
const voiceUrls=new Set();
const baseInterview=interview,baseReport=report,baseRender=render;
const formatTime=seconds=>`${Math.floor(seconds/60).toString().padStart(2,'0')}:${Math.floor(seconds%60).toString().padStart(2,'0')}`;
function stopSpeech(){if(window.speechSynthesis)window.speechSynthesis.cancel();voiceState.speaking=false}
function releaseStream(){voiceState.stream?.getTracks().forEach(track=>track.stop());voiceState.stream=null}
function rememberDraft(){const input=document.querySelector('#chat-form input');if(input)textDraft=input.value}
function stopRecording(){
  if(voiceState.pending)return voiceState.pending;
  if(!voiceState.recorder||voiceState.recorder.state==='inactive'){releaseStream();return Promise.resolve()}
  voiceState.pending=new Promise(resolve=>{voiceState.resolve=resolve});
  voiceState.recorder.stop();voiceState.recording=false;releaseStream();return voiceState.pending;
}
async function recordAnswer(){
  if(voiceState.recording){await stopRecording();render();return}
  if(voiceState.requesting||voiceState.pending||voiceState.answers[voiceState.round])return;
  if(!navigator.mediaDevices?.getUserMedia||!window.MediaRecorder){voiceState.error='当前浏览器无法录音。请在支持麦克风录音的浏览器中使用 localhost 或 HTTPS 打开本页面。';render();return}
  stopSpeech();voiceState.error='';voiceState.requesting=true;const token=++voiceState.token;render();
  try{
    const stream=await navigator.mediaDevices.getUserMedia({audio:true});
    if(token!==voiceState.token||mode!=='voice'||location.hash!=='#interview'){stream.getTracks().forEach(t=>t.stop());return}
    voiceState.stream=stream;
    const recorder=new MediaRecorder(stream),chunks=[],round=voiceState.round;
    voiceState.recorder=recorder;
    recorder.ondataavailable=e=>{if(e.data.size)chunks.push(e.data)};
    recorder.onstop=()=>{
      const duration=Math.max(1,Math.round((Date.now()-voiceState.started)/1000));
      if(chunks.length){const blob=new Blob(chunks,{type:recorder.mimeType||chunks[0].type});const url=URL.createObjectURL(blob);voiceUrls.add(url);voiceState.answers[round]={question:questions[round],url,duration}}
      else voiceState.error='未获取到音频，请检查麦克风后重试。';
      voiceState.recording=false;voiceState.recorder=null;releaseStream();
      const resolve=voiceState.resolve;voiceState.pending=null;voiceState.resolve=null;resolve?.();
      if(mode==='voice'&&location.hash==='#interview')render();
    };
    recorder.onerror=()=>{voiceState.error='录音中断，请检查设备后重试。';stopRecording()};
    voiceState.started=Date.now();recorder.start();voiceState.recording=true;
  }catch(error){releaseStream();voiceState.error=error.name==='NotAllowedError'?'麦克风权限未开启。允许麦克风后可重试，聊天模式仍可使用。':'无法使用麦克风，请检查设备连接或浏览器设置。'}
  finally{voiceState.requesting=false;if(mode==='voice'&&location.hash==='#interview')render()}
}
function speakQuestion(){
  if(!window.speechSynthesis||!window.SpeechSynthesisUtterance){voiceState.error='当前浏览器无法播放合成语音，可阅读题目继续录音。';render();return}
  stopSpeech();const utterance=new SpeechSynthesisUtterance(questions[voiceState.round]);utterance.lang='zh-CN';utterance.rate=.95;
  utterance.onend=utterance.onerror=()=>{voiceState.speaking=false;if(mode==='voice'&&location.hash==='#interview')render()};
  voiceState.speaking=true;window.speechSynthesis.speak(utterance);render();
}
interview=function(){
  if(mode==='text')return `<div class="mode-banner"><span>01 / 文字面试</span><span>独立文字对话 · 切换模式保留进度</span></div>`+baseInterview();
  const current=voiceState.answers[voiceState.round];
  return `<div class="heading voice-heading"><div><div class="eyebrow">02 / VOICE INTERVIEW</div><h2>听见问题，从容作答。</h2></div><button class="ghost" data-action="mode">转聊天框 ▤</button></div><div class="call-layout"><section class="call-stage"><div class="call-top"><span><i class="status-dot"></i>独立语音面试</span><span>第 ${voiceState.round+1} / ${questions.length} 题</span></div><div class="caller-avatar ${voiceState.speaking?'speaking':''}">${logo}</div><h2>Astra 面试官</h2><p class="call-subtitle">${voiceState.speaking?'面试官正在提问…':voiceState.requesting?'正在请求麦克风权限…':voiceState.recording?'正在接收你的语音…':current?'回答已保存，可以回听或继续':'准备好后，播放题目并开始回答'}</p><div class="sound-wave ${voiceState.recording||voiceState.speaking?'live':''}" aria-hidden="true">${Array.from({length:23},(_,i)=>`<i style="--h:${12+(i*17)%40}px;--delay:${i*.06}s"></i>`).join('')}</div><span class="call-timer" id="record-timer">${voiceState.recording?formatTime((Date.now()-voiceState.started)/1000):current?formatTime(current.duration):'00:00'}</span><div class="call-question"><span>本轮问题</span><p>${esc(questions[voiceState.round])}</p></div><div class="call-controls"><button class="call-control" data-voice="speak" ${voiceState.recording||voiceState.requesting?'disabled':''}><span>◖))</span>${voiceState.speaking?'重新播放':'播放题目'}</button><button class="call-control record-control ${voiceState.recording?'recording':''}" data-voice="record" ${voiceState.requesting||current?'disabled':''}><span>${voiceState.recording?'■':icon('mic')}</span>${voiceState.recording?'完成回答':voiceState.requesting?'等待授权':'开始回答'}</button><button class="call-control end-control" data-action="finish"><span>${icon('phone')}</span>结束面试</button></div>${voiceState.error?`<div class="voice-error" role="alert">${esc(voiceState.error)}</div>`:''}<div class="call-disclosure">语音练习演示 · 音频仅在当前页面保存，不转写为文字<br>题目由浏览器合成语音播放，尚未接入实时 AI 通话与评分</div></section><aside class="call-notes"><div class="eyebrow">SESSION NOTES</div><h2>你的语音进度</h2><p>文字与语音分别练习，<br>切换模式不会合并回答。</p><div class="voice-steps">${questions.map((q,i)=>`<div class="voice-step ${i===voiceState.round?'current':''}"><span>${voiceState.answers[i]?'✓':String(i+1).padStart(2,'0')}</span><div>${['自我介绍','技术挑战','方案权衡','系统扩展','结果量化'][i]}<small>${voiceState.answers[i]?'已录制 · '+formatTime(voiceState.answers[i].duration):i===voiceState.round?'当前问题':'待练习'}</small></div></div>`).join('')}</div>${current?`<div class="audio-review"><h3>本轮回答</h3><audio controls preload="metadata" src="${current.url}"></audio><button class="ghost" data-voice="retry">重新录制</button></div><button class="primary dark voice-next" ${voiceState.round===questions.length-1?'data-action="finish"':'data-voice="next"'}>${voiceState.round===questions.length-1?'完成语音面试':'下一题'} ↗</button>`:'<div class="voice-tip">点击「开始回答」录音，<br>说完后点击「完成回答」。</div>'}</aside></div>`;
};
report=function(){
  if(!selectedPractice||sessionStorage.getItem('astra-report-new')!=='yes')return baseReport();
  const isVoice=selectedPractice.mode==='voice';
  return title(isVoice?'VOICE SESSION REVIEW':'TEXT SESSION REVIEW',isVoice?'语音面试复盘':'文字面试复盘',`${selectedPractice.date} · ${isVoice?'独立语音模式':'独立文字模式'}`)+`<div class="report-note">本次练习未接入 AI 评估，得分与能力评价尚未生成。以下为本次实际${isVoice?'录音':'对话'}记录。</div><div class="report-grid"><section class="card"><h3>核心能力模型</h3>${skills.map(s=>`<div class="meter">${s}<span>待评估</span><div class="track"></div></div>`).join('')}</section><div><section class="card"><h3>面试官综合评价</h3><p>尚未生成评价。可先回顾自己的回答，检查表达结构、方案依据和量化结果。</p></section><section class="card" style="margin-top:20px"><h3>报告结论与训练建议</h3><p>尚无自动分析结论。通用自查：是否清晰说明了背景、个人贡献、关键决策与最终结果？</p><a class="primary dark" href="#phone">开启下一次练习 ↗</a></section></div><section class="card" style="grid-column:1/-1"><h3>逐题问答复盘</h3>${isVoice?(selectedPractice.audio.length?selectedPractice.audio.map((a,i)=>`<div class="audio-answer"><h3>${i+1}. ${esc(a.question)}</h3><p>我的语音回答 · ${formatTime(a.duration)}</p><audio controls preload="metadata" src="${a.url}"></audio></div>`).join(''):'<p>本次未保存语音回答。</p>'):selectedPractice.messages.map(m=>`<div class="plan"><strong>${m.role==='ai'?'面试官':'我'}</strong><p>${esc(m.text)}</p></div>`).join('')}</section></div>`;
};
render=function(){baseRender();const input=document.querySelector('#chat-form input');if(input)input.value=textDraft};
document.addEventListener('input',e=>{if(e.target.matches?.('#chat-form input'))textDraft=e.target.value});
async function finishPractice(){
  ++voiceState.token;await stopRecording();stopSpeech();
  selectedPractice={name:mode==='voice'?'语音面试（未评分）':'文字面试（未评分）',date:new Date().toLocaleString('zh-CN'),type:mode==='voice'?'语音面试':'文字面试',mode,score:null,messages:messages.map(m=>({...m})),audio:voiceState.answers.filter(Boolean).map(a=>({...a}))};
  history.unshift(selectedPractice);sessionStorage.setItem('astra-report-new','yes');go('report');render();
}
document.addEventListener('click',async e=>{
  const b=e.target.closest('[data-voice], [data-action]');if(!b)return;
  const action=b.dataset.action;
  if(b.dataset.voice){e.stopImmediatePropagation();switch(b.dataset.voice){case'record':await recordAnswer();break;case'speak':speakQuestion();break;case'next':if(voiceState.answers[voiceState.round]&&voiceState.round<questions.length-1){stopSpeech();voiceState.round++;voiceState.error='';render()}break;case'retry':voiceState.answers[voiceState.round]=undefined;voiceState.error='';render();break}return}
  if(action==='mode'){e.stopImmediatePropagation();rememberDraft();++voiceState.token;await stopRecording();stopSpeech();mode=mode==='text'?'voice':'text';render();return}
  if(action==='finish'){e.stopImmediatePropagation();await finishPractice();return}
  if(action==='report'){e.stopImmediatePropagation();selectedPractice=b.dataset.source==='history'?history[Number(b.dataset.id)]:null;sessionStorage.setItem('astra-report-new',selectedPractice?'yes':'no');go('report');render();return}
  if(action==='start'){voiceState.round=0;voiceState.answers=[];voiceState.error='';selectedPractice=null;textDraft=''}
  if(action==='logout'){++voiceState.token;await stopRecording();stopSpeech()}
},true);
document.addEventListener('submit',e=>{if(e.target.id==='chat-form')textDraft=''},true);
window.addEventListener('hashchange',()=>{if(location.hash!=='#interview'){++voiceState.token;stopRecording();stopSpeech()}});
window.addEventListener('beforeunload',()=>{releaseStream();stopSpeech();voiceUrls.forEach(url=>URL.revokeObjectURL(url))});
setInterval(()=>{const timer=document.querySelector('#record-timer');if(timer&&voiceState.recording)timer.textContent=formatTime((Date.now()-voiceState.started)/1000)},1000);
render();
