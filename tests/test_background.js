const assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');
const base=require('node:path').join(__dirname,'../extension/');
function fixture({block=false,store={}}={}){
 let listener,selected=0,created=0,exported,blocked=block,writes=[];
 const page=()=>({kind:'page',source_novel_id:selected,novelupdates_url:`https://www.novelupdates.com/series/n${selected}/`,source_title:`Novel ${selected}`,html:'<div>fixture</div>',captured_at:new Date().toISOString(),capture_format:'novelclue_metadata_fragment_v1'});
 const browser={storage:{local:{get:async keys=>Object.fromEntries((Array.isArray(keys)?keys:[keys]).filter(k=>store[k]).map(k=>[k,store[k]])),
 set:async obj=>{writes.push(Object.keys(obj));Object.assign(store,structuredClone(obj));},remove:async keys=>keys.forEach(k=>delete store[k])}},
 runtime:{onMessage:{addListener:fn=>listener=fn}},
 tabs:{create:async({url})=>{created++;selected=Number(new URL(url).searchParams.get('p'));return {id:1};},
 update:async(id,{url})=>{selected=Number(new URL(url).searchParams.get('p'));},get:async()=>({status:'complete'}),
 executeScript:async()=>[blocked?{kind:'blocked',reason:'Verification detected.'}:page()]},
 downloads:{download:async({url})=>{exported=JSON.parse(await (await fetch(url)).text());return 1;}}};
 const ctx=vm.createContext({browser,URL,Blob,console,setTimeout:(fn,ms)=>ms===60000?0:setImmediate(fn)});
 vm.runInContext(fs.readFileSync(base+'core.js','utf8'),ctx);
 vm.runInContext(fs.readFileSync(base+'background.js','utf8'),ctx);
 async function send(action,data){return listener({action,data});}
 async function finish(){for(let i=0;i<2000;i++){await new Promise(setImmediate);const s=await send('status');if(!s.running)return s;}throw new Error('did not stop');}
 return {send,finish,unblock:()=>blocked=false,store,writes,get created(){return created;},get exported(){return exported;}};
}
(async()=>{
 const f=fixture();await f.send('load',Array.from({length:20},(_,i)=>i+1));await f.send('start',{delay:1});let s=await f.finish();
 assert.equal(s.captured,20);assert.equal(f.created,1);assert.equal(s.status,'complete');
 assert(f.writes.every(keys=>keys.filter(k=>k.startsWith('collector-page-')).length<=1));
 await f.send('export');assert.equal(f.exported.records.length,20);assert.equal(f.exported.queue.length,20);
 await assert.rejects(()=>f.send('load',[9]));
 const restarted=fixture({store:f.store});s=await restarted.send('status');assert.equal(s.captured,20);assert.equal(s.running,false);
 const restored=fixture();await restored.send('load',f.exported);await restored.send('start');s=await restored.finish();assert.equal(restored.created,0);assert.equal(s.captured,20);
 const blocked=fixture({block:true});await blocked.send('load',[4052,392]);await blocked.send('start');
 s=await blocked.finish();assert.equal(s.captured,0);assert.equal(s.pending,4052);assert.equal(s.status,'paused');
 await blocked.send('export');assert.equal(blocked.exported.queue.length,2);
 blocked.unblock();await blocked.send('start');s=await blocked.finish();assert.equal(s.captured,2);assert.equal(blocked.created,1);
 const partial=structuredClone(f.exported);partial.records=partial.records.slice(0,17);
 const resume=fixture();await resume.send('load',partial);await resume.send('start');s=await resume.finish();assert.equal(s.captured,20);assert.equal(resume.created,1);
 const paused=fixture();await paused.send('load',[1,2]);await paused.send('start');await paused.send('export');await paused.send('pause');
 s=await paused.finish();assert(s.captured<2);assert.equal(paused.exported.queue.length,2);
 await assert.rejects(()=>paused.send('start',{delay:0}));
 const invalid=structuredClone(partial);invalid.records.push(invalid.records[0]);await assert.rejects(()=>fixture().send('load',invalid));
 await f.send('clear');assert.equal((await f.send('status')).captured,0);
 assert(!Object.keys(f.store).some(k=>k.startsWith('collector-page-')));
 const legacy=fixture({store:{collector:{queue:[{id:1,title:'one'}],records:[partial.records[0]],status:'paused',tabId:null,pending:null}}});
 await legacy.send('export');assert.equal(legacy.exported.records.length,1);await legacy.send('start');await legacy.finish();
 assert(!('records' in legacy.store.collector));
 console.log('Background checks passed: continuous 20, incremental storage, restore, partial checkpoints, export while running, challenge and manual pause, migration, clear.');
})().catch(e=>{console.error(e);process.exit(1);});
