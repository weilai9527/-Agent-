// Return to the logical parent, independently of browser visit history.
const parentPages={home:['login','登录页面'],phone:['home','面试空间'],portrait:['home','面试空间'],me:['home','面试空间'],custom:['phone','难度选择'],resume:['me','我的'],history:['me','我的'],analysis:['resume','我的简历'],report:['history','我的历史']};
let interviewParent=sessionStorage.getItem('astra-v3-interview-parent')==='custom'?'custom':'phone';
function parentOf(page){return page==='interview'?[interviewParent,interviewParent==='custom'?'自主难度设置':'难度选择']:parentPages[page]||parentPages.home}
const shellBeforeNavigation=shell;
shell=function(content,page){
  const [parent,label]=parentOf(page);
  // The common toolbar replaces the configurator's former one-off return button.
  content=content.replace(/<button class="back" data-action="back" data-value="phone">[\s\S]*?<\/button>/,'');
  const toolbar=`<div class="parent-toolbar"><a class="parent-back" href="#${parent}" data-parent="${parent}" aria-label="返回上一级：${label}"><span aria-hidden="true">←</span> 返回${label}</a><span class="parent-hint">${page==='home'?'个人面试空间':'面试空间 / '+({phone:'电话面试',portrait:'能力画像',me:'我的',custom:'自主配置',resume:'我的简历',history:'我的历史',analysis:'简历分析',report:'历史报告',interview:'面试进行中'}[page]||'')}</span></div>`;
  return shellBeforeNavigation(toolbar+content,page);
};
document.addEventListener('click',async e=>{
  const start=e.target.closest('[data-action="start"]');
  if(start){interviewParent=location.hash==='#custom'?'custom':'phone';sessionStorage.setItem('astra-v3-interview-parent',interviewParent)}
  const back=e.target.closest('[data-parent]');if(!back)return;
  // Modified clicks retain the browser's normal link behavior.
  if(e.ctrlKey||e.metaKey||e.shiftKey||e.altKey)return;
  e.preventDefault();e.stopImmediatePropagation();
  if(location.hash==='#interview'){rememberDraft();++voiceState.token;stopSpeech();await stopRecording()}
  go(back.dataset.parent);
},true);
render();
