// Versioned, bounded, stop-and-wait transfer. No archive credentials cross this link.
export const MAX_FILE = 32 * 1024 * 1024;
export const CHUNK = 48 * 1024;
export const LABEL = "lumadrop-photos-v1";
export const allowedPhoto = (f) => Number.isSafeInteger(f.size) && f.size > 0 && f.size <= MAX_FILE &&
  /\.(jpe?g|png|webp|heic|heif)$/i.test(f.name) && ["", "image/jpeg","image/png","image/webp","image/heic","image/heif"].includes(f.type);
export function digest(bytes) {
  return crypto.subtle.digest("SHA-256", bytes).then(hash=>Array.from(new Uint8Array(hash),b=>b.toString(16).padStart(2,"0")).join(""));
}
function exchange(link,message,expect,timeout=30000) {
  return new Promise((resolve,reject)=>{
    const cleanup=()=>{clearTimeout(timer);link.off("data",data);link.off("close",closed);link.off("error",closed);};
    const fail=(text)=>{cleanup();reject(new Error(text));};
    const data=(m)=>{if(m?.id!==message.id)return;if(m.type==="error")return fail(m.message||"Empfang fehlgeschlagen");if(expect(m)){cleanup();resolve(m);}};
    const closed=()=>fail("Dateikanal geschlossen. Erneut verbinden.");
    const timer=setTimeout(()=>fail("Empfang nicht bestätigt. Am Computer prüfen; nicht automatisch doppelt senden."),timeout);
    link.on("data",data);link.on("close",closed);link.on("error",closed);
    try {link.send(message);}catch {closed();}
  });
}
export async function sendFiles(link,files,meta={},progress=()=>{}) {
  if(!link?.open)throw new Error("Zuerst den Dateikanal verbinden.");
  if(files.length>30)throw new Error("Höchstens 30 Fotos pro Auswahl.");
  for(const file of files)if(!allowedPhoto(file))throw new Error("JPEG, PNG, WebP oder HEIC wählen; maximal 32 MB pro Foto.");
  for(let i=0;i<files.length;i++) {
    const file=files[i],bytes=await file.arrayBuffer(),id=crypto.randomUUID();
    const sha256=await digest(bytes);
    await exchange(link,{type:"begin",id,name:file.name,typeHint:file.type,size:bytes.byteLength,sha256,meta},m=>m.type==="ready");
    for(let offset=0;offset<bytes.byteLength;offset+=CHUNK) {
      const chunk=bytes.slice(offset,offset+CHUNK),end=offset+chunk.byteLength;
      await exchange(link,{type:"chunk",id,offset,bytes:chunk},m=>m.type==="ack"&&m.offset===end);
      progress(`${i+1}/${files.length} · ${Math.round(end/bytes.byteLength*100)} %`);
    }
    await exchange(link,{type:"end",id},m=>m.type==="saved",120000);
    progress(`${i+1}/${files.length} am Computer bestätigt`);
  }
}
export function receiveFiles(link,onFile,onStatus=()=>{}) {
  let active=null,writing=false,timer;
  const reset=()=>{clearTimeout(timer);active=null;};
  const arm=()=>{clearTimeout(timer);timer=setTimeout(()=>{const id=active?.id;reset();if(link.open)link.send({type:"error",id,message:"Übertragung abgelaufen"});},30000);};
  const data=async(m)=>{
    if(!m||typeof m!=="object"||typeof m.id!=="string"||m.id.length>64)return;
    try {
      if(m.type==="begin") {
        if(active||writing)throw new Error("Ein Foto wird bereits übertragen.");
        if(!allowedPhoto({name:m.name,type:m.typeHint,size:m.size})||typeof m.name!=="string"||m.name.length>240||!(/^[a-f0-9]{64}$/).test(m.sha256))throw new Error("Ungültige Fotodaten.");
        const meta={view:["front","back","edge","detail","other"].includes(m.meta?.view)?m.meta.view:"other",
          tip_direction:["left","right","up","down","unknown"].includes(m.meta?.tip_direction)?m.meta.tip_direction:"unknown",
          source:["library","camera-original","video-frame"].includes(m.meta?.source)?m.meta.source:"library"};
        active={...m,meta,offset:0,parts:[]};arm();link.send({type:"ready",id:m.id});onStatus(`Empfange ${m.name}`);
      } else if(m.type==="chunk") {
        if(!active||m.id!==active.id||m.offset!==active.offset)throw new Error("Falsche Reihenfolge.");
        const bytes=m.bytes instanceof ArrayBuffer?m.bytes:ArrayBuffer.isView(m.bytes)?m.bytes.buffer.slice(m.bytes.byteOffset,m.bytes.byteOffset+m.bytes.byteLength):null;
        if(!bytes||bytes.byteLength<1||bytes.byteLength>CHUNK||active.offset+bytes.byteLength>active.size)throw new Error("Ungültiger Datenblock.");
        active.parts.push(bytes);active.offset+=bytes.byteLength;arm();link.send({type:"ack",id:m.id,offset:active.offset});
      } else if(m.type==="end") {
        if(!active||m.id!==active.id||active.offset!==active.size)throw new Error("Foto unvollständig.");
        const file=active;writing=true;reset();
        try {
          const blob=new Blob(file.parts,{type:file.typeHint||"application/octet-stream"});
          if(await digest(await blob.arrayBuffer())!==file.sha256)throw new Error("Prüfsumme stimmt nicht.");
          await onFile(blob,file);
          if(link.open)link.send({type:"saved",id:m.id});onStatus("Foto vollständig empfangen");
        } finally {writing=false;}
      }
    } catch(error) {reset();if(link.open)link.send({type:"error",id:m.id,message:error.message});onStatus(error.message);}
  };
  link.on("data",data);link.on("close",reset);
  return ()=>{reset();link.off("data",data);link.off("close",reset);};
}
