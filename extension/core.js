/* Pure queue and identity checks, shared with the offline tests. */
const Core = {
  canonical(value) {
    const u = new URL(value);
    if (u.protocol !== 'https:' || !['www.novelupdates.com', 'novelupdates.com'].includes(u.hostname) ||
        u.port || u.username || u.password || u.search || u.hash || !/^\/series\/[^/]+\/?$/.test(u.pathname))
      throw new Error('Invalid canonical series URL.');
    return 'https://www.novelupdates.com' + u.pathname.replace(/\/$/, '') + '/';
  },
  queue(data) {
    let rows;
    if (Array.isArray(data)) rows = data.map(id => ({source_novel_id: id}));
    else if (data && data.report_type === 'novel_readiness_audit' && Array.isArray(data.results)) {
      rows = data.results.filter(r => ['resolve_url','stage_import','enrich_metadata'].includes(r.next_action));
      rows = [...rows].sort((a,b) => Number(b.normal_candidate === true) - Number(a.normal_candidate === true));
    } else throw new Error('Choose the readiness audit JSON or a JSON array of numeric IDs.');
    const seen = new Set();
    const queue = rows.map(r => {
      const id = r.source_novel_id;
      if (!Number.isSafeInteger(id) || id <= 0 || seen.has(id)) throw new Error('Invalid or duplicate source ID.');
      seen.add(id);
      return {id, title: typeof r.source_title === 'string' ? r.source_title : `Novel ${id}`};
    });
    if (!queue.length || queue.length > 10000) throw new Error('Queue must contain 1–10,000 IDs.');
    return queue;
  },
  check(page, expected) {
    if (!page || page.kind !== 'page') throw new Error(page?.reason || 'No series page found.');
    if (page.source_novel_id !== expected) throw new Error('Page ID does not match the queued novel.');
    page.novelupdates_url = Core.canonical(page.novelupdates_url);
    if (!page.html || page.html.length > 1000000) throw new Error('Page metadata is empty or too large.');
    return page;
  }
};
if (typeof module !== 'undefined') module.exports = Core;

// New exports are also restartable checkpoints; old exports lack a queue.
Core.restore = function(data) {
  if(data?.report_type !== 'novelclue_browser_capture')return {queue:Core.queue(data),records:[]};
  if(data.version!==1 || !Array.isArray(data.queue) || !Array.isArray(data.records))
    throw new Error('This capture has no resumable queue. Load a new queue instead.');
  const queue=Core.queue(data.queue.map(r=>r.id));
  queue.forEach((r,i)=>r.title=typeof data.queue[i].title==='string'?data.queue[i].title:r.title);
  const ids=new Set(queue.map(r=>r.id)),seen=new Set();
  let bytes=0;
  for(const record of data.records){
    if(!ids.has(record.source_novel_id)||seen.has(record.source_novel_id))throw new Error('Invalid checkpoint ID or duplicate record.');
    if(record.capture_format!=='novelclue_metadata_fragment_v1'||!Number.isFinite(Date.parse(record.captured_at)))
      throw new Error('Invalid checkpoint capture metadata.');
    Core.check({...record,kind:'page'},record.source_novel_id);
    bytes+=record.html.length;if(bytes>200000000)throw new Error('Checkpoint exceeds 200 MB.');
    seen.add(record.source_novel_id);
  }
  return {queue,records:data.records,delay:Number.isInteger(data.delay)&&data.delay>=1&&data.delay<=60?data.delay:2};
};
