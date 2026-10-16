/** Reproducible, one-request read-only GMGN transport check. No secrets logged. */
import fs from 'node:fs';
import { OpenApiClient } from '/workspace/gmgn-tools/node_modules/gmgn-cli/dist/client/OpenApiClient.js';
import { Agent, ProxyAgent, buildConnector, setGlobalDispatcher } from '/workspace/gmgn-tools/node_modules/undici/index.js';

delete process.env.GMGN_DEBUG;
const publicControl = process.argv.slice(2).includes('--public-control');
if (process.argv.slice(2).some(x => x !== '--public-control')) throw new Error('Only --public-control is supported');
if (!publicControl && !process.env.GMGN_API_KEY) {
  process.stdout.write(JSON.stringify({ status: 'missing_api_key_binding', request_sent: false }) + '\n');
  process.exit(1);
}
const proxy = process.env.HTTPS_PROXY ?? process.env.https_proxy ?? process.env.HTTP_PROXY ?? process.env.http_proxy;
const dispatcher = proxy ? new ProxyAgent(proxy) : new Agent({ connect: buildConnector({ family: 4 }) });
setGlobalDispatcher(dispatcher);
const report = {
  checked_at: new Date().toISOString(), provider: 'GMGN',
  official_client_version: JSON.parse(fs.readFileSync('/workspace/gmgn-tools/node_modules/gmgn-cli/package.json', 'utf8')).version,
  method: 'GET', path: publicControl ? '/v1/market/rank' : '/v1/user/info', read_only: true,
  check: publicControl ? 'official_documented_public_demo' : 'user_api_key',
  user_credentials_sent: !publicControl,
  api_key_binding_present: Boolean(process.env.GMGN_API_KEY), proxy_configured: Boolean(proxy),
  request_contract: 'Official OpenApiClient; X-APIKEY + timestamp seconds + UUID client_id; standard validated TLS',
};
class DiagnosticClient extends OpenApiClient {
  async doFetch(...args) {
    // Bound the one diagnostic request without changing headers, credentials or TLS.
    const [method, , url, headers, body] = args;
    return fetch(url, { method, headers, body: body ?? undefined, signal: AbortSignal.timeout(20000) });
  }
  async parseResponse(method, path, response) {
    const body = await response.text();
    report.http_status = response.status;
    report.content_type = response.headers.get('content-type');
    report.server = response.headers.get('server');
    report.cloudflare_ray = response.headers.get('cf-ray');
    report.response_date = response.headers.get('date');
    report.response_body_bytes = Buffer.byteLength(body);
    const title = /<title>\s*([^<]{0,120})/i.exec(body)?.[1]?.trim();
    report.cloudflare_block_page = /Sorry, you have been blocked/i.test(body) && /cloudflare/i.test(body);
    if (title) report.page_title = title;
    const ip = /Your IP:[\s\S]{0,150}?(\d{1,3}(?:\.\d{1,3}){3})/i.exec(body)?.[1];
    if (ip) report.cloudflare_reported_egress_ipv4 = ip;
    let payload;
    try { payload = JSON.parse(body); } catch { /* Raw response intentionally never logged. */ }
    report.response_is_json = Boolean(payload && typeof payload === 'object');
    report.api_request_succeeded = response.ok && payload?.code === 0;
    report.credentials_validated = report.api_request_succeeded;
    if (typeof payload?.code === 'number') report.api_code = payload.code;
    if (typeof payload?.error === 'string' && /^[A-Z0-9_]{1,64}$/.test(payload.error)) report.api_error_code = payload.error;
    report.status = report.api_request_succeeded ? 'api_access_confirmed'
      : report.cloudflare_block_page ? 'blocked_by_cloudflare'
      : report.response_is_json ? 'api_json_rejection' : 'unexpected_non_json_response';
    return null; // Do not retry any rejection during diagnosis.
  }
}
try {
  const client = new DiagnosticClient({
    apiKey: publicControl ? 'gmgn_solbscbaseethmonadtron' : process.env.GMGN_API_KEY,
    host: 'https://openapi.gmgn.ai',
  });
  if (publicControl) await client.getTrendingSwaps('sol', '1h', { limit: 3 });
  else await client.getUserInfo();
} catch (error) {
  // Error strings can contain URLs or proxy credentials: emit only bounded classification.
  report.status = 'network_or_timeout_error';
  report.error_type = ['TimeoutError', 'AbortError', 'TypeError'].includes(error?.name) ? error.name : 'Error';
  report.credentials_validated = false;
} finally {
  await dispatcher.close();
}
const output = publicControl ? '/workspace/my-project/data/gmgn/resolver_public_control.json'
  : '/workspace/my-project/data/gmgn/resolver_access_diagnosis.json';
fs.mkdirSync('/workspace/my-project/data/gmgn', { recursive: true });
fs.writeFileSync(output, JSON.stringify(report, null, 2) + '\n', { mode: 0o600 });
process.stdout.write(JSON.stringify(report, null, 2) + '\n');
