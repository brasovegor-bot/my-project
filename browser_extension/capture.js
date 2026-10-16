// Self-contained function executed ONLY after a user's click, on a GMGN tab.
// Reads visible row structure. No fetch, cookies, storage, clicks or mutations.
export function extractTrackerSample(priorities) {
  const host = location.hostname;
  if (!['gmgn.ai', 'www.gmgn.ai'].includes(host) || location.protocol !== 'https:')
    throw new Error('Открой вкладку https://gmgn.ai с Wallet Tracker.');
  const normalize = value => String(value || '').replace(/\s+/g, ' ').trim();
  const clip = (value, max = 600) => normalize(value).slice(0, max);
  const visible = el => {
    const rect = el.getBoundingClientRect(), style = getComputedStyle(el);
    return rect.width > 0 && rect.height > 0 && rect.bottom > 0 && rect.top < innerHeight
      && rect.right > 0 && rect.left < innerWidth && style.visibility !== 'hidden' && style.display !== 'none';
  };
  const names = new Map();
  for (const wallet of priorities) {
    const label = normalize(wallet.label);
    if (!names.has(label)) names.set(label, []);
    names.get(label).push(wallet);
  }
  const safeLink = href => {
    try {
      const url = new URL(href, location.href);
      if (url.protocol !== 'https:') return null;
      // Only public identity paths; never capture query parameters or fragments.
      if (['gmgn.ai', 'www.gmgn.ai'].includes(url.hostname)
          && /^\/[a-z0-9_-]+\/(?:token|address)\/[a-zA-Z0-9_-]+\/?$/.test(url.pathname))
        return url.origin + url.pathname;
      if (/^\/tx\/0x[a-fA-F0-9]{64}\/?$/.test(url.pathname))
        return url.origin + url.pathname;
    } catch {}
    return null;
  };
  const tokenLinks = el => [...el.querySelectorAll('a[href]')]
    .map(a => safeLink(a.getAttribute('href'))).filter(href => href && /\/token\//.test(href));
  function tree(el, depth = 0, budget = {left: 110}) {
    if (budget.left-- <= 0 || depth > 7 || ['SCRIPT','STYLE','INPUT','TEXTAREA','SELECT','IFRAME','FORM'].includes(el.tagName)
        || getComputedStyle(el).display === 'none' || getComputedStyle(el).visibility === 'hidden') return null;
    const node = {tag: el.tagName.toLowerCase()};
    const attrs = {};
    for (const name of ['class','role','data-testid','data-row-key','data-tx-hash','data-address','data-chain']) {
      const value = el.getAttribute(name);
      if (value !== null) attrs[name] = clip(value, 200);
    }
    const href = el.tagName === 'A' ? safeLink(el.getAttribute('href')) : null;
    if (href) attrs.href = href;
    if (Object.keys(attrs).length) node.attributes = attrs;
    node.color = getComputedStyle(el).color;
    const direct = [...el.childNodes].filter(n => n.nodeType === Node.TEXT_NODE).map(n => n.textContent).join(' ');
    if (normalize(direct)) node.text = clip(direct, 200);
    const children = [...el.children].map(c => tree(c, depth + 1, budget)).filter(Boolean);
    if (children.length) node.children = children;
    return node;
  }
  const hits = [], seen = new Set(), matchedLabels = new Set();
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  let text, visited = 0;
  while ((text = walker.nextNode()) && visited++ < 60000 && hits.length < 24) {
    const label = normalize(text.textContent), wallets = names.get(label), el = text.parentElement;
    if (!wallets || !el || !visible(el) || el.closest('input,textarea,select,script,style,form')) continue;
    matchedLabels.add(label);
    let row = el;
    // A sample requires a nearby token link and a compact visible row; never
    // capture body/main/header or the entire account page to get more context.
    for (let level = 0; row && level < 9; level++, row = row.parentElement) {
      if (['BODY','HTML','MAIN','HEADER','NAV','FORM'].includes(row.tagName)) break;
      const rect = row.getBoundingClientRect();
      if (rect.height > 220) break;
      const links = tokenLinks(row);
      if (rect.width < 220 || rect.height < 18 || !links.length) continue;
      const rowText = clip(row.innerText, 1000);
      // Exclude containers combining multiple tracked wallets.
      const exactWalletNodes = [...row.querySelectorAll('*')].filter(n => n.children.length === 0 && names.has(normalize(n.textContent)));
      if (new Set(exactWalletNodes.map(n => normalize(n.textContent))).size > 1) break;
      if (seen.has(row)) break;
      seen.add(row);
      hits.push({matched_label: label, candidate_wallets: wallets.map(w => ({label: w.label, address: w.address})),
        wallet_identity_verified: false, event_identity_verified: false,
        row_text: rowText, token_links: [...new Set(links)], structure: tree(row)});
      break;
    }
  }
  const chain = new URL(location.href).searchParams.get('chain');
  return {
    format: 'gmgn-visible-tracker-sample-v1', captured_at: new Date().toISOString(),
    source: {host, path: location.pathname,
      page_chain_hint: ['eth','sol','bsc','base','arbitrum','hyperevm','robinhood','arc','stable'].includes(chain) ? chain : null},
    selected_wallet_count: priorities.length, matched_labels: [...matchedLabels],
    visible_row_count: hits.length, rows: hits, completeness: 'visible_sample_only',
    monitoring_active: false,
    note: 'Diagnostic sample only. Wallet/transaction identity, side, amount units and capitalization time require mapping verification before notifications.'
  };
}
