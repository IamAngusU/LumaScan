import {CaptureGate} from '/scan-auto.mjs';
import {receiveFiles,LABEL} from '/luma-transfer.js';

const $=id=>document.getElementById(id);
let lang=localStorage.getItem('lumascanLanguage')||localStorage.getItem('keyringLanguage')||'de';
const en={brandSub:'Photos & documents',objects:'API',language:'Language',title:'Place. Capture. Preserve.',subtitle:'Photographs, Polaroids and documents. One or several at a time.',mat:'Print A4 capture mat',destination:'Save following captures to',session:'Collection',newSession:'New collection',connect:'Connect iPhone',localCamera:'Camera on this device',upload:'Open photographs',noCamera:'No camera connected',emptyTitle:'Your originals, in view.',emptyText:'Connect a camera or open images. Detected borders appear directly in the image.',nothing:'No items detected',auto:'Automatic',capture:'Digitise now',manualHint:'Capture manually or enable automatic capture.',detectAgain:'Detect borders again',manual:'Add four corners',whole:'Whole image',clear:'Clear selection',torch:'Light',cropHint:'Drag corners to adjust. Click an item to select it; Delete removes it. Polaroid borders are preserved.',saved:'Saved in this collection',processing:'Processing',look:'Image treatment',original:'Original colours',photo:'Refresh photograph',mono:'Restore black-and-white photo',gray:'Grayscale',document:'Document · black and white',ocr:'Text recognition (OCR)',orient:'Automatically orient text',originalHint:'The original and perspective crop are retained. Edits are saved as additional versions.',guide:'For good digitisations',guideText:'Lay originals flat with space between them. Keep the camera perpendicular and avoid reflections. Use close-ups for small photographs. The mat is optional; white borders are hard to detect on white.',matHint:'The mat offers 152 × 232 mm. For A4 and larger originals use a contrasting table without the mat. Separate overlapping items.',autoHint:'Automatic capture waits for steady, sharp items. Briefly clear the surface or capture manually to scan the same photo again.',phoneHint:'On iPhone/iPad: download the ZIP or use Share to save in Files. Safari does not support continuous access to an arbitrary folder.',recent:'Your digitisations',refresh:'Refresh',privacy:'Processing and archive stay local. Direct phone capture over Wi-Fi.',pairTitle:'Your iPhone as a scanner',pairHint:'Open the QR code and start the camera. Wait for the green check before replacing an original.',sender:'Open phone camera',existing:'Resume an existing LumaDrop pairing code',resume:'Use code',serverTitle:'Folder on the server computer',serverHint:'Enter the full folder path. New folders are created. Following captures use this destination.',cancel:'Cancel',activate:'Activate folder',editTitle:'Edit photograph',editHint:'Original on the left, new version on the right. Mark scratches on the left crop; “Create version” calculates the repair.',source:'Perspective crop',version:'Edited version',brush:'Mark scratches',radius:'Brush',undoStroke:'Remove last stroke',rotate:'Rotate 90°',makeVersion:'Create version',repairHint:'Small scratches are filled from their surroundings. Missing image parts and historical colours cannot be reliably reconstructed this way.',downloadVersion:'Download version'};
const tr=(de,english)=>lang==='en'?english:de;
document.documentElement.lang=lang;
$('language').value=lang;
for(const el of document.querySelectorAll('[data-i]'))if(lang==='en'&&en[el.dataset.i])el.textContent=en[el.dataset.i];
$('matLink').href='/print/lumascan-a4-v1.pdf?language='+lang;
$('editMode').replaceChildren(...[...$('treatment').options].map(x=>x.cloneNode(true)));
$('language').onchange=()=>{localStorage.setItem('lumascanLanguage',$('language').value);location.reload();};
let token=sessionStorage.getItem('lumascanToken')||'';
const fragment=new URLSearchParams(location.hash.slice(1));
if(fragment.has('token')){token=fragment.get('token');sessionStorage.setItem('lumascanToken',token);history.replaceState(null,'',location.pathname);}
let session=null,status=null,sessions=[],peer=null,link=null,call=null,dispose=null,remote={},generation=0;
let quads=[],points=[],manual=false,adding=false,selected=-1,drag=null,currentFile=null,stillUrl=null;
let sw=0,sh=0,analysis=null,folderHandle=null,lastDestination='archive',pending=null,submitting=false;
let polling=false,pollTimer=null,browserSaved=new Set(),activeUrls=[],thumbUrls=[];
const gate=new CaptureGate();
const ctx=$('overlay').getContext('2d');
function notice(message){$('notice').textContent=message;$('notice').hidden=false;clearTimeout(notice.timer);notice.timer=setTimeout(()=>$('notice').hidden=true,12000);}
async function api(path,opts={}){
  const response=await fetch(path,{...opts,headers:{Authorization:`Bearer ${token}`,...opts.headers}});
  if(!response.ok){const error=await response.json().catch(()=>({}));throw new Error(typeof error.detail==='string'?error.detail:`${response.status}: ${tr('Anfrage fehlgeschlagen','Request failed')}`);}
  return response;
}
const json=async(path,opts)=>(await api(path,opts)).json();
const post=(path,data)=>json(path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});
const on=(id,event,fn)=>$(id).addEventListener(event,async e=>{try{await fn(e);}catch(error){notice(error.message);}});
const sidPath=sid=>`/api/digitize/sessions/${sid}`;
const jobPath=(sid,jid)=>`${sidPath(sid)}/jobs/${jid}`;
const filePath=(sid,jid,name)=>`${jobPath(sid,jid)}/files/${name}`;
function id(){return crypto.randomUUID().replaceAll('-','');}
function settings(){return {destination:$('destination').value,mode:$('treatment').value,ocr:$('ocr').checked,orient:$('orient').checked,request_id:id(),source:'library',detect:true,quads:[]};}
function snapshot(){return {sid:session.id,options:settings(),handle:folderHandle,quads:manual?quads.map(q=>q.map(p=>p.slice())):[],width:sw,height:sh};}
function source(){return currentFile?$('still'):$('video');}
async function blobOfSource(max=Infinity){
  if(!sw||!sh)throw new Error(tr('Zuerst Kamera verbinden oder Foto öffnen.','Connect a camera or open an image first.'));
  const c=document.createElement('canvas'),scale=Math.min(1,max/Math.max(sw,sh));c.width=Math.round(sw*scale);c.height=Math.round(sh*scale);c.getContext('2d').drawImage(source(),0,0,c.width,c.height);
  return new Promise(resolve=>c.toBlob(resolve,'image/jpeg',.97));
}
async function inspectBlob(blob){const form=new FormData();form.append('file',blob,'inspect.jpg');return json('/api/digitize/inspect',{method:'POST',body:form});}
function updateSource(){
  sw=currentFile?$('still').naturalWidth:$('video').videoWidth;sh=currentFile?$('still').naturalHeight:$('video').videoHeight;
  $('empty').hidden=Boolean(sw);$('overlay').hidden=!sw;$('overlay').width=sw||1;$('overlay').height=sh||1;
  $('capture').disabled=!sw||submitting;draw();
}
function draw(){
  ctx.clearRect(0,0,sw,sh);const scale=Math.max(sw/900,1);
  for(const marker of analysis?.markers||[])polygon(marker.points,'#269870',1.3*scale,false);
  quads.forEach((q,i)=>{
    const color=i===selected?'#e7a52c':'#227ce1';polygon(q,color,2*scale,true);
    q.forEach(p=>{ctx.beginPath();ctx.arc(...p,5*scale,0,Math.PI*2);ctx.fillStyle='white';ctx.fill();ctx.strokeStyle=color;ctx.stroke();});
    ctx.font=`600 ${17*scale}px Segoe UI`;ctx.fillStyle=color;ctx.fillRect(q[0][0],q[0][1]-25*scale,30*scale,25*scale);ctx.fillStyle='white';ctx.fillText(String(i+1),q[0][0]+7*scale,q[0][1]-6*scale);
  });
  points.forEach(p=>{ctx.fillStyle='#e7a52c';ctx.beginPath();ctx.arc(...p,6*scale,0,7);ctx.fill();});
  $('detected').textContent=quads.length?tr(`${quads.length} Vorlage${quads.length===1?'':'n'} erkannt`,`${quads.length} item${quads.length===1?'':'s'} detected`):tr('Keine Vorlagen erkannt','No items detected');
  $('quality').textContent=analysis?tr(`${analysis.mat?'Matte erkannt · ':''}Schärfe ${analysis.sharpness.toFixed(0)}${manual?' · manuell korrigiert':''}`,`${analysis.mat?'Mat detected · ':''}Sharpness ${analysis.sharpness.toFixed(0)}${manual?' · adjusted manually':''}`):'';
}
function polygon(q,color,width,fill){ctx.beginPath();q.forEach((p,i)=>i?ctx.lineTo(...p):ctx.moveTo(...p));ctx.closePath();ctx.strokeStyle=color;ctx.lineWidth=width;if(fill){ctx.fillStyle=color;ctx.globalAlpha=.07;ctx.fill();ctx.globalAlpha=1;}ctx.stroke();}
function position(event,canvas=$('overlay')){
  const rect=canvas.getBoundingClientRect(),w=canvas.width,h=canvas.height,scale=Math.min(rect.width/w,rect.height/h),left=rect.left+(rect.width-w*scale)/2,top=rect.top+(rect.height-h*scale)/2;
  return [Math.max(0,Math.min(w-1,(event.clientX-left)/scale)),Math.max(0,Math.min(h-1,(event.clientY-top)/scale))];
}
$('overlay').tabIndex=0;
on('overlay','pointerdown',e=>{
  $('overlay').focus();const p=position(e),threshold=sw/45;
  if(adding){points.push(p);if(points.length===4){quads.push(points);points=[];adding=false;selected=quads.length-1;}draw();return;}
  let closest=null;
  quads.forEach((q,i)=>q.forEach((v,k)=>{const distance=Math.hypot(v[0]-p[0],v[1]-p[1]);if(distance<threshold&&(!closest||distance<closest.distance))closest={i,k,distance};}));
  if(closest){drag=closest;manual=true;$('overlay').setPointerCapture(e.pointerId);return;}
  selected=quads.findIndex(q=>{const xs=q.map(p=>p[0]),ys=q.map(p=>p[1]);return p[0]>=Math.min(...xs)&&p[0]<=Math.max(...xs)&&p[1]>=Math.min(...ys)&&p[1]<=Math.max(...ys);});
  if(manual&&selected<0){points=[p];}draw();
});
on('overlay','pointermove',e=>{if(drag){quads[drag.i][drag.k]=position(e);selected=drag.i;draw();}});
on('overlay','pointerup',()=>drag=null);on('overlay','pointercancel',()=>drag=null);
on('overlay','keydown',e=>{if(e.key==='Delete'&&selected>=0){quads.splice(selected,1);selected=-1;manual=true;draw();}});
on('manual','click',()=>{if(!sw)return;manual=true;adding=true;points=[];selected=-1;notice(tr('Vier Ecken im Uhrzeigersinn anklicken.','Click four corners clockwise.'));});
on('whole','click',()=>{manual=true;adding=false;points=[];quads=[[[0,0],[sw-1,0],[sw-1,sh-1],[0,sh-1]]];draw();});
on('clearQuads','click',()=>{manual=true;adding=false;points=[];quads=[];draw();});
on('detectAgain','click',async()=>{manual=false;adding=false;points=[];await inspectCurrent();});
async function inspectCurrent(){if(!sw)return;const result=await inspectBlob(await blobOfSource(1280));analysis={...result,markers:result.markers.map(m=>({...m,points:m.points.map(([x,y])=>[x*sw/result.width,y*sh/result.height])}))};if(!manual)quads=result.quads.map(q=>q.map(([x,y])=>[x*sw/result.width,y*sh/result.height]));draw();return result;}
function pixels(){
  const c=document.createElement('canvas');c.width=128;c.height=128;const cctx=c.getContext('2d'),values=[];
  // Compare the originals themselves. A changed line on a similar document must
  // not disappear into the average colour of a large empty table.
  for(const q of quads){const xs=q.map(p=>p[0]),ys=q.map(p=>p[1]),x=Math.min(...xs),y=Math.min(...ys);cctx.drawImage(source(),x,y,Math.max(...xs)-x,Math.max(...ys)-y,0,0,128,128);const d=cctx.getImageData(0,0,128,128).data;for(let i=0;i<d.length;i+=4)values.push((d[i]+d[i+1]+d[i+2])/3);}
  return values;
}
function startLoop(){
  const gen=++generation;
  async function tick(){
    try{
      if(gen!==generation||currentFile||!$('video').srcObject)return;
      if(!document.hidden&&sw&&!pending&&!submitting){
        await inspectCurrent();if(gen!==generation)return;
        const observed=gate.observe({pixels:pixels(),count:quads.length,sharpness:analysis.sharpness,time:performance.now()});
        $('stability').value=observed.progress;
        const states={empty:tr('Vorlagen auflegen.','Place originals on the surface.'),pending:tr('Foto wird übertragen.','Transferring photograph.'),blur:tr('Noch unscharf. Kamera fokussieren lassen.','Still blurry. Let the camera focus.'),moving:tr('Bewegung erkannt. Kurz ruhig halten.','Movement detected. Hold steady.'),saved:tr('Bereits gesichert. Vorlagen austauschen.','Already saved. Replace the originals.'),steady:tr('Ruhig erkannt. Aufnahme wird vorbereitet.','Steady. Preparing capture.'),capture:tr('Aufnahme wird ausgelöst …','Capturing…')};
        $('autoStatus').textContent=$('auto').checked?states[observed.state]:tr('Manuell auslösen oder Automatik aktivieren.','Capture manually or enable automatic capture.');
        if(observed.trigger){if($('auto').checked)await trigger(true);else gate.failed();}
      }
    }catch(error){gate.failed();$('autoStatus').textContent=error.message;}
    finally{if(gen===generation)setTimeout(tick,550);}
  }void tick();
}
function stopSource(){
  generation++;pending&&clearTimeout(pending.timer);pending=null;gate.reset();
  dispose?.();dispose=null;link?.close();call?.close();peer?.destroy();peer=null;link=null;call=null;remote={};
  $('video').srcObject?.getTracks().forEach(t=>t.stop());$('video').srcObject=null;$('video').hidden=true;
  currentFile=null;sw=0;sh=0;analysis=null;quads=[];points=[];manual=false;adding=false;selected=-1;drag=null;$('still').hidden=true;if(stillUrl)URL.revokeObjectURL(stillUrl);stillUrl=null;remoteUI();updateSource();
}
async function openFile(file){
  stopSource();currentFile=file;stillUrl=URL.createObjectURL(file);$('still').src=stillUrl;
  try{await $('still').decode();}catch{
    const form=new FormData();form.append('file',file,file.name);const preview=await(await api('/api/digitize/preview',{method:'POST',body:form})).blob();
    URL.revokeObjectURL(stillUrl);stillUrl=URL.createObjectURL(preview);$('still').src=stillUrl;await $('still').decode();
  }
  $('still').hidden=false;updateSource();await inspectCurrent();$('sourceStatus').textContent=file.name;
}
on('files','change',async()=>{
  const files=[...$('files').files];if(files.length>30)throw new Error(tr('Höchstens 30 Dateien pro Auswahl.','At most 30 files at a time.'));
  if(files.length===1)await openFile(files[0]);
  else if(files.length){const snap=snapshot();for(const file of files)await submit(file,{...snap,options:{...snap.options,request_id:id()},quads:[]});}
  $('files').value='';
});
on('localCamera','click',async()=>{
  stopSource();$('video').srcObject=await navigator.mediaDevices.getUserMedia({video:{facingMode:'environment',width:{ideal:3840},height:{ideal:2160}},audio:false});$('video').hidden=false;await $('video').play();updateSource();$('sourceStatus').textContent=tr('Lokale Kamera · Videobild','Local camera · video frame');startLoop();
});
on('video','loadedmetadata',updateSource);
async function syncPhoneSettings(){
  if(!session)return;
  if($('destination').value==='server')return;
  const options=settings();options.destination=['browser','server'].includes(options.destination)?'archive':options.destination;
  await json(sidPath(session.id)+'/settings',{method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify(options)});
}
async function connect(){
  await syncPhoneSettings();
  const pair=await post(sidPath(session.id)+'/pair',{});
  $('qr').src=pair.qr_data_url;$('sender').href=pair.url;
  $('pairStatus').textContent=tr('Im gleichen WLAN öffnen. Code gilt zehn Minuten.','Open on the same Wi-Fi. Code expires in ten minutes.');
}
on('connect','click',async()=>{$('pair').showModal();await connect();});
on('resume','click',async()=>{const value=$('existingPeer').value.trim();if(!/^[A-Za-z0-9-]{1,128}$/.test(value))throw new Error(tr('Kopplungscode prüfen.','Check pairing code.'));await connect(value);});
function remoteUI(){
  $('torch').disabled=!link?.open||!remote.remote||!remote.torch;
  $('zoomLabel').hidden=!remote.zoom||!remote.remote;
  if(remote.zoom){$('zoom').min=remote.zoom.min;$('zoom').max=remote.zoom.max;$('zoom').step=remote.zoom.step||.1;$('zoom').value=remote.settings?.zoom||1;}
}
on('torch','click',()=>link?.send({type:'camera-command',action:'torch',value:!remote.settings?.torch}));
on('zoom','change',()=>{gate.failed();link?.send({type:'camera-command',action:'zoom',value:Number($('zoom').value)});});
on('auto','change',()=>{gate.failed();if(currentFile&&$('auto').checked){$('auto').checked=false;notice(tr('Automatik braucht eine Live-Kamera.','Automatic mode needs a live camera.'));}});
on('ocr','change',()=>$('orient').disabled=!$('ocr').checked);
async function trigger(automatic=false){
  if(pending||submitting)return;
  if(!session)throw new Error(tr('Sammlung anlegen.','Create a collection.'));
  const snap=snapshot();
  if(currentFile){if(!quads.length)throw new Error(tr('Ränder erkennen oder ganzes Bild wählen.','Detect borders or choose whole image.'));snap.quads=quads.map(q=>q.map(p=>p.slice()));snap.options.detect=false;await submit(currentFile,snap,currentFile.name);return;}
  if(link?.open&&remote.remote){
    pending={snapshot:snap,timer:setTimeout(()=>{pending=null;gate.failed();notice(tr('Foto nicht angekommen. Verbindung prüfen und erneut auslösen.','Photograph did not arrive. Check connection and capture again.'));},90000)};
    link.send({type:'camera-command',action:'capture'});
  }else{
    snap.options.source='video-frame';await submit(await blobOfSource(),snap,'camera-frame.jpg');gate.committed();
    if(!automatic)notice(tr('Videobild gesichert. Für mehr Detail Originalfotos übertragen.','Video frame saved. Transfer original photographs for more detail.'));
  }
}
on('capture','click',()=>trigger());
async function submit(blob,snap,name='capture.jpg'){
  submitting=true;$('capture').disabled=true;
  try{
    const options={...snap.options,destination:['browser','server'].includes(snap.options.destination)?'archive':snap.options.destination};
    if(snap.quads.length){const image=await inspectBlob(blob);options.quads=snap.quads.map(q=>q.map(([x,y])=>[x*(image.width-1)/Math.max(1,snap.width-1),y*(image.height-1)/Math.max(1,snap.height-1)]));options.detect=false;}
    const form=new FormData();form.append('file',blob,name);form.append('options',JSON.stringify(options));
    const job=await json(sidPath(snap.sid)+'/capture',{method:'POST',body:form});
    if(snap.handle)browserTargets.set(job.id,{handle:snap.handle,sid:snap.sid});
    if(session?.id===snap.sid)await refresh();
    schedulePoll();
  }catch(e){gate.failed();throw e;}finally{submitting=false;$('capture').disabled=!sw;}
}
const browserTargets=new Map();
function renderDestinations(){
  const select=$('destination'),value=lastDestination;select.replaceChildren();
  const add=(id,text)=>{const option=document.createElement('option');option.value=id;option.textContent=text;select.append(option);};
  add('archive',tr('Lokales LumaScan-Archiv','Local LumaScan archive'));
  for(const d of status?.destinations||[])add(d.id,d.path);
  add('browser',folderHandle?tr(`Dieses Gerät: ${folderHandle.name}`,`This device: ${folderHandle.name}`):tr('Ordner auf diesem Gerät wählen …','Choose folder on this device…'));
  add('server',tr('PC-/Serverordner hinzufügen …','Add folder on server computer…'));select.value=value;
  $('destinationNote').textContent=value==='browser'?tr('Direkt im gewählten Geräteordner; zusätzlich im lokalen Archiv.','Saved directly to the selected device folder and the local archive.'):value==='archive'?tr('Im lokalen Archiv. ZIP, PNG, PDF und Text jederzeit herunterladen.','In the local archive. Download ZIP, PNG, PDF and text at any time.'):tr('Zielordner gilt ab der nächsten Aufnahme. Laufende Aufnahmen behalten ihr Ziel.','Destination applies to the next capture. Pending captures keep their destination.');
}
on('destination','change',async()=>{
  if($('destination').value==='server'){$('folderDialog').showModal();$('folderPath').focus();return;}
  if($('destination').value==='browser'){
    if(!window.showDirectoryPicker){$('destination').value=lastDestination;throw new Error(tr('Dieser Browser unterstützt keine dauerhafte Ordnerauswahl. ZIP herunterladen oder über Teilen in Dateien sichern.','This browser cannot grant continuous folder access. Download the ZIP or use Share to save in Files.'));}
    try{folderHandle=await window.showDirectoryPicker({mode:'readwrite'});}catch(e){$('destination').value=lastDestination;if(e.name!=='AbortError')throw e;return;}
  }
  lastDestination=$('destination').value;renderDestinations();
});
on('folderCancel','click',()=>{$('folderDialog').close();$('destination').value=lastDestination;});
on('folderDialog','cancel',()=>$('destination').value=lastDestination);
on('folderForm','submit',async e=>{e.preventDefault();const d=await post('/api/digitize/destinations',{path:$('folderPath').value});status.destinations=status.destinations.filter(x=>x.id!==d.id);status.destinations.push(d);lastDestination=d.id;renderDestinations();$('folderDialog').close();await syncPhoneSettings();});
async function refresh(){if(!session)return;session=await json(sidPath(session.id));await renderJobs();}
async function refreshSessions(){sessions=await json('/api/digitize/sessions');$('sessions').replaceChildren();for(const s of sessions){const option=document.createElement('option');option.value=s.id;option.textContent=s.name;$('sessions').append(option);}if(session)$('sessions').value=session.id;}
on('sessions','change',async()=>{session=await json(sidPath($('sessions').value));await renderJobs();gate.reset();schedulePoll();});
on('newSession','click',async()=>{const name=prompt(tr('Name der Sammlung','Collection name'),tr('Fotoalbum','Photo album'));if(!name?.trim())return;session=await post('/api/digitize/sessions',{name:name.trim()});await refreshSessions();await renderJobs();gate.reset();});
on('refresh','click',refresh);
function element(tag,text,cls){const e=document.createElement(tag);if(text!==undefined)e.textContent=text;if(cls)e.className=cls;return e;}
function button(text,action){const b=element('button',text,'quiet');b.onclick=()=>Promise.resolve(action()).catch(e=>notice(e.message));return b;}
async function imageBlob(path,img,thumbnail=false){const url=URL.createObjectURL(await(await api(path)).blob());(thumbnail?thumbUrls:activeUrls).push(url);img.src=url;}
async function download(path,name,share=false){const blob=await(await api(path)).blob();const file=new File([blob],name,{type:blob.type});if(share&&navigator.canShare?.({files:[file]})){await navigator.share({files:[file]});return;}const a=document.createElement('a');const url=URL.createObjectURL(blob);a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),30000);}
async function renderJobs(){
  thumbUrls.forEach(url=>URL.revokeObjectURL(url));thumbUrls=[];
  $('count').textContent=session.jobs.reduce((sum,j)=>sum+(j.receipt?.complete?j.pages.length:0),0);
  $('batchCount').textContent=tr(`${session.jobs.filter(j=>j.status==='ready').length} Aufnahmen · ${session.jobs.filter(j=>['queued','processing'].includes(j.status)).length} in Arbeit`,`${session.jobs.filter(j=>j.status==='ready').length} captures · ${session.jobs.filter(j=>['queued','processing'].includes(j.status)).length} processing`);
  $('jobs').replaceChildren();
  if(!session.jobs.length){$('jobs').append(element('p',tr('Noch keine Aufnahmen. Originale erscheinen nach dem Digitalisieren hier.','No captures yet. Your originals appear here after digitising.'),'subtle'));return;}
  const sessionId=session.id;
  for(const job of [...session.jobs].reverse()){
    const box=element('article',undefined,'job'),head=element('div',undefined,'jobhead');
    const label=job.receipt?.state==='review'?tr('Prüfung nötig','Review required'):{queued:tr('Wartet','Queued'),processing:tr('Wird digitalisiert …','Digitising…'),ready:tr(`${job.pages.length} Vorlagen gesichert`,`${job.pages.length} items saved`),failed:tr('Aufnahme prüfen','Review capture')}[job.status];
    head.append(element('strong',label),element('span',new Date(job.created_at).toLocaleString(lang), 'jobmeta'));
    head.append(button(tr('Original','Original'),()=>download(filePath(sessionId,job.id,job.original),job.original)));
    if(job.status==='ready'){head.append(button(tr('ZIP herunterladen / teilen','Download / share ZIP'),()=>download(jobPath(sessionId,job.id)+'/archive',`LumaScan-${job.id.slice(0,8)}.zip`,true)));}
    box.append(head,element('p',job.destination_path||tr('Lokales Archiv','Local archive'),'jobmeta'));
    if(job.source==='video-frame')box.append(element('p',tr('Quelle: Videobild. Originalfoto bietet meist mehr Detail.','Source: video frame. Original photographs usually offer more detail.'),'subtle'));
    if(job.receipt?.state==='review')box.append(element('p',job.receipt.reasons.join(', '),'subtle'),button(tr('Aufnahme geprüft und akzeptiert','Reviewed and accepted'),async()=>{await post(jobPath(sessionId,job.id)+'/review',{});await refresh();}));
    if(job.error){box.append(element('p',job.error),button(tr('Original öffnen und Ränder prüfen','Open original and review borders'),async()=>{const blob=await(await api(filePath(sessionId,job.id,job.original))).blob();await openFile(new File([blob],job.original,{type:blob.type}));$('stage').scrollIntoView({block:'center',behavior:'smooth'});}));}
    if(job.export_status==='failed'){box.append(element('p',tr('Zielordner nicht erreicht. Originale und Ergebnisse im lokalen Archiv gesichert. ','Destination not reached. Originals and results saved in the local archive. ')+job.export_error),button(tr('Ziel erneut speichern','Retry destination'),async()=>{await post(jobPath(sessionId,job.id)+'/retry-export',{});await refresh();}));}
    const sheet=element('div',undefined,'contactsheet');
    for(const page of job.pages){const card=element('div',undefined,'page'),thumb=element('div',undefined,'thumb'),img=element('img');img.alt=`${page.index}`;thumb.append(img);card.append(thumb);void imageBlob(filePath(sessionId,job.id,page.id+'/preview.jpg'),img,true).catch(()=>{});card.append(element('p',`${page.index} · ${page.width} × ${page.height} px`));card.append(button('PNG',()=>download(filePath(sessionId,job.id,page.id+'/scan.png'),`scan-${page.index}.png`)),button('PDF',()=>download(filePath(sessionId,job.id,page.id+'/scan.pdf'),`scan-${page.index}.pdf`)),button(tr('Bearbeiten','Edit'),()=>openEditor(sessionId,job,page)));
      if(page.ocr.status==='ready'){const details=element('details'),summary=element('summary',tr('Erkannter Text','Recognised text'));details.append(summary,element('pre',page.ocr.text));card.append(details);}
      else if(['failed','unavailable'].includes(page.ocr.status))card.append(element('p',tr('OCR nicht verfügbar / fehlgeschlagen. Bild ist gesichert.','OCR unavailable / failed. Image is saved.'),'subtle'));
      for(const version of page.versions||[])card.append(button(tr('Version ','Version ')+version.id.slice(0,4),()=>download(filePath(sessionId,job.id,page.id+'/'+version.id+'.png'),'restored.png')));
      sheet.append(card);
    }box.append(sheet);$('jobs').append(box);
  }
}
function schedulePoll(){clearTimeout(pollTimer);pollTimer=setTimeout(poll,1100);}
async function poll(){
  if(polling)return;polling=true;
  try{
    const current=session;if(current){const updated=await json(sidPath(current.id));if(session?.id===current.id){const changed=JSON.stringify(updated)!==JSON.stringify(session);session=updated;if(changed)await renderJobs();}}
    for(const [jid,target] of browserTargets){const data=target.sid===session?.id?session:await json(sidPath(target.sid));const job=data.jobs.find(j=>j.id===jid);if(job?.status==='ready'&&!browserSaved.has(jid)){try{await saveToHandle(target.handle,target.sid,job);browserSaved.add(jid);browserTargets.delete(jid);}catch(e){browserTargets.delete(jid);notice(tr('Geräteordner nicht beschreibbar. Aufnahme bleibt im lokalen Archiv. ','Cannot write to device folder. Capture remains in local archive. ')+e.message);}}if(job?.status==='failed')browserTargets.delete(jid);}
  }catch(e){notice(e.message);}finally{polling=false;if(session?.jobs.some(j=>(['queued','processing'].includes(j.status)||j.receipt?.state==='processing'))||browserTargets.size)schedulePoll();}
}
async function saveToHandle(handle,sid,job){const folder=await handle.getDirectoryHandle('LumaScan-'+job.id,{create:true});for(const page of job.pages){for(const file of ['scan.png','scan.pdf','text.txt']){const target=await folder.getFileHandle(`${page.id}-${file}`,{create:true}),writer=await target.createWritable();await writer.write(await(await api(filePath(sid,job.id,page.id+'/'+file))).blob());await writer.close();}}const zip=await folder.getFileHandle('originals-and-results.zip',{create:true}),writer=await zip.createWritable();await writer.write(await(await api(jobPath(sid,job.id)+'/archive')).blob());await writer.close();notice(tr(`Im Geräteordner ${handle.name} gesichert.`,`Saved to device folder ${handle.name}.`));}

