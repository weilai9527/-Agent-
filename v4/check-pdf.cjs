const fs=require('node:fs'),assert=require('node:assert/strict');
const pdfjs=require('./vendor/pdfjs/build/pdf.min.js');
pdfjs.GlobalWorkerOptions.workerSrc=require.resolve('./vendor/pdfjs/build/pdf.worker.min.js');
(async()=>{
 const filename=process.argv[2];if(!filename)throw new Error('Pass a PDF file path');
 const task=pdfjs.getDocument({data:new Uint8Array(fs.readFileSync(filename)),isEvalSupported:false,cMapUrl:__dirname+'/vendor/pdfjs/cmaps/',cMapPacked:true,standardFontDataUrl:__dirname+'/vendor/pdfjs/standard_fonts/'});
 const doc=await task.promise;
 for(let n=1;n<=doc.numPages;n++){
  const page=await doc.getPage(n),raw=page.getViewport({scale:1});
  assert(raw.width>0&&raw.height>0);
  const operators=await page.getOperatorList();assert(operators.fnArray.length>0);
  for(const width of [252,307,322,346,382,700]){
   const ratio=Math.min(2,Math.sqrt(2000000/(width*width*raw.height/raw.width)));
   const viewport=page.getViewport({scale:width/raw.width*ratio});
   assert(Math.abs(viewport.width/ratio-width)<.01);
   assert(viewport.width*viewport.height<=2000001);
  }
 }
 console.log(`PASS: real PDF decoded (${doc.numPages} pages), 6 preview widths, proportional fit and bounded canvas resolution.`);
 await task.destroy();
})().catch(e=>{console.error(e);process.exitCode=1});
