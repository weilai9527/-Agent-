// Render local PDF bytes instead of relying on a mobile browser's iframe viewer.
const pdfMounts=new Map();
if(window.pdfjsLib)pdfjsLib.GlobalWorkerOptions.workerSrc='vendor/pdfjs/build/pdf.worker.min.js';
resume=function(){return title('YOUR STORY, WELL PRESENTED','我的简历','整理经历，让每一份潜力被看见。')+`<div class="upload">${icon('file')}<h3>上传你的 PDF 简历</h3><p>本地预览 · 支持多页 PDF · 最大 10 MB</p><input type="file" id="pdf-upload" accept="application/pdf,.pdf" aria-label="上传 PDF 简历"></div>${resumes.length?resumes.map((r,i)=>`<section class="card resume-card"><details data-resume="${i}" ${i===0?'open':''}><summary><span>${esc(r.name)}</span><small>${esc(r.date)} · 点击展开或收起</small></summary><div class="resume-preview-tools"><span>按框架宽度适配 · 向下滚动查看全部页面</span><a href="${r.url}" target="_blank" rel="noopener">打开原文件 ↗</a></div><div class="pdf-pages" data-pdf="${i}" aria-label="${esc(r.name)} 全文预览"><p class="pdf-status" role="status">正在准备简历预览…</p></div><a class="primary dark" href="#analysis">简历分析 · 查看示例报告 ↗</a></details></section>`).join(''):'<div class="empty">还没有简历记录，上传第一份简历开始吧。</div>'}`};
function disposePdf(host,state){
  state.dead=true;state.resize?.disconnect();state.intersection?.disconnect();clearTimeout(state.timer);
  for(const page of state.pages)page.task?.cancel();
  state.loading?.destroy();pdfMounts.delete(host);
}
async function drawPdfPage(state,item){
  if(state.dead||!item.visible||!state.host.clientWidth)return;
  if(item.busy){item.again=true;return}
  const width=item.canvas.clientWidth||state.host.clientWidth;
  if(Math.abs(width-(item.width||0))<2&&item.drawn)return;
  item.busy=true;
  try{
    const raw=item.page.getViewport({scale:1});
    const ratio=Math.min(window.devicePixelRatio||1,2,Math.sqrt(2000000/(width*width*raw.height/raw.width)));
    const viewport=item.page.getViewport({scale:width/raw.width*ratio});
    item.canvas.width=Math.ceil(viewport.width);item.canvas.height=Math.ceil(viewport.height);
    item.task=item.page.render({canvasContext:item.canvas.getContext('2d'),viewport,background:'#ffffff'});
    await item.task.promise;item.width=width;item.drawn=true;item.canvas.classList.add('pdf-ready');
  }catch(error){if(!state.dead&&error.name!=='RenderingCancelledException'){item.note.textContent='此页渲染失败，请使用上方“打开原文件”查看。'}}
  finally{item.busy=false;item.task=null;if(item.again&&!state.dead){item.again=false;drawPdfPage(state,item)}}
}
async function mountPdf(host){
  const record=resumes[Number(host.dataset.pdf)];if(!record)return;
  const state={host,pages:[],dead:false};pdfMounts.set(host,state);
  try{
    if(!window.pdfjsLib)throw new Error('library');
    const bytes=record.file?await record.file.arrayBuffer():await(await fetch(record.url)).arrayBuffer();
    if(state.dead)return;
    state.loading=pdfjsLib.getDocument({data:new Uint8Array(bytes),isEvalSupported:false,cMapUrl:'vendor/pdfjs/cmaps/',cMapPacked:true,standardFontDataUrl:'vendor/pdfjs/standard_fonts/'});
    state.loading.onPassword=()=>{host.querySelector('.pdf-status').textContent='此 PDF 需要密码。请上传不加密的版本，或点击“打开原文件”查看。';state.loading.destroy()};
    const pdf=await state.loading.promise;if(state.dead)return;
    host.querySelector('.pdf-status').textContent=`共 ${pdf.numPages} 页 · 已按框架宽度适配`;
    if(window.IntersectionObserver)state.intersection=new IntersectionObserver(entries=>{for(const entry of entries){const item=state.pages.find(p=>p.canvas===entry.target);if(item){item.visible=entry.isIntersecting;if(item.visible)drawPdfPage(state,item)}}},{rootMargin:'300px'});
    for(let index=1;index<=pdf.numPages;index++){
      const page=await pdf.getPage(index);if(state.dead)return;
      const viewport=page.getViewport({scale:1});
      const figure=document.createElement('figure'),canvas=document.createElement('canvas'),note=document.createElement('figcaption');
      figure.className='pdf-sheet';canvas.setAttribute('role','img');canvas.setAttribute('aria-label',`${record.name} 第 ${index} 页`);
      canvas.style.aspectRatio=`${viewport.width} / ${viewport.height}`;
      note.textContent=`第 ${index} / ${pdf.numPages} 页`;figure.append(canvas,note);host.append(figure);
      const item={page,canvas,note,visible:!state.intersection};state.pages.push(item);
      if(state.intersection)state.intersection.observe(canvas);else await drawPdfPage(state,item);
    }
    if(window.ResizeObserver){state.resize=new ResizeObserver(()=>{clearTimeout(state.timer);state.timer=setTimeout(()=>{for(const item of state.pages)drawPdfPage(state,item)},140)});state.resize.observe(host)}
  }catch(error){if(!state.dead){const status=host.querySelector('.pdf-status');if(status&&!status.textContent.includes('密码'))status.textContent='暂时无法预览此 PDF，请重新上传有效文件，或使用上方“打开原文件”查看。'}}
}
function syncPdfViewers(){
  for(const [host,state] of pdfMounts)if(!host.isConnected)disposePdf(host,state);
  document.querySelectorAll('details[open] .pdf-pages').forEach(host=>{if(!pdfMounts.has(host))mountPdf(host)});
}
document.addEventListener('change',e=>{
  if(e.target.id!=='pdf-upload')return;e.stopImmediatePropagation();
  const file=e.target.files[0];if(!file)return;
  if(!file.name.toLowerCase().endsWith('.pdf')||file.size>10*1024*1024){toast('请选择不超过 10 MB 的 PDF 文件。');e.target.value='';return}
  resumes.unshift({name:file.name,date:new Date().toLocaleDateString('zh-CN'),url:URL.createObjectURL(file),file});render();
},true);
document.addEventListener('toggle',syncPdfViewers,true);
new MutationObserver(syncPdfViewers).observe(app,{childList:true,subtree:true});
window.addEventListener('beforeunload',()=>{for(const [host,state] of pdfMounts)disposePdf(host,state)});
render();syncPdfViewers();
