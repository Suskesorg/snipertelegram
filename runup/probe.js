// READ-ONLY probe for the runup.fun $RUNNER sale.
// Needs no private key and sends no transactions. Only reads public data.
// Usage: node probe.js > probe-output.txt

const API = 'https://blockscout.injective.network/api/v2';
const SALE = '0x8399aF15A225314d7bE75BEeBf1E83D001380074'.toLowerCase();
const IMPL = '0xf981aD766B0A7e2F3668Eb8749Ea1b8A1c0C8A8d';
const BUY_SEL = '0x8906b078';
const SITE = 'https://runup.fun';

async function getJson(url) {
  const r = await fetch(url, { headers: { accept: 'application/json' } });
  if (!r.ok) throw new Error(`${r.status} ${url}`);
  return r.json();
}
async function getText(url) {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`${r.status} ${url}`);
  return r.text();
}
const words = (hex) => (hex.slice(10).match(/.{1,64}/g) || []);

async function saleTxs(maxPages = 6) {
  const out = [];
  let params = '';
  for (let i = 0; i < maxPages; i++) {
    const j = await getJson(`${API}/addresses/${SALE}/transactions?filter=to${params}`);
    out.push(...j.items);
    if (!j.next_page_params) break;
    params = '&' + new URLSearchParams(j.next_page_params).toString();
  }
  return out;
}

async function section1(txs) {
  console.log('\n===== 1. CALLS TO THE SALE CONTRACT =====');
  const bySel = {};
  for (const t of txs) {
    const sel = (t.raw_input || '0x').slice(0, 10);
    bySel[sel] ??= { n: 0, ok: 0, ex: t.hash };
    bySel[sel].n++;
    if (t.status === 'ok') bySel[sel].ok++;
  }
  for (const [s, v] of Object.entries(bySel)) console.log(`${s}  calls=${v.n}  succeeded=${v.ok}  example=${v.ex}`);

  const buys = txs.filter((t) => (t.raw_input || '').startsWith(BUY_SEL));
  console.log(`\n--- ${buys.length} calls with ${BUY_SEL}; showing up to 6 (succeeded first) ---`);
  buys.sort((a, b) => (a.status === 'ok' ? -1 : 1) - (b.status === 'ok' ? -1 : 1));
  for (const t of buys.slice(0, 6)) {
    console.log(`\nhash=${t.hash} from=${t.from?.hash} status=${t.status} result=${t.result} value=${t.value} time=${t.timestamp}`);
    console.log(`revert_reason=${JSON.stringify(t.revert_reason ?? null)}`);
    console.log(`raw_input length (bytes)=${(t.raw_input.length - 2) / 2}`);
    words(t.raw_input).forEach((w, i) => console.log(`  word[${i}] ${w}  (=${BigInt('0x' + w)})`));
  }
  return buys;
}

async function section2(buys) {
  console.log('\n===== 2. HOW BUYERS PAY (approvals to the sale contract) =====');
  const wallets = [...new Set(buys.map((t) => t.from?.hash))].slice(0, 6);
  const tokens = new Set();
  for (const w of wallets) {
    try {
      const j = await getJson(`${API}/addresses/${w}/transactions`);
      for (const t of j.items) {
        const inp = t.raw_input || '';
        if (inp.startsWith('0x095ea7b3')) {
          const spender = '0x' + inp.slice(34, 74);
          const amt = BigInt('0x' + inp.slice(74, 138));
          console.log(`wallet=${w} approve token=${t.to?.hash} spender=${spender} amount=${amt} status=${t.status} spenderIsSale=${spender.toLowerCase() === SALE}`);
          if (spender.toLowerCase() === SALE) tokens.add(t.to?.hash);
        }
      }
    } catch (e) { console.log(`wallet ${w}: ${e.message}`); }
  }
  for (const tk of tokens) {
    try {
      const j = await getJson(`${API}/tokens/${tk}`);
      console.log(`PAYMENT TOKEN? ${tk} name=${j.name} symbol=${j.symbol} decimals=${j.decimals}`);
    } catch (e) { console.log(`token ${tk}: ${e.message}`); }
  }
  if (!tokens.size) console.log('No approvals to the sale contract found in these wallets.');
}

