const {test}=require('node:test');
const assert=require('node:assert/strict');
const {spawnSync}=require('node:child_process');
const path=require('node:path');
const {pathToFileURL}=require('node:url');
const library=pathToFileURL(path.resolve('app/static/pdf.mjs')).href;
const worker=pathToFileURL(path.resolve('app/static/pdf.worker.mjs')).href;
for(const missing of [false,true]) test(`real PDF library and worker load a document (${missing?'Chrome 138 missing methods':'native methods'})`,()=>{
 const result=spawnSync(process.execPath,['--input-type=module','-e',`
 import assert from 'node:assert/strict';
 if(${missing}){delete Uint8Array.prototype.toHex;delete Uint8Array.prototype.toBase64;delete Uint8Array.fromBase64;}
 const nativeHex=Uint8Array.prototype.toHex;
 // Parsing does not use canvas; these placeholders avoid Node-only canvas dependencies.
 globalThis.DOMMatrix=class DOMMatrix {};
 globalThis.ImageData=class ImageData {};
 globalThis.Path2D=class Path2D {};
 const pdfjs=await import(${JSON.stringify(library)});
 pdfjs.GlobalWorkerOptions.workerSrc=${JSON.stringify(worker)};
 assert.equal(pdfjs.version,'5.4.624');
 if(nativeHex)assert.equal(Uint8Array.prototype.toHex,nativeHex);
 const bytes=new Uint8Array([0,1,127,128,255]);
 assert.equal(bytes.toHex(),'00017f80ff');
 assert.equal(bytes.toBase64(),'AAF/gP8=');
 assert.deepEqual(Uint8Array.fromBase64(bytes.toBase64()),bytes);
 const document='%PDF-1.4\\n1 0 obj\\n<< /Type /Catalog /Pages 2 0 R >>\\nendobj\\n2 0 obj\\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\\nendobj\\n3 0 obj\\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 200 100] >>\\nendobj\\ntrailer\\n<< /Root 1 0 R >>\\n%%EOF';
 const task=pdfjs.getDocument({data:new TextEncoder().encode(document),isEvalSupported:false});
 try{
  const pdf=await task.promise;
  assert.equal(pdf.numPages,1);
  assert.match(pdf.fingerprints[0],/^[a-f0-9]{32}$/);
  const page=await pdf.getPage(1);
  assert.equal(page.getViewport({scale:1}).width,200);
  await page.getOperatorList();
 }finally{await task.destroy();}
 `],{encoding:'utf8',timeout:20000});
 assert.equal(result.status,0,result.stdout+'\n'+result.stderr);
});

test('worker installs compatibility methods in its own isolated realm',()=>{
 const result=spawnSync(process.execPath,['--input-type=module','-e',`
  import assert from 'node:assert/strict';
  delete Uint8Array.prototype.toHex;delete Uint8Array.prototype.toBase64;delete Uint8Array.fromBase64;
  await import(${JSON.stringify(worker)});
  assert.equal(new Uint8Array([0,255]).toHex(),'00ff');
  assert.equal(new Uint8Array([0,255]).toBase64(),'AP8=');
  assert.deepEqual([...Uint8Array.fromBase64('AP8=')],[0,255]);
 `],{encoding:'utf8',timeout:20000});
 assert.equal(result.status,0,result.stdout+'\n'+result.stderr);
});
