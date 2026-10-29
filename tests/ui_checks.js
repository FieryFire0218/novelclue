const fs = require('fs');
const vm = require('vm');
const assert = require('assert/strict');
const html = fs.readFileSync(require('path').join(__dirname,'../src/templates/index.html'),'utf8');
const script = html.match(/<script>([\s\S]*?)<\/script>/)[1];
const elements = new Map();
function element(id) {
 if (!elements.has(id)) elements.set(id,{value:'',disabled:false,innerHTML:'',textContent:'',className:'',listeners:{},focus(){},addEventListener(k,f){this.listeners[k]=f;},insertAdjacentHTML(_,s){this.innerHTML=s+this.innerHTML;}});
 return elements.get(id);
}
const ctx=vm.createContext({document:{getElementById:element},fetch:async()=>({ok:true,json:async()=>({title:'<img src=x onerror=alert(1)>',author:null,translator:null,chapters:null,rating5:null,genres:[]})})});
vm.runInContext(script,ctx);
assert.equal(vm.runInContext('renderStars(0)',ctx),'0 stars');
assert.equal(vm.runInContext('renderStars(null)',ctx),'Unknown');
assert.equal(vm.runInContext('displayValue(0)',ctx),'0');
assert.equal(vm.runInContext('formatChapters({original_chapters_total:154, original_chapters_main:149, original_chapters_extra:5})',ctx), '154 chapters · 149 main + 5 extras');
assert.equal(vm.runInContext('formatPublication({publication_status:"completed"})',ctx), 'Completed');
assert.equal(vm.runInContext('formatPublication({publication_status:"ongoing",main_publication_status:"completed"})',ctx), 'Ongoing · Main story: Completed');
(async()=>{
 await vm.runInContext('revealAnswer()',ctx);
 const result=element('results').innerHTML;
 assert(result.includes('&lt;img'));
 assert(!result.includes('<img'));
 assert(!result.includes('Translator:')); 
 assert(result.includes('Original chapters:</strong> Total unknown'));
 assert(element('guessBtn').disabled);
 vm.runInContext('resetGame()',ctx);
 ctx.fetch=async()=>({ok:false,json:async()=>({error:'No novels available'})});
 await vm.runInContext('revealAnswer()',ctx);
 assert.equal(element('statusMessage').textContent,'No novels available');
 assert.equal(element('guessBtn').disabled,false);
 console.log('PASS: JS rendering, unknown and zero values, escaped source text, answer-error handling.');
})().catch(e=>{console.error(e);process.exitCode=1;});
