const assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs'),path=require('node:path');
const root=path.join(__dirname,'../extension');
const manifest=JSON.parse(fs.readFileSync(path.join(root,'manifest.json')));
assert.equal(manifest.browser_action.default_popup,undefined);
assert.ok(manifest.background.scripts.includes('open_collector.js'));
let click,remove,created=0,activated=[];
const browser={browserAction:{onClicked:{addListener:f=>click=f}},
 runtime:{getURL:p=>'moz-extension://test/'+p},
 tabs:{onRemoved:{addListener:f=>remove=f},
 create:async args=>{assert.equal(args.url,'moz-extension://test/popup.html');return {id:++created};},
 update:async(id,args)=>{assert.equal(args.active,true);activated.push(id);}}};
vm.runInNewContext(fs.readFileSync(path.join(root,'open_collector.js'),'utf8'),{browser});
(async()=>{await click();await click();assert.equal(created,1);assert.deepEqual(activated,[1]);
 remove(1);await click();assert.equal(created,2);console.log('Collector tab open, reuse, and reopen checks passed.');})().catch(e=>{console.error(e);process.exit(1)});
