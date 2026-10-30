const assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');
const base=require('node:path').join(__dirname,'../extension/');
function fixture(block=false){
 let listener,selected=0,created=0,exported=0,stored,blocked=block;
 const page=()=>({kind:'page',source_novel_id:selected,novelupdates_url:`https://www.novelupdates.com/series/n${selected}/`,source_title:`Novel ${selected}`,html:'<div>fixture</div>'});
 const browser={storage:{local:{get:async()=>({}),set:async obj=>{stored=structuredClone(obj.collector);}}},
 runtime:{onMessage:{addListener:fn=>listener=fn}},
 tabs:{create:async({url})=>{created++;selected=Number(new URL(url).searchParams.get('p'));return {id:1};},
 update:async(id,{url})=>{selected=Number(new URL(url).searchParams.get('p'));},get:async()=>({status:'complete'}),
 executeScript:async()=>[blocked?{kind:'blocked',reason:'Verification detected.'}:page()]},
 downloads:{download:async()=>{exported++;return 1;}}};
 const ctx=vm.createContext({browser,URL,Blob,console,setTimeout:(fn)=>setImmediate(fn)});
 vm.runInContext(fs.readFileSync(base+'core.js','utf8'),ctx);
 vm.runInContext(fs.readFileSync(base+'background.js','utf8'),ctx);
 async function send(action,data){return listener({action,data});}
 async function finish(){for(let i=0;i<500;i++){await new Promise(setImmediate);const s=await send('status');if(!s.running)return s;}throw new Error('did not stop');}
 return {send,finish,unblock:()=>blocked=false,get stored(){return stored;},get created(){return created;},get exported(){return exported;}};
}
(async()=>{
 const f=fixture();await f.send('load',[1,2,3,4,5,6]);await f.send('start');let s=await f.finish();
 assert.equal(s.captured,5);assert.equal(f.created,1);assert.equal(f.stored.status,'paused');
 await f.send('export');assert.equal(f.exported,1);
 await assert.rejects(()=>f.send('load',[9]));
 await f.send('start');s=await f.finish();assert.equal(s.captured,6);assert.equal(s.status,'complete');
 const blocked=fixture(true);await blocked.send('load',[4052]);await blocked.send('start');
 s=await blocked.finish();assert.equal(s.captured,0);assert.equal(s.pending,4052);assert.equal(s.status,'paused');
 blocked.unblock();await blocked.send('start');s=await blocked.finish();
 assert.equal(s.captured,1);assert.equal(blocked.created,1); // resume rechecks without new tab
 const paused=fixture();await paused.send('load',[1,2]);await paused.send('start');await paused.send('pause');
 s=await paused.finish();assert.equal(s.captured,0);
 console.log('Background checks passed: five-page bound, export, challenge pause/resume, user pause.');
})().catch(e=>{console.error(e);process.exit(1);});
