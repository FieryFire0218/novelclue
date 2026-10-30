const {JSDOM}=require('jsdom'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const code=fs.readFileSync(path.join(__dirname,'../extension/capture.js'),'utf8');
const html=`<title>Example</title><link rel="canonical" href="https://www.novelupdates.com/series/example/">
<input id="mypostid" value="4052"><nav>PRIVATE ACCOUNT NAVIGATION</nav>
<div class="seriestitlenu">Example</div><div id="showlang">Chinese</div>
<div id="seriesgenre"><a class="genre" href="/genre/xianxia/">Xianxia</a></div>
<div id="showauthors"><a>Author</a></div>
<div id="editdescription"><p onclick="alert(1)">First paragraph.</p><script>SECRET_SCRIPT</script>
<form><input value="SECRET_TOKEN"></form><p>Second paragraph.</p><div class="editmsg">Private edit controls</div></div>
<span class="uvotes">(4.3 / 5.0, 100 votes)</span><b class="rlist">2,500</b>
<div id="editstatus">149 Chapters + 5 Extras (Completed)</div>`;
function capture(text){const dom=new JSDOM(text,{url:'https://www.novelupdates.com/series/example/',runScripts:'outside-only'});const result=dom.window.eval(code);dom.window.close();return result;}
const p=capture(html);assert.equal(p.kind,'page');assert.equal(p.source_novel_id,4052);
for(const secret of ['SECRET','onclick','<script','<form','Private edit','PRIVATE ACCOUNT'])assert.ok(!p.html.includes(secret),secret);
assert.ok(p.html.includes('First paragraph.'));assert.ok(p.html.includes('value="4052"'));
assert.equal(capture(html.replace('<title>Example</title>','<title>Just a moment...</title>')).kind,'blocked');
assert.equal(capture('<title>Empty</title>').kind,'waiting');
if(process.argv[2])fs.writeFileSync(process.argv[2],JSON.stringify({report_type:'novelclue_browser_capture',version:1,records:[p]}));
console.log('DOM capture assertions passed, including metadata preservation and removal of controls/scripts.');
