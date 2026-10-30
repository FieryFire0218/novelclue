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