let edit=null,editImage=null,strokes=[],drawingStroke=null,rotation=0;
async function openEditor(sid,job,page){
  edit={sid,job,page};strokes=[];rotation=page.rotation||0;$('editMode').value=page.mode;$('brush').checked=false;$('editStatus').textContent='';$('versionDownload').hidden=true;
  const url=URL.createObjectURL(await(await api(filePath(sid,job.id,page.id+'/crop.png'))).blob());activeUrls.push(url);editImage=new Image();editImage.src=url;await editImage.decode();$('repairCanvas').width=editImage.width;$('repairCanvas').height=editImage.height;drawRepair();await imageBlob(filePath(sid,job.id,page.id+'/scan.png'),$('versionImage'));$('editor').showModal();
}
function drawRepair(){const c=$('repairCanvas'),x=c.getContext('2d');x.drawImage(editImage,0,0);x.strokeStyle='#f34d64';x.fillStyle='#f34d64';x.globalAlpha=.6;x.lineWidth=Number($('radius').value)*2;x.lineCap='round';for(const stroke of strokes){x.beginPath();stroke.forEach(([u,v],i)=>i?x.lineTo(u*(c.width-1),v*(c.height-1)):x.moveTo(u*(c.width-1),v*(c.height-1)));x.stroke();}x.globalAlpha=1;}
on('repairCanvas','pointerdown',e=>{if(!$('brush').checked)return;const p=position(e,$('repairCanvas'));drawingStroke=[[p[0]/($('repairCanvas').width-1),p[1]/($('repairCanvas').height-1)]];strokes.push(drawingStroke);$('repairCanvas').setPointerCapture(e.pointerId);drawRepair();});
on('repairCanvas','pointermove',e=>{if(!drawingStroke)return;const p=position(e,$('repairCanvas'));drawingStroke.push([p[0]/($('repairCanvas').width-1),p[1]/($('repairCanvas').height-1)]);drawRepair();});
on('repairCanvas','pointerup',()=>drawingStroke=null);on('repairCanvas','pointercancel',()=>drawingStroke=null);
on('undoStroke','click',()=>{strokes.pop();drawRepair();});on('radius','input',drawRepair);
on('rotate','click',()=>{rotation=(rotation+90)%360;$('editStatus').textContent=tr(`Drehung für neue Version: ${rotation}°`,`New version rotation: ${rotation}°`);});
on('makeVersion','click',async()=>{
  $('makeVersion').disabled=true;$('editStatus').textContent=tr('Neue Version wird berechnet …','Calculating new version…');
  try{const result=await post(`${jobPath(edit.sid,edit.job.id)}/pages/${edit.page.id}/versions`,{mode:$('editMode').value,rotation,strokes,radius:Number($('radius').value),ocr:$('ocr').checked});await imageBlob(filePath(edit.sid,edit.job.id,edit.page.id+'/'+result.id+'.png'),$('versionImage'));$('versionDownload').hidden=false;$('versionDownload').onclick=e=>{e.preventDefault();void download(filePath(edit.sid,edit.job.id,edit.page.id+'/'+result.id+'.png'),'restored.png').catch(e=>notice(e.message));};$('editStatus').textContent=result.export_error||tr('Neue Version gesichert. Das Original bleibt erhalten.','New version saved. Original retained.');await refresh();}finally{$('makeVersion').disabled=false;}
});
window.addEventListener('beforeunload',()=>{stopSource();[...activeUrls,...thumbUrls].forEach(x=>URL.revokeObjectURL(x));});
async function initialize(){
  if(!token){const bootstrap=await json('/api/bootstrap');token=bootstrap.token;sessionStorage.setItem('lumascanToken',token);}
  status=await json('/api/digitize/status');renderDestinations();
  $('ocrStatus').textContent=status.ocr_available?tr('RapidOCR lokal verfügbar. Text in TXT und durchsuchbarem PDF.','Local RapidOCR ready. Text in TXT and searchable PDF.'):tr('OCR nicht eingerichtet. Fotos und PDFs funktionieren.','OCR not configured. Photographs and PDFs work.');
  $('ocr').disabled=!status.ocr_available;$('ocr').checked=status.ocr_available;
  $('orient').disabled=!$('ocr').checked;
  await refreshSessions();session=sessions[0]||await post('/api/digitize/sessions',{name:tr('Mein Fotoarchiv','My photo archive')});await refreshSessions();await refresh();schedulePoll();
}
for(const control of ['destination','treatment','ocr','orient'])$(control).addEventListener('change',()=>void syncPhoneSettings().catch(e=>notice(e.message)));
$('existingPeer').hidden=true;$('resume').hidden=true;document.querySelector('label[for="existingPeer"]').hidden=true;
setInterval(()=>{if(session&&!document.hidden)void refresh().catch(()=>{});},2500);
initialize().catch(e=>notice(e.message));
