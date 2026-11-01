fetch('/openapi.json').then(r=>r.json()).then(schema=>{
 const target=document.getElementById('endpoints');
 for(const [path,methods]of Object.entries(schema.paths))for(const [method,operation]of Object.entries(methods)){
  const details=document.createElement('details'),summary=document.createElement('summary'),pre=document.createElement('pre');
  summary.textContent=method.toUpperCase()+' '+path+' — '+(operation.summary||'');pre.textContent=JSON.stringify(operation,null,2);details.append(summary,pre);target.append(details);
 }
 document.getElementById('schemas').textContent=JSON.stringify(schema.components?.schemas||{},null,2);
}).catch(e=>{document.getElementById('endpoints').textContent=e.message;});
