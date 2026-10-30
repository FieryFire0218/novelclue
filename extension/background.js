let state = {queue:[], records:[], status:'idle', message:'Load a queue to begin.', tabId:null, pending:null};
let running=false, stop=false, busy=false;
const ready = (async () => {
  const saved=await browser.storage.local.get('collector');
  if(saved.collector) {
    state=saved.collector;
    state.tabId=null; state.status='paused';
    state.message='Collector reloaded. Export saved pages or click Start / Resume.';
  }
})();
const sleep=ms=>new Promise(resolve=>setTimeout(resolve,ms));
async function persist() { await browser.storage.local.set({collector:state}); }
function summary() {return {status:state.status,message:state.message,queued:state.queue.length,
  captured:state.records.length,pending:state.pending,running};}
async function pause(message) {stop=true;state.status='paused';state.message=message;await persist();}
async function collectBatch() {
  try {
    let count=0;
    while(!stop && count<5) {
      const done=new Set(state.records.map(r=>r.source_novel_id));
      const item=state.queue.find(r=>!done.has(r.id));
      if(!item) {state.status='complete';state.message='Queue complete. Export captured pages.';break;}
      let sameTab=false;
      if(state.pending===item.id && state.tabId!==null) {
        try {await browser.tabs.get(state.tabId);sameTab=true;} catch (_) {state.tabId=null;}
      }
      state.pending=item.id;state.message=`Loading ${item.title} (${item.id})`;await persist();
      const url=`https://www.novelupdates.com/?p=${item.id}`;
      if(!sameTab) {
        if(state.tabId===null) state.tabId=(await browser.tabs.create({url,active:true})).id;
        else await browser.tabs.update(state.tabId,{url});
      }
      let captured=false;
      for(let attempt=0;attempt<30 && !stop;attempt++) {
        await sleep(2000); if(stop) break;
        const tab=await browser.tabs.get(state.tabId);
        if(tab.status!=='complete') continue;
        const results=await browser.tabs.executeScript(state.tabId,{file:'capture.js',runAt:'document_idle'});
        if(stop) break;
        const page=results[0];
        if(page?.kind==='blocked') {await pause(page.reason);break;}
        if(page?.kind==='waiting') continue;
        Core.check(page,item.id);
        state.records.push(page);state.pending=null;count++;captured=true;
        state.message=`Saved ${page.source_title}. ${count}/5 in this run.`;
        await persist();break;
      }
      if(stop) break;
      if(!captured) {await pause('Page did not become ready within 60 seconds. Check the collector tab, then Resume.');break;}
      if(count<5) {
        // Delay never clicks or reloads a challenge; stop is checked each second.
        for(let i=0;i<15 && !stop;i++) await sleep(1000);
      }
    }
    if(!stop && state.status!=='complete') {
      state.status='paused';state.message='Five-page test finished. Export the results before continuing.';
    }
  } catch(error) {
    state.status='paused';state.message=`Stopped: ${error.message}. Saved pages are retained.`;
  } finally {running=false;await persist();}
}
browser.runtime.onMessage.addListener(async msg=>{
  await ready;
  if(msg.action==='status') return summary();
  if(msg.action==='pause') {await pause('Paused by you. Click Resume to inspect the current page again.');return summary();}
  if(busy) throw new Error('Another action is in progress.');
  busy=true;
  try {
    if(msg.action==='load') {
      if(running) throw new Error('Pause and wait for the run to stop before loading a queue.');
      if(state.records.length) throw new Error('Export saved pages and clear the queue before loading another.');
      state={queue:Core.queue(msg.data),records:[],status:'ready',message:'Queue ready. Each run captures at most five pages.',tabId:null,pending:null};
      await persist();
    } else if(msg.action==='start') {
      if(running) return summary();
      if(!state.queue.length) throw new Error('Load a queue first.');
      stop=false;running=true;state.status='running';
      try {await persist();} catch(e) {running=false;throw e;}
      void collectBatch();
    } else if(msg.action==='export') {
      if(running) throw new Error('Pause and wait for the run to stop before exporting.');
      if(!state.records.length) throw new Error('No pages captured yet.');
      const payload={report_type:'novelclue_browser_capture',version:1,exported_at:new Date().toISOString(),records:state.records};
      const url=URL.createObjectURL(new Blob([JSON.stringify(payload,null,2)],{type:'application/json'}));
      try {await browser.downloads.download({url,filename:'novelclue-browser-capture.json',saveAs:true});}
      finally {setTimeout(()=>URL.revokeObjectURL(url),60000);}
    } else if(msg.action==='clear') {
      if(running) throw new Error('Pause and wait for the run to stop before clearing.');
      state={queue:[],records:[],status:'idle',message:'Queue cleared.',tabId:null,pending:null};await persist();
    } else throw new Error('Unknown action.');
    return summary();
  } finally {busy=false;}
});
