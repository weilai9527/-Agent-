let activeDimension=0;
const configurationAnimations=new WeakMap();
function softenConfiguration(element,keyframes,duration=360,delay=0){
  if(!element?.animate||window.matchMedia?.('(prefers-reduced-motion: reduce)').matches)return;
  configurationAnimations.get(element)?.cancel();
  const animation=element.animate(keyframes,{duration,delay,fill:'backwards',easing:'cubic-bezier(.22,.61,.36,1)'});
  configurationAnimations.set(element,animation);
  animation.onfinish=()=>{if(configurationAnimations.get(element)===animation)configurationAnimations.delete(element)};
}
// Keep the page, scroll position and focused controls mounted during selection.
function updateConfiguration(){
  const board=document.querySelector('.neural-board');
  if(!board){render();return}
  const oldValues=board.querySelector('.neural-values').textContent;
  const oldOptions=[...board.querySelectorAll('.neural-values .network-node')].map(node=>node.dataset.value).join('|');
  const oldDimension=board.querySelector('.neural-dimensions .focused')?.dataset.id;
  const oldLevel=board.querySelector('.neural-levels .chosen')?.dataset.value;
  const wasReady=!!board.querySelector('.configuration-summary .primary');
  const oldChosen=board.querySelector('.neural-values .chosen')?.dataset.value;
  const oldSummary=board.querySelector('.summary-tags').textContent;
  const template=document.createElement('template');
  template.innerHTML=custom();
  const next=template.content.querySelector('.neural-board');
  function reconcile(current,desired){
    if(current.nodeType!==desired.nodeType||current.nodeName!==desired.nodeName){current.replaceWith(desired.cloneNode(true));return}
    if(current.nodeType===3){if(current.nodeValue!==desired.nodeValue)current.nodeValue=desired.nodeValue;return}
    if(current.nodeType!==1)return;
    for(const attr of [...current.attributes])if(!desired.hasAttribute(attr.name))current.removeAttribute(attr.name);
    for(const attr of [...desired.attributes])if(current.getAttribute(attr.name)!==attr.value)current.setAttribute(attr.name,attr.value);
    const children=[...current.childNodes],updates=[...desired.childNodes];
    for(let i=0;i<Math.max(children.length,updates.length);i++){
      if(!updates[i])children[i].remove();
      else if(!children[i])current.appendChild(updates[i].cloneNode(true));
      else reconcile(children[i],updates[i]);
    }
  }
  reconcile(board,next);
  const values=board.querySelector('.neural-values');
  const changedBranch=oldOptions!==[...values.querySelectorAll('.network-node')].map(node=>node.dataset.value).join('|')||oldDimension!==String(activeDimension)||oldLevel!==level;
  if(changedBranch){
    values.querySelectorAll('.network-node').forEach((node,index)=>{
      softenConfiguration(node,[{opacity:.15,transform:'translateY(8px) scale(.98)'},{opacity:1,transform:'translateY(0) scale(1)'}],440,index*55);
    });
    softenConfiguration(board.querySelector('.neural-dimensions .focused'),[{transform:'scale(.98)'},{transform:'scale(1.025)',offset:.55},{transform:'scale(1)'}],440);
  }
  const chosen=values.querySelector('.chosen');
  if(chosen&&oldChosen!==chosen.dataset.value){
    softenConfiguration(chosen,[{transform:'scale(.97)',boxShadow:'0 0 0 0 var(--soft)'},{transform:'scale(1.035)',boxShadow:'0 0 0 10px var(--soft)',offset:.4},{transform:'scale(1)',boxShadow:'0 0 0 0 transparent'}],580);
    softenConfiguration(chosen.querySelector('span'),[{opacity:0,transform:'scale(.55) rotate(-20deg)'},{opacity:1,transform:'scale(1.2) rotate(5deg)',offset:.6},{opacity:1,transform:'scale(1) rotate(0deg)'}],460);
  }
  if(oldSummary!==board.querySelector('.summary-tags').textContent){
    softenConfiguration(board.querySelectorAll('.summary-tags b')[activeDimension],[{opacity:.35,transform:'translateY(4px)'},{opacity:1,transform:'translateY(0)'}],420);
  }
  if(!wasReady)softenConfiguration(board.querySelector('.configuration-summary .primary'),[{opacity:0,transform:'translateY(7px) scale(.97)'},{opacity:1,transform:'translateY(0) scale(1)'}],520);
  softenConfiguration(board.querySelector('.neural-wires'),[{opacity:.6},{opacity:1}],440);
}
let night=sessionStorage.getItem('astra-v2-theme')==='night';
document.documentElement.dataset.theme=night?'night':'day';
const originalShell=shell;
shell=function(content,page){return originalShell(content,page).replace('<div class="top-actions">','<div class="top-actions"><button class="theme-switch" data-v2="theme" aria-label="切换日夜主题">'+(night?'☀ 日间模式':'☾ 夜间模式')+'</button>')};
const originalAuth=auth;
auth=function(){return `<button class="auth-theme theme-switch" data-v2="theme">${night?'☀ 日间模式':'☾ 夜间模式'}</button>`+originalAuth().replace('准备充分，<br>自信发生。','下一次机会，<br>从容以对。').replace('THE NEXT CHAPTER STARTS HERE','ASTRAINTERVIEW / FOURTH EDITION')};
home=function(){return `<div class="workspace-heading"><div><div class="eyebrow">ASTRAINTERVIEW / PERSONAL STUDIO</div><h1>准备，从这里开始。</h1><p>把每一次对话，变成下一次的底气。</p></div><span class="edition-number">04 <small>FOURTH EDITION</small></span></div><div class="home-layout"><section class="interview-stage"><div class="stage-top"><span class="pill">${icon('phone')} TELEPHONE INTERVIEW</span><span class="stage-index">01 — PRACTICE</span></div><div class="stage-word" aria-hidden="true">面试空间</div><div class="tie-sculpture">${logo}<div class="pedestal"></div></div><div class="stage-copy"><div class="eyebrow">你的下一场，值得认真准备</div><h2>进入状态。<br>让实力被听见。</h2><p>从第一句自我介绍，到最后一次深度追问。<br>在真实场景中练习属于你的表达。</p><a class="primary" href="#phone">开始电话面试 <span>↗</span></a></div><div class="stage-bottom"><span>场景定制 / 多维复盘 / 持续进阶</span><span>AI INTERVIEW STUDIO</span></div></section><div class="side-features"><a class="feature-card" href="#portrait"><div class="feature-top"><span>02 / INSIGHTS</span>${icon('chart')}</div><div class="radar-mark" aria-hidden="true"><svg viewBox="0 0 180 100"><path d="M90 4 145 28 145 73 90 98 35 73 35 28Z M90 22 124 37 124 63 90 80 56 63 56 37Z"/><path class="radar-fill" d="M90 11 132 34 119 62 90 89 47 69 66 41Z"/></svg></div><h2>看见你的能力轮廓</h2><p>优势与短板，都有迹可循。</p><span class="feature-link">探索能力画像 <b>↗</b></span></a><a class="feature-card personal" href="#me"><div class="feature-top"><span>03 / ARCHIVE</span>${icon('user')}</div><div class="file-sculpture" aria-hidden="true">${icon('file')}</div><h2>积累，属于你的答案</h2><p>一份简历，每一场练习。</p><span class="feature-link">进入我的空间 <b>↗</b></span></a></div></div><div class="section-title"><h2>最近练习 <span> / 示例数据</span></h2><a href="#history">全部记录 ↗</a></div>${rows(demo)}`};
phone=function(){return title('CHOOSE YOUR PACE','选择一种方式，进入面试。','一次充分的准备，从适合你的难度开始。')+`<div class="cards difficulty-cards"><section class="card difficulty" tabindex="0"><div class="eyebrow">01 / GUIDED SESSION</div><div class="difficulty-symbol">${icon('phone')}</div><h2>默认难度设置</h2><p>让面试官带你进入状态。<br>从基础热身，到更有深度的对话。</p><button class="ghost" data-action="expand">选择难度 ↓</button><div class="options">${['简单','中等','困难'].map((v,i)=>`<button class="node" data-action="start" data-value="${v}"><small>0${i+1}</small> ${v} ↗</button>`).join('')}</div></section><a href="#custom" class="card difficulty heavy"><div class="eyebrow">02 / PRESSURE CHAMBER</div><div class="challenge-lines" aria-hidden="true">////</div><span class="challenge-label">挑战模式</span><h2>自主难度设置</h2><p>设定场景，直面追问。<br>把舒适区的边界，再推远一点。</p><div class="feature-link">构建专属挑战 <b>↗</b></div></a></div>`};
custom=function(){const done=Object.keys(selection).length;return `<button class="back" data-action="back" data-value="phone">← 返回难度选择</button>`+title('INTERVIEW NEURAL CONFIGURATOR','你的面试，由你定义。','选择经验层级，再依次设定五个维度。连线展示当前选择路径。')+`<div class="neural-board"><div class="neural-labels"><span>01 / 经验层级</span><span>02 / 配置维度</span><span>03 / 场景选项</span></div><div class="neural-columns"><svg class="neural-wires" viewBox="0 0 1000 440" preserveAspectRatio="none" aria-hidden="true">${[0,1,2,3,4].map(i=>`<path d="M215 ${55+Object.keys(config).indexOf(level)*100} C330 ${55+Object.keys(config).indexOf(level)*100},330 ${40+i*82},440 ${40+i*82}" class="${activeDimension===i?'lit':''}"/>`).join('')}${config[level][activeDimension].map((v,i)=>`<path class="${selection[activeDimension]===v?'lit':''}" d="M590 ${40+activeDimension*82} C710 ${40+activeDimension*82},710 ${50+i*94},805 ${50+i*94}"/>`).join('')}</svg><div class="neural-levels">${Object.keys(config).map((l,i)=>`<button class="network-node ${level===l?'chosen':''}" data-v2="level" data-value="${l}" aria-pressed="${level===l}"><small>0${i+1}</small>${l}<span>→</span></button>`).join('')}</div><div class="neural-dimensions">${categories.map((c,i)=>`<button class="network-node ${activeDimension===i?'focused':''} ${selection[i]?'complete':''}" data-v2="dimension" data-id="${i}" aria-pressed="${activeDimension===i}">${c}<span>${selection[i]?'✓':'+'}</span></button>`).join('')}</div><div class="neural-values">${config[level][activeDimension].map(v=>`<button class="network-node ${selection[activeDimension]===v?'chosen':''}" data-v2="value" data-value="${v}" aria-pressed="${selection[activeDimension]===v}">${v}<span>${selection[activeDimension]===v?'✓':'○'}</span></button>`).join('')}</div></div><div class="configuration-summary"><div><span class="eyebrow">YOUR CONFIGURATION / ${done} OF 5</span><div class="summary-tags">${categories.map((c,i)=>`<button data-v2="dimension" data-id="${i}">${c}<b>${selection[i]||'待选择'}</b></button>`).join('')}</div></div>${done===5?'<button class="primary dark" data-action="start" data-value="自主配置">开始面试 ↗</button>':'<span class="pending-label">完成五个维度后<br>即可开始面试</span>'}</div></div>`};
document.addEventListener('click',e=>{const b=e.target.closest('[data-v2]');if(!b)return;switch(b.dataset.v2){case'theme':night=!night;document.documentElement.dataset.theme=night?'night':'day';sessionStorage.setItem('astra-v2-theme',night?'night':'day');break;case'level':level=b.dataset.value;selection={};activeDimension=0;break;case'dimension':activeDimension=Number(b.dataset.id);break;case'value':selection[activeDimension]=b.dataset.value;break;}if(b.dataset.v2==='theme')render();else updateConfiguration();});
render();