async function section3() {
  console.log('\n===== 3. FUNCTION SELECTORS IN THE IMPLEMENTATION BYTECODE =====');
  try {
    const j = await getJson(`${API}/smart-contracts/${IMPL}`);
    const code = (j.deployed_bytecode || '').toLowerCase();
    const sels = [...new Set([...code.matchAll(/63([0-9a-f]{8})(?=14|81)/g)].map((m) => m[1]))];
    console.log(`bytecode bytes=${code.length / 2}; candidate selectors:\n${sels.join(' ')}`);
    console.log(`contains ${BUY_SEL.slice(2)}: ${code.includes(BUY_SEL.slice(2))}`);
  } catch (e) { console.log(`could not read bytecode: ${e.message}`); }
}

async function section4() {
  console.log('\n===== 4. FRONTEND JAVASCRIPT =====');
  let html;
  try { html = await getText(SITE); } catch (e) { console.log(e.message); return; }
  const queue = [...html.matchAll(/(?:src|href)="([^"]+\.js)"/g)].map((m) => new URL(m[1], SITE).href);
  const seen = new Set();
  const hits = new Set();
  while (queue.length && seen.size < 200) {
    const url = queue.shift();
    if (seen.has(url)) continue;
    seen.add(url);
    let js;
    try { js = await getText(url); } catch { continue; }
    for (const m of js.matchAll(/["'](\/?_next\/static\/[^"']+\.js)["']/g)) queue.push(new URL(m[1].replace(/^\/?/, '/'), SITE).href);
    for (const m of js.matchAll(/static\/chunks\/[^"']+?\.js/g)) queue.push(new URL('/_next/' + m[0], SITE).href);
    const low = js.toLowerCase();
    for (const key of [SALE.slice(2), BUY_SEL.slice(2), 'e2906863a4dc9261b1d0c25b5ef983c84130d893']) {
      let i = low.indexOf(key);
      while (i !== -1) {
        hits.add(`[${key.slice(0, 8)}] ${url}\n  ...${js.slice(Math.max(0, i - 400), i + 400).replace(/\s+/g, ' ')}...`);
        i = low.indexOf(key, i + 1);
      }
    }
    // ABI function entries
    for (const m of js.matchAll(/\{[^{}]{0,600}?type:\s*["']function["'][^{}]{0,600}?\}/g)) {
      if (/name:\s*["'](\w+)["']/.test(m[0]) && /stateMutability/.test(m[0])) {
        const ctx = js.slice(Math.max(0, m.index - 600), m.index + m[0].length + 600).replace(/\s+/g, ' ');
        if (!/transferFrom|allowance|totalSupply/.test(ctx) || /buy|purchase|phase|sale|curve|whitelist|found/i.test(ctx)) hits.add(`[abi] ${url}\n  ${ctx}`);
      }
    }
    for (const m of js.matchAll(/["'](\w*(?:buy|purchase|phase|isOpen|saleOpen|founding|whitelist|quote|getAmountOut|tokensFor)\w*)["']/gi)) hits.add(`[name] ${m[1]}  (${url.split('/').pop()})`);
  }
  console.log(`scanned ${seen.size} JS files`);
  for (const h of [...hits].slice(0, 150)) console.log(h.slice(0, 2500) + '\n');
}

(async () => {
  console.log(`probe run at ${new Date().toISOString()}`);
  let buys = [];
  try { const txs = await saleTxs(); buys = await section1(txs); } catch (e) { console.log('section 1 failed:', e.message); }
  try { await section2(buys); } catch (e) { console.log('section 2 failed:', e.message); }
  await section3();
  await section4();
  console.log('\n===== DONE =====');
})();
