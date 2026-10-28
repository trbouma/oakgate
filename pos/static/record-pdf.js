import * as pdfjsLib from '/pdf-assets/pdf.mjs';
pdfjsLib.GlobalWorkerOptions.workerSrc='/pdf-assets/pdf.worker.mjs';
const $=id=>document.getElementById(id);
let generation=0, task, pdf, renderTask, pageNumber=1, busy=false;
function clear(){
 generation++;renderTask?.cancel();renderTask=null;
 if(task)void task.destroy().catch(()=>{});
 task=null;pdf=null;busy=false;pageNumber=1;
 $('record-pdf').hidden=true;$('record-pdf-pages').replaceChildren();
 $('record-pdf-status').textContent='';$('record-pdf-page').textContent='';$('record-pdf-controls').hidden=true;
}
function error(){
 $('record-pdf-pages').replaceChildren();$('record-pdf-controls').hidden=true;
 $('record-pdf-status').hidden=false;$('record-pdf-status').textContent='PDF preview unavailable.';
}
async function render(number, run){
 if(busy||!pdf)return;
 busy=true;$('record-pdf-previous').disabled=true;$('record-pdf-next').disabled=true;
 try{
  const page=await pdf.getPage(number);if(run!==generation)return;
  const natural=page.getViewport({scale:1});
  const width=Math.max(1,Math.min($('record-result').clientWidth || 480,800));
  // Bound canvas memory even for unusually tall or malformed documents.
  const scale=Math.min(width/natural.width,1600/natural.height);
  const viewport=page.getViewport({scale});
  const ratio=Math.min(2,window.devicePixelRatio || 1);
  const canvas=document.createElement('canvas');canvas.setAttribute('aria-label',`PDF page ${number}`);
  canvas.width=Math.ceil(viewport.width*ratio);canvas.height=Math.ceil(viewport.height*ratio);
  renderTask=page.render({canvasContext:canvas.getContext('2d',{alpha:false}),viewport,transform:[ratio,0,0,ratio,0,0]});
  await renderTask.promise;if(run!==generation)return;
  $('record-pdf-pages').replaceChildren(canvas);pageNumber=number;
  $('record-pdf-page').textContent=`Page ${number} of ${pdf.numPages}`;
  $('record-pdf-controls').hidden=pdf.numPages<=1;$('record-pdf-status').hidden=true;
 }catch(_){if(run===generation)error();}
 finally{if(run===generation){busy=false;renderTask=null;$('record-pdf-previous').disabled=pageNumber<=1;$('record-pdf-next').disabled=!pdf||pageNumber>=pdf.numPages;}}
}
async function show(encoded){
 clear();const run=generation;$('record-pdf').hidden=false;
 $('record-pdf-status').hidden=false;$('record-pdf-status').textContent='Loading PDF…';
 try{
  const data=Uint8Array.from(atob(encoded),c=>c.charCodeAt(0));
  task=pdfjsLib.getDocument({data,standardFontDataUrl:'/pdf-assets/standard_fonts/',isEvalSupported:false});
  const loaded=await task.promise;if(run!==generation)return;
  pdf=loaded;await render(1,run);
 }catch(_){if(run===generation)error();}
}
$('record-pdf-previous').addEventListener('click',()=>{if(pageNumber>1)void render(pageNumber-1,generation);});
$('record-pdf-next').addEventListener('click',()=>{if(pdf&&pageNumber<pdf.numPages)void render(pageNumber+1,generation);});
window.oakgatePOSPDF={show,clear};
