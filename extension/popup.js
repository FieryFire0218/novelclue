const $=id=>document.getElementById(id);
function show(s){$('counts').textContent=`${s.captured} captured / ${s.queued} queued`;
  $('status').textContent=s.message;$('start').disabled=s.running;$('file').disabled=s.running;
  $('export').disabled=s.running||!s.captured;$('clear').disabled=s.running;}
async function action(action,data){try{$('error').textContent='';show(await browser.runtime.sendMessage({action,data}));}
catch(e){$('error').textContent=e.message;}}
for(const id of ['start','pause','export']) $(id).addEventListener('click',()=>action(id));
$('clear').addEventListener('click',()=>{if(confirm('Clear locally saved pages and queue? Export first.')) action('clear');});
$('file').addEventListener('change',async()=>{try{const file=$('file').files[0];if(!file)return;
if(file.size>10000000)throw new Error('Queue file exceeds 10 MB.');await action('load',JSON.parse(await file.text()));}
catch(e){$('error').textContent=e.message;}});
action('status');setInterval(async()=>{try{show(await browser.runtime.sendMessage({action:'status'}));}catch(_){}},1000);
