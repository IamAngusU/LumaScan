const {createRequire}=require('node:module');const path=require('node:path');const assert=require('node:assert/strict');
const {chromium}=createRequire(path.join(process.env.LUMASCAN_NODE_MODULES,'runtime.cjs'))('playwright');
(async()=>{
 const browser=await chromium.launch({executablePath:process.env.LUMASCAN_CHROME,headless:true});
 try{
  const desktop=await browser.newPage({viewport:{width:1440,height:1000}});const errors=[];desktop.on('pageerror',e=>errors.push(e.message));
  await desktop.goto('http://127.0.0.1:8774/scanner.html');await desktop.locator('#sessions option').first().waitFor({state:'attached'});
  desktop.once('dialog',d=>d.accept('Browser QA '+Date.now()));await desktop.locator('#newSession').click();await desktop.waitForFunction(()=>document.querySelector('#count').textContent==='0');
  await desktop.locator('#connect').click();await desktop.waitForFunction(()=>document.querySelector('#sender').href.includes('/phone.html#pair='));
  const url=await desktop.locator('#sender').getAttribute('href');assert(url.includes('/phone.html#pair='));
  await desktop.screenshot({path:'runtime/qa/desktop-pair.png',fullPage:true});
  const phone=await browser.newPage({viewport:{width:390,height:844}});phone.on('pageerror',e=>errors.push(e.message));
  await phone.addInitScript(()=>{
    const c=document.createElement('canvas');c.width=2200;c.height=1600;const x=c.getContext('2d');
    function draw(second=false){x.fillStyle='#677581';x.fillRect(0,0,c.width,c.height);x.fillStyle='#fffdf8';x.fillRect(220,160,1760,1280);x.fillStyle='#142840';x.font='60px Arial';for(let i=0;i<8;i++)x.fillText((second?'SECOND DOCUMENT ':'FAMILY ARCHIVE ')+i,330,330+i*125);}
    draw();window.testReplace=()=>draw(true);setInterval(()=>{x.fillRect(0,0,1,1);},66);
    navigator.mediaDevices.getUserMedia=async()=>c.captureStream(15);
    window.ImageCapture=undefined;
  });
  await phone.goto(url);await phone.locator('#message').filter({hasText:'Bereit'}).waitFor();await phone.locator('#start').click();
  await phone.locator('#feedback.processing').waitFor({timeout:15000});
  await phone.screenshot({path:'runtime/qa/phone-processing.png'});
  await phone.locator('#feedback.saved').waitFor({timeout:30000});assert.equal(await phone.locator('#count').textContent(),'1');
  await phone.screenshot({path:'runtime/qa/phone-saved.png'});await phone.waitForTimeout(2500);assert.equal(await phone.locator('#count').textContent(),'1');
  await phone.evaluate(()=>window.testReplace());await phone.waitForFunction(()=>document.querySelector('#count').textContent==='2',undefined,{timeout:30000});
  await desktop.locator('#pair .close').click();await desktop.waitForFunction(()=>document.querySelector('#count').textContent==='2');
  await desktop.screenshot({path:'runtime/qa/desktop-results.png',fullPage:true});assert.deepEqual(errors,[]);
  console.log('PASS: desktop QR -> scoped phone -> automatic capture -> processing spinner -> persisted/OCR-complete green -> no duplicate -> replacement -> counter 2.');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exit(1);});
