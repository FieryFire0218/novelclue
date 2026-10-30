/* Returns only the public metadata elements used by our existing Python parser. */
(() => {
  const title = document.title.toLowerCase();
  if (['just a moment','access denied','attention required','verify you are human','security verification']
      .some(t => title.includes(t))) return {kind:'blocked', reason:'Verification detected. Complete it manually if possible, then click Resume.'};
  const ids = document.querySelectorAll('input#mypostid');
  const canon = document.querySelectorAll('link[rel="canonical"]');
  const name = document.querySelector('.seriestitlenu');
  if (ids.length !== 1 || canon.length !== 1 || !name || !document.querySelector('#editdescription') ||
      !document.querySelector('.rlist')) return {kind:'waiting', reason:'Series metadata is not ready.'};
  if (!/^[1-9]\d*$/.test(ids[0].value)) return {kind:'invalid', reason:'Invalid page ID.'};
  const sourceId = Number(ids[0].value);
  // Rebuild a static metadata fragment: no scripts, forms, tokens, event handlers,
  // cookies, navigation menus or account controls are exported.
  const allowed = new Set(['DIV','SPAN','A','BR','P','B','STRONG','EM','UL','OL','LI','I']);
  function clean(node) {
    if (node.nodeType === Node.TEXT_NODE) return document.createTextNode(node.textContent);
    if (node.nodeType !== Node.ELEMENT_NODE || ['SCRIPT','STYLE','INPUT','BUTTON','IFRAME','FORM','NOSCRIPT'].includes(node.tagName)
        || node.classList.contains('editmsg')) return document.createTextNode('');
    const copy = document.createElement(allowed.has(node.tagName) ? node.tagName : 'span');
    for (const attr of ['id','class']) if (node.hasAttribute(attr)) copy.setAttribute(attr,node.getAttribute(attr));
    for (const child of node.childNodes) copy.appendChild(clean(child));
    return copy;
  }
  const wrapper = document.createElement('div');
  const link = document.createElement('link'); link.rel='canonical'; link.href=canon[0].href;
  wrapper.appendChild(link);
  const marker = document.createElement('input'); marker.id='mypostid'; marker.value=String(sourceId);
  marker.setAttribute('value',String(sourceId)); wrapper.appendChild(marker);
  for (const selector of ['.seriestitlenu','#showlang','#seriesgenre','#showtags','#showauthors',
      '#editassociated','#editdescription','.uvotes','.rlist','#editstatus']) {
    const node=document.querySelector(selector); if(node) wrapper.appendChild(clean(node));
  }
  return {kind:'page', source_novel_id:sourceId, novelupdates_url:link.href,
    source_title:name.textContent.trim(), captured_at:new Date().toISOString(),
    capture_format:'novelclue_metadata_fragment_v1', html:wrapper.innerHTML};
})();
