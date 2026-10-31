function emptyState(message='Load a queue to begin.') {
  return {queue:[],records:[],status:'idle',message,tabId:null,pending:null,delay:2,
    generation:Date.now().toString(36)+'-'+Math.random().toString(36).slice(2)};
}
let state=emptyState(), running=false,stop=false,busy=false;
const storedIds=new Set();
const recordKey=id=>`collector-page-${state.generation}-${id}`;
const ready=(async()=>{
  const saved=await browser.storage.local.get('collector');
  if(saved.collector){
    state={...emptyState(),...saved.collector,tabId:null,status:'paused'};
    if(!Array.isArray(saved.collector.records)){
      const keys=state.queue.map(r=>recordKey(r.id));
      const pages=await browser.storage.local.get(keys);
      state.records=keys.filter(k=>pages[k]).map(k=>pages[k]);
      state.records.forEach(r=>storedIds.add(r.source_novel_id));
    }
    state.message='Saved progress restored. Click Start / Resume when ready.';
  }
})();
const sleep=ms=>new Promise(resolve=>setTimeout(resolve,ms));
async function persist(){
  const {records,...metadata}=state;
  const update={collector:metadata};
  const added=[];
  for(const page of records)if(!storedIds.has(page.source_novel_id)){
    update[recordKey(page.source_novel_id)]=page;added.push(page.source_novel_id);
  }
  await browser.storage.local.set(update);
  added.forEach(id=>storedIds.add(id));
}
function summary(){return {status:state.status,message:state.message,queued:state.queue.length,
  captured:state.records.length,pending:state.pending,running,delay:state.delay};}
async function pause(message){stop=true;state.status='paused';state.message=message;await persist();}
async function collectBatch(){
  try{
    while(!stop){
      const done=new Set(state.records.map(r=>r.source_novel_id));
      const item=state.queue.find(r=>!done.has(r.id));
      if(!item){state.status='complete';state.message='Queue complete. Export captured pages and checkpoint.';break;}
      let sameTab=false;
      if(state.pending===item.id && state.tabId!==null){
        try{await browser.tabs.get(state.tabId);sameTab=true;}catch(_){state.tabId=null;}
      }
      state.pending=item.id;state.message=`Loading ${item.title} (${item.id})`;await persist();
      const url=`https://www.novelupdates.com/?p=${item.id}`;
      if(!sameTab){
        if(state.tabId===null)state.tabId=(await browser.tabs.create({url,active:true})).id;
        else await browser.tabs.update(state.tabId,{url});
      }
      let captured=false, lastMismatch=null, sawVerification=false;
      for(let attempt=0;attempt<120 && !stop;attempt++){
        await sleep(500);if(stop)break;
        // Check the DOM before images/ads finish. capture.js checks readiness.
        await browser.tabs.get(state.tabId);
        let results;
        try{results=await browser.tabs.executeScript(state.tabId,{file:'capture.js',runAt:'document_start'});}
        catch(error){
          const tab=await browser.tabs.get(state.tabId);
          if(tab.status==='loading')continue;
          throw error;
        }
        if(stop)break;
        const page=results[0];
        if(page?.kind==='blocked'){
          // Allow the site's automatic check to finish in this same tab.
          // This only observes the page; it never clicks or reloads verification.
          sawVerification=true;
          state.message=`Waiting for automatic verification for ${item.title} (#${item.id}). Collection will continue when the page is ready; Pause remains available.`;
          continue;
        }
        if(page?.kind==='waiting')continue;
        // Navigation may still expose the previous document. Wait for the
        // expected identity without reloading, accepting, or skipping a page.
        if(page?.kind==='page' && page.source_novel_id!==item.id){
          lastMismatch=page;
          state.message=`Waiting for ${item.title} (#${item.id}); currently reading ${page.source_title} (#${page.source_novel_id}).`;
          continue;
        }
        Core.check(page,item.id);
        state.records.push(page);state.pending=null;captured=true;
        state.message=`Saved ${page.source_title}. ${state.records.length}/${state.queue.length} captured.`;
        await persist();break;
      }
      if(stop)break;
      if(!captured){
        await pause(lastMismatch
          ? `Page identity did not settle after 120 checks. Expected ${item.title} (#${item.id}); read ${lastMismatch.source_title} (#${lastMismatch.source_novel_id}) at ${lastMismatch.novelupdates_url}. No mismatched page was saved. Export a checkpoint and report this message.`
          : sawVerification
            ? 'Verification or page readiness did not finish within 120 checks. Collection paused; captured pages are retained. Check the collection tab, then Resume when ready.'
            : 'Metadata did not become ready. Check the collection tab, then Resume.');
        break;
      }
      if(state.records.length===state.queue.length)continue;
      for(let i=0;i<state.delay*4 && !stop;i++)await sleep(250);
    }
  }catch(error){state.status='paused';state.message=`Stopped: ${error.message}. Captured pages are retained; export a checkpoint.`;}
  finally{running=false;try{await persist();}catch(error){state.message+=' Could not save local progress: '+error.message;}}
}
browser.runtime.onMessage.addListener(async msg=>{
  await ready;
  if(msg.action==='status')return summary();
  if(msg.action==='pause'){await pause('Paused by you. Resume checks the pending page again.');return summary();}
  if(busy)throw new Error('Another action is in progress.');
  busy=true;
  try{
    if(msg.action==='load'){
      if(running)throw new Error('Pause and wait before loading a queue.');
      if(state.records.length)throw new Error('Export and clear existing captures before loading another file.');
      const imported=Core.restore(msg.data);
      state={...emptyState(),...imported,status:'ready',message:'Queue ready. Start runs until completion or a pause.'};
      storedIds.clear();await persist();
    }else if(msg.action==='start'){
      if(running)return summary();
      if(!state.queue.length)throw new Error('Load a queue first.');
      const delay=msg.data?.delay ?? state.delay;
      if(!Number.isInteger(delay)||delay<1||delay>60)throw new Error('Delay must be a whole number from 1 to 60 seconds.');
      state.delay=delay;stop=false;running=true;state.status='running';
      try{await persist();}catch(e){running=false;throw e;}
      void collectBatch();
    }else if(msg.action==='export'){
      if(!state.queue.length)throw new Error('No queue loaded.');
      // Snapshot synchronously: export can run during collection without pausing.
      const payload={report_type:'novelclue_browser_capture',version:1,exported_at:new Date().toISOString(),
        records:state.records.slice(),queue:state.queue.map(r=>({...r})),delay:state.delay};
      const url=URL.createObjectURL(new Blob([JSON.stringify(payload,null,2)],{type:'application/json'}));
      try{await browser.downloads.download({url,filename:'novelclue-browser-capture.json',saveAs:true});}
      finally{setTimeout(()=>URL.revokeObjectURL(url),60000);}
    }else if(msg.action==='clear'){
      if(running)throw new Error('Pause and wait before clearing.');
      await browser.storage.local.remove(state.records.map(r=>recordKey(r.source_novel_id)));
      state=emptyState('Queue cleared.');storedIds.clear();await persist();
    }else throw new Error('Unknown action.');
    return summary();
  }finally{busy=false;}
});
