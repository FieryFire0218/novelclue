const assert=require('node:assert/strict');
const Core=require('../extension/core.js');
assert.deepEqual(Core.queue([4052,14]).map(r=>r.id),[4052,14]);
assert.throws(()=>Core.queue([1,1]));assert.throws(()=>Core.queue([true]));
assert.throws(()=>Core.queue([-1]));assert.throws(()=>Core.queue(['4052']));
assert.throws(()=>Core.queue({results:[]}));
const report={report_type:'novel_readiness_audit',results:[
 {source_novel_id:1,normal_candidate:false,next_action:'resolve_url'},
 {source_novel_id:2,normal_candidate:true,next_action:'resolve_url'},
 {source_novel_id:3,normal_candidate:true,next_action:'no_metadata_gap'}]};
assert.deepEqual(Core.queue(report).map(r=>r.id),[2,1]);
assert.equal(Core.canonical('https://novelupdates.com/series/example'),'https://www.novelupdates.com/series/example/');
for(const u of ['https://evil.com/series/a/','https://www.novelupdates.com/?p=1','https://user@www.novelupdates.com/series/a/'])assert.throws(()=>Core.canonical(u));
assert.throws(()=>Core.check({kind:'blocked'},4052));
assert.throws(()=>Core.check({kind:'page',source_novel_id:1},4052));
console.log('Queue and identity assertions passed.');
