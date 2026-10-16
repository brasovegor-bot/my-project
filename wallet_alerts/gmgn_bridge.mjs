// Read-only transport using the installed official GMGN client. No CLI config,
// dotenv or credential logs; only this fixed endpoint can leave the process.
import fs from 'node:fs';
import {Agent,buildConnector,ProxyAgent,setGlobalDispatcher} from '/workspace/gmgn-tools/node_modules/undici/index.js';
import {OpenApiClient} from '/workspace/gmgn-tools/node_modules/gmgn-cli/dist/client/OpenApiClient.js';
delete process.env.GMGN_DEBUG;
const proxy=process.env.HTTPS_PROXY||process.env.https_proxy||process.env.HTTP_PROXY||process.env.http_proxy;
const dispatcher=proxy?new ProxyAgent(proxy):new Agent({connect:buildConnector({family:4})});
setGlobalDispatcher(dispatcher);
let transport={};
const originalFetch=globalThis.fetch;
globalThis.fetch=async(input,init)=>{
  const url=new URL(input);
  if(url.origin!=='https://openapi.gmgn.ai'||url.pathname!=='/v1/user/wallet_activity'||init.method!=='GET')
    throw Error('read_only_guard');
  const response=await originalFetch(input,{...init,signal:AbortSignal.timeout(25000),redirect:'error'});
  transport={http_status:response.status,cf_ray:response.headers.get('cf-ray')};
  const text=await response.clone().text();
  transport.cloudflare_block=/Sorry, you have been blocked/i.test(text)&&/cloudflare/i.test(text);
  return response;
};
try{
  const args=JSON.parse(fs.readFileSync(0,'utf8'));
  if(!['eth','bsc','base','arbitrum','hyperevm','robinhood','arc','stable','sol'].includes(args.chain)
      ||typeof args.wallet!=='string'||!process.env.GMGN_API_KEY)throw Error('configuration');
  const extra={limit:20,type:['buy','sell']};
  if(args.cursor!=null)extra.cursor=args.cursor;
  const client=new OpenApiClient({apiKey:process.env.GMGN_API_KEY,host:'https://openapi.gmgn.ai'});
  const data=await client.getWalletActivity(args.chain,args.wallet,extra);
  process.stdout.write(JSON.stringify({ok:true,data}));
}catch(error){
  const result={ok:false,...transport,kind:transport.cloudflare_block?'cloudflare_block':'request_failed'};
  if(Number.isInteger(error.status))result.http_status=error.status;
  if(Number.isFinite(error.resetAtUnix))result.retry_at=error.resetAtUnix;
  if(typeof error.apiError==='string'&&/^[A-Z_0-9]{1,80}$/.test(error.apiError))result.api_error=error.apiError;
  // Never include error.message, response body, URLs, headers or credentials.
  process.stdout.write(JSON.stringify(result));
  process.exitCode=1;
}finally{
  await dispatcher.close();
}
