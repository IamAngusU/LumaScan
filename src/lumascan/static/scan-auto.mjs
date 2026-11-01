// Stable content, not elapsed time alone, arms a new capture.
export class CaptureGate {
  constructor({holdMs=1600, change=9, motion=2.8}={}) {
    Object.assign(this,{holdMs,change,motion}); this.reset();
  }
  reset() {this.last=null;this.saved=null;this.since=null;this.samples=0;this.empty=0;this.pending=false;}
  distance(a,b) {if(!a||!b||a.length!==b.length)return Infinity;const differences=a.map((x,i)=>Math.abs(x-b[i])).sort((x,y)=>y-x);const n=Math.max(1,Math.ceil(differences.length*.03));return differences.slice(0,n).reduce((sum,x)=>sum+x,0)/n;}
  observe({pixels,count,sharpness,time}) {
    if(!count) {
      this.since=null;this.samples=0;this.last=null;
      // A brief failed detection is not proof that the old page was removed.
      if(++this.empty>=3)this.saved=null;
      return {state:'empty',progress:0,trigger:false};
    }
    this.empty=0;
    if(this.pending)return {state:'pending',progress:0,trigger:false};
    const motion=this.distance(pixels,this.last);this.last=pixels.slice();
    if(motion>this.motion||sharpness<30) {this.since=time;this.samples=0;return {state:sharpness<30?'blur':'moving',progress:0,trigger:false};}
    if(this.distance(pixels,this.saved)<this.change)return {state:'saved',progress:1,trigger:false};
    if(this.since===null)this.since=time;
    const progress=Math.min(1,(time-this.since)/this.holdMs);this.samples++;
    const trigger=progress>=1&&this.samples>=3;
    if(trigger){this.pending=true;this.candidate=pixels.slice();}
    return {state:trigger?'capture':'steady',progress,trigger};
  }
  committed() {this.saved=this.candidate;this.pending=false;this.since=null;this.samples=0;}
  failed() {this.pending=false;this.since=null;this.samples=0;}
}
