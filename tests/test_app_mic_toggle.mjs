// FE2: exercise real app event handlers with mocked devices/server, no Gemini calls.
// Run: node tests/test_app_mic_toggle.mjs
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
const source = fs.readFileSync(new URL('../static/app.js', import.meta.url), 'utf8').replace(/^import .*;.*$/gm, '');
function harness(liveAvailable = false) {
  const elements = new Map();
  function element(id) {
    if (elements.has(id)) return elements.get(id);
    const classes = new Set();
    const el = { id, value: id === 'region-select' ? 'europe' : '20-29', selectedIndex: 0,
      options: [{text:'Europe'}], children: [], attrs: {}, listeners: {}, disabled:false,
      classList: {add(...xs){xs.forEach(x=>classes.add(x));},remove(...xs){xs.forEach(x=>classes.delete(x));},toggle(x,v){v?classes.add(x):classes.delete(x);},contains(x){return classes.has(x);}},
      addEventListener(type,fn){(this.listeners[type]??=[]).push(fn);},
      async fire(type){for(const fn of this.listeners[type]??[])await fn({preventDefault(){}});},
      setAttribute(k,v){this.attrs[k]=v;},removeAttribute(k){delete this.attrs[k];},
      querySelector(q){return element(id+q);}, appendChild(c){this.children.push(c);},
      replaceChildren(){this.children=[];},focus(){},
    };
    elements.set(id,el);return el;
  }
  const track={enabled:true,stop(){this.stopped=true;}};
  const stream={getAudioTracks:()=>[track],getTracks:()=>[track]};
  let sent=0, recorder, handlers;
  class Recorder {
    constructor(){recorder=this;this.state='inactive';this.mimeType='audio/webm';}
    start(){this.state='recording';}
    stop(){this.state='inactive';this.ondataavailable?.({data:new Blob(['audio'])});this.done=this.onstop?.();}
  }
  const conversation={muted:false,prime(){},close(){},
    async open(){if(!liveAvailable)throw new Error('offline');handlers.onStatus({state:'listening',status:'Listening',label:'Listening'});},
    toggleMuted(){this.muted=!this.muted;handlers.onStatus({state:this.muted?'muted':'listening',status:'changed',label:'changed'});},
  };
  const context={console:{warn(){}},Blob,Map,Set,performance,
    document:{getElementById:element,querySelector:element,createElement:element,addEventListener(){}},
    window:{scrollTo(){},MediaRecorder:Recorder},MediaRecorder:Recorder,MediaStream:class {},
    navigator:{mediaDevices:{getUserMedia:async()=>stream}},
    startSession:async()=>({session_id:'session',reply:'hello'}),
    postTurn:async()=>{sent++;return {reply:'reply',artwork_id:'unknown'};},
    initAudio:async()=>{},speak(){},stopSpeaking(){},toWav16k:async()=>new Blob([new Uint8Array(9000)]),
    createLiveConversation:({handlers:h})=>{handlers=h;return conversation;},
    createVisitStore:()=>({load:()=>null,save(){},clear(){}}),createWakeLock:()=>({request(){},release(){}}),
    FRAME_MAX_WIDTH:1100,fetch:async()=>({ok:true}),alert(m){throw new Error(m);},
  };
  vm.runInNewContext(source,context);
  return {element,track,conversation,get recorder(){return recorder;},get sent(){return sent;},handlers:()=>handlers};
}
const h=harness();
await h.element('onboarding-form').fire('submit');
assert.equal(h.track.enabled,false,'fallback starts muted');
assert.equal(h.element('talk').attrs['aria-pressed'],'true');
await h.element('talk').fire('click');
assert.equal(h.recorder.state,'recording');assert.equal(h.track.enabled,true);
await h.element('talk').fire('pointerup');
assert.equal(h.recorder.state,'recording','lifting finger must not send');
await h.element('talk').fire('click');
assert.equal(h.track.enabled,false,'mute stops real input');
assert.equal(h.element('talk').disabled,true,'rapid click blocked during decoding');
await h.element('talk').fire('click');
await h.recorder.done;
assert.equal(h.sent,1);assert.equal(h.element('talk').disabled,false);
await h.element('talk').fire('click');
await h.element('end-visit').fire('click');
assert.equal(h.sent,1,'ending a visit must discard unfinished audio');assert.equal(h.track.stopped,true);
const l=harness(true);
await l.element('onboarding-form').fire('submit');
assert.equal(l.element('talk').attrs['aria-pressed'],'false');
await l.element('talk').fire('click');assert.equal(l.conversation.muted,true);
assert.equal(l.element('talk').classList.contains('muted'),true);
await l.element('talk').fire('click');assert.equal(l.conversation.muted,false);
l.handlers().onStatus({state:'reconnecting',status:'Reconnecting',label:'Reconnecting'});
assert.equal(l.element('talk').disabled,true);assert.equal(l.element('talk').attrs['aria-pressed'],undefined);
l.handlers().onStatus({state:'muted',status:'Muted',label:'Muted'});
assert.equal(l.element('talk').disabled,false);assert.equal(l.element('talk').attrs['aria-pressed'],'true');
console.log('PASS: fallback tap/mute/send, rapid taps, end discard, Live mute and reconnect UI');
