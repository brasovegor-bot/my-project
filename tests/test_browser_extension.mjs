import fs from 'node:fs';
import assert from 'node:assert/strict';
import crypto from 'node:crypto';
import {createRequire} from 'node:module';
const require=createRequire(import.meta.url);
const {chromium}=require('/opt/codex/runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const {extractTrackerSample}=await import(new URL('../browser_extension/capture.js',import.meta.url));
const root=new URL('..',import.meta.url).pathname.replace(/\/$/,'');
const browser=await chromium.launch({executablePath:'/usr/bin/chromium',headless:true,args:['--no-sandbox']});
try{
 const context=await browser.newContext({acceptDownloads:true,viewport:{width:1000,height:850}});
 const page=await context.newPage();
 const addr='0x'+'1'.repeat(40),tok='0x'+'2'.repeat(40);
 const fixture=`<meta charset="utf-8"><style>.row{width:550px;height:64px;display:flex;gap:15px}.name,.cell{display:block}</style>
 <script>window.clicked=0;document.cookie='test_cookie=PRIVATE_COOKIE'</script>
 <form><input value='PRIVATE_TOKEN'><span>Account balance PRIVATE_BALANCE</span></form>
 <div class='row' data-row-key='trade-001'><a class='name' href='/eth/address/${addr}?auth=PRIVATE_QUERY'>Рома 12</a><a class='cell' href='/eth/token/${tok}?ref=PRIVATE_REF'>INUDEX</a><span class='cell' style='color:rgb(0,200,80)'>0.048 ETH</span><span class='cell'>$4.2K</span><button onclick='window.clicked++'>Buy</button></div>
 <div class='row' data-row-key='trade-002'><a class='name' href='/eth/address/${addr}'>Рома 13</a><a class='cell' href='/eth/token/${tok}'>INUDEX</a><span class='cell'>0.048 ETH</span><span class='cell'>$4.7K</span></div>
 <div class='row'><a href='/eth/address/${addr}'>Unselected</a><a href='/eth/token/${tok}'>OTHER</a><span>PRIVATE_UNSELECTED_AMOUNT</span></div>
 <div hidden><span>Рома 11</span><input value='HIDDEN_SECRET'></div>`;
 await page.route('https://gmgn.ai/**',route=>route.fulfill({status:200,contentType:'text/html',body:fixture}));
 await page.goto('https://gmgn.ai/?chain=eth&token=PRIVATE_URL_TOKEN');
 const selected=[{label:'Рома 12',address:addr},{label:'Рома 13',address:addr},{label:'Рома 11',address:addr}];
 const sample=await page.evaluate(extractTrackerSample,selected);
 assert.equal(sample.visible_row_count,2);assert.equal(sample.monitoring_active,false);
 const serialized=JSON.stringify(sample);
 for(const secret of ['PRIVATE_COOKIE','PRIVATE_TOKEN','PRIVATE_BALANCE','PRIVATE_QUERY','PRIVATE_REF','PRIVATE_UNSELECTED_AMOUNT','HIDDEN_SECRET','PRIVATE_URL_TOKEN'])assert(!serialized.includes(secret),secret);
 assert(serialized.includes('trade-001'));assert(serialized.includes('0.048 ETH'));assert(serialized.includes('$4.2K'));
 assert.equal(await page.evaluate(()=>window.clicked),0);
 assert.deepEqual(sample.rows.map(r=>r.wallet_identity_verified),[false,false]);
 const wrong=await context.newPage();await wrong.setContent('<div>Not GMGN</div>');
 await assert.rejects(()=>wrong.evaluate(extractTrackerSample,selected));
 const install=await context.newPage();const errors=[];install.on('pageerror',e=>errors.push(e.message));
 await install.setContent(fs.readFileSync(root+'/data/gmgn/install_browser_extension.html','utf8'));
 let pending=install.waitForEvent('download');await install.locator('#download').click();let dl=await pending;
 assert.equal(dl.suggestedFilename(),'GMGN_Tracker_Check.zip');
 let bytes=fs.readFileSync(await dl.path()),expected=fs.readFileSync(root+'/data/gmgn/GMGN_Tracker_Check.zip');
 assert.equal(crypto.createHash('sha256').update(bytes).digest('hex'),crypto.createHash('sha256').update(expected).digest('hex'));
 pending=install.waitForEvent('download');await install.locator('#save').click();dl=await pending;
 const reopened=await context.newPage();await reopened.setContent(fs.readFileSync(await dl.path(),'utf8'));
 pending=reopened.waitForEvent('download');await reopened.locator('#download').click();dl=await pending;
 assert.equal(fs.readFileSync(await dl.path()).length,expected.length);
 await install.setViewportSize({width:390,height:844});
 assert.equal(await install.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
 assert.deepEqual(errors,[]);
 await install.screenshot({path:root+'/data/gmgn/browser_install_preview.png',fullPage:false});
 fs.writeFileSync(root+'/data/gmgn/browser_checker_validation.json',JSON.stringify({fixture_only:true,synthetic_rows_captured:2,privacy_checks_passed:true,no_mutation:true,wrong_host_rejected:true,zip_download_matches:true,saved_html_download_works:true,live_GMGN_verified:false},null,2));
 console.log('PASS: 2 selected rows, hidden/form/query/cookie/foreign-row data excluded, no clicks/mutations, wrong-host rejection, exact ZIP download, saved HTML reopens, mobile width. Live GMGN is not tested.');
}finally{await browser.close();}
