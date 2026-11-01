const $=id=>document.getElementById(id);
let lang=localStorage.getItem('lumascanLanguage')||'de';$('language').value=lang;
const tr=(de,en)=>lang==='en'?en:de;
const translations={saved:'saved',start:'Start camera',manual:'Scan now',auto:'Automatic',torch:'Light',review:'Accept capture anyway',hint:'Lay originals flat and hold the camera steady. Wait for the green check before replacing them. Mat optional.'};
if(lang==='en')for(const e of document.querySelectorAll('[data-i]'))e.textContent=translations[e.dataset.i];
$('language').onchange=()=>{localStorage.setItem('lumascanLanguage',$('language').value);location.reload();};
let token=sessionStorage.getItem('lumascanDevice')||'',stream=null,busy=false,timer=null,last=null;
const frame=document.createElement('canvas');
async function api(path,options={}){const r=await fetch('/api/'+path,{...options,headers:{Authorization:'Bearer '+token,...options.headers}});if(!r.ok){const e=await r.json().catch(()=>({}));throw new Error(e.detail||'Connection failed');}return r.json();}
function display(state,text,progress=0){$('feedback').className=state;$('message').textContent=text;$('icon').textContent=state==='saved'?'✓':state==='processing'?'◌':state==='review'?'!':state==='error'?'×':'○';$('progress').value=progress;}
function receipt(result){
  $('count').textContent=result.saved_items??$('count').textContent;
  $('collection').textContent=result.collection||'';
  const r=result.receipt;if(!r)return;
  if(r.state==='saved'){display('saved',tr('Gesichert. Nächste Vorlage auflegen.','Saved. Place the next original.'),1);$('review').hidden=true;$('error').textContent='';}
  if(r.state==='processing')display('processing',tr('Wird verarbeitet und gespeichert …','Processing and saving…'),r.progress||0);
  if(r.state==='review'){display('review',tr('Bitte Aufnahme am Computer prüfen.','Review this capture at the computer.'),1);$('error').textContent=r.reasons.join(', ');$('review').hidden=false;}
  if(r.state==='error'){display('error',tr('Nicht abgeschlossen. Am Computer prüfen.','Not completed. Check at the computer.'));$('error').textContent=r.message;}
}
async function picture(preview=false){
  const video=$('video'),track=stream.getVideoTracks()[0];
  if(!preview&&window.ImageCapture){try{return {blob:await new ImageCapture(track).takePhoto(),source:'camera-original'};}catch{}}
  const scale=preview?Math.min(1,1280/Math.max(video.videoWidth,video.videoHeight)):1;frame.width=Math.round(video.videoWidth*scale);frame.height=Math.round(video.videoHeight*scale);frame.getContext('2d').drawImage(video,0,0,frame.width,frame.height);
  const blob=await new Promise((resolve,reject)=>frame.toBlob(b=>b?resolve(b):reject(new Error('Camera capture failed')),'image/jpeg',preview?.85:.98));return {blob,source:'video-frame'};
}
async function capture(intent){
  busy=true;display('processing',tr('Aufnahme wird übertragen …','Uploading capture…'));
  try{const p=await picture();const form=new FormData();form.append('file',p.blob,p.blob.type==='image/png'?'camera.png':'camera.jpg');form.append('intent_id',intent);form.append('source',p.source);await api('device/capture',{method:'POST',body:form});}
  finally{busy=false;}
}
function overlay(d){const c=$('overlay');c.width=d.width;c.height=d.height;const ctx=c.getContext('2d');ctx.strokeStyle='#6bd8a2';ctx.lineWidth=Math.max(2,d.width/450);for(const q of d.quads){ctx.beginPath();q.forEach((p,i)=>i?ctx.lineTo(...p):ctx.moveTo(...p));ctx.closePath();ctx.stroke();}}
async function tick(){
  try{
    if(!stream||busy||document.hidden)return;
    const p=await picture(true),form=new FormData();form.append('file',p.blob,'preview.jpg');const r=await api('device/preview',{method:'POST',body:form});last=r;receipt(r);if(r.detection)overlay(r.detection);
    if(r.state==='capture'){if($('auto').checked)await capture(r.intent_id);else display('steady',tr('Bereit. Jetzt scannen drücken.','Ready. Press Scan now.'),1);}
    else if(['empty','moving','focus','steady'].includes(r.state)){const labels={empty:tr('Vorlage auflegen.','Place an original.'),moving:tr('Kurz ruhig halten.','Hold steady.'),focus:tr('Fokus prüfen.','Check focus.'),steady:tr('Vorlage erkannt. Ruhig halten …','Original detected. Hold steady…')};display(r.state,labels[r.state],r.progress);}
  }catch(e){$('error').textContent=e.message;display('error',tr('Verbindung oder Aufnahme prüfen.','Check connection or capture.'));}
  finally{if(stream)timer=setTimeout(tick,500);}
}
$('start').onclick=async()=>{try{if(!stream){stream=await navigator.mediaDevices.getUserMedia({video:{facingMode:'environment',width:{ideal:3840},height:{ideal:2160}},audio:false});$('video').srcObject=stream;await $('video').play();$('manual').disabled=false;$('start').disabled=true;const track=stream.getVideoTracks()[0];$('torch').disabled=!track.getCapabilities?.().torch;const settings=track.getSettings();$('quality').textContent=`${settings.width} × ${settings.height} px · `+tr('Browseraufnahme; native Kamera kann mehr Detail liefern.','Browser capture; native camera can provide more detail.');void tick();}}catch(e){$('error').textContent=e.message;}};
$('manual').onclick=async()=>{try{if(busy)return;const intent=await api('device/intent',{method:'POST'});await capture(intent.intent_id);}catch(e){$('error').textContent=e.message;}};
$('torch').onclick=async()=>{const track=stream.getVideoTracks()[0];try{await track.applyConstraints({advanced:[{torch:!track.getSettings().torch}]});}catch(e){$('error').textContent=e.message;}};
$('review').onclick=async()=>{try{receipt(await api('device/review',{method:'POST'}));}catch(e){$('error').textContent=e.message;}};
window.addEventListener('beforeunload',()=>{clearTimeout(timer);stream?.getTracks().forEach(t=>t.stop());});
async function initialize(){const code=new URLSearchParams(location.hash.slice(1)).get('pair');if(code){const r=await api('pair/claim',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({code})});token=r.token;sessionStorage.setItem('lumascanDevice',token);history.replaceState(null,'',location.pathname);}receipt(await api('device/state'));display('empty',tr('Bereit. Kamera starten.','Ready. Start camera.'));}
initialize().catch(e=>{$('error').textContent=e.message;display('error',tr('Am Computer neu koppeln.','Pair again at the computer.'));});
