"""Render a private standalone wallet-priority checklist.

Input is our validated wallet configuration, not an assumed GMGN export schema.
The GMGN source inventory must be obtained separately; an activity feed alone
does not establish that all followed wallets are present.
"""
import argparse
import hashlib
import html
import json
from pathlib import Path

from .core import load_wallets


def render(wallets, source, complete=False, note=''):
    records = [dict(chain=w.chain, address=w.address, label=w.label, priority=w.priority)
               for w in sorted(wallets.values(), key=lambda w: (w.label.casefold(), w.chain, w.address))]
    identity = hashlib.sha256(json.dumps([(r['chain'],r['address']) for r in records]).encode()).hexdigest()[:20]
    data = json.dumps(dict(wallets=records, source=source, complete=bool(complete),
                           identity=identity, note=note), ensure_ascii=False).replace('<','\\u003c')
    return TEMPLATE.replace('__DATA__',data).replace('__SOURCE__',html.escape(source))


TEMPLATE = r'''<!doctype html><html lang="ru"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>GMGN · Выбор кошельков для уведомлений</title>
<style>
:root{color-scheme:dark;font:16px/1.6 system-ui;background:#0c1422;color:#e9f0fa}*{box-sizing:border-box}body{margin:0;padding:28px}main{max-width:1100px;margin:auto}h1{font-size:28px;margin:8px 0}p,.muted{color:#9daec6}.tag{color:#4cdeba;font-size:12px;letter-spacing:2px}.panel{background:#142035;border:1px solid #293b54;border-radius:16px;padding:20px;margin-top:18px}.controls{display:flex;gap:10px;align-items:center;flex-wrap:wrap}button,input[type=search]{font:inherit;border-radius:8px;border:1px solid #3c506d;padding:10px 14px;background:#1b2d45;color:#eff5ff}button{cursor:pointer}button.primary{background:#42d7b1;color:#08261d;font-weight:700}button:disabled{opacity:.4;cursor:default}input[type=search]{flex:1;min-width:180px}input[type=checkbox]{accent-color:#42d7b1;width:20px;height:20px;flex-shrink:0}.wallet{display:flex;gap:14px;align-items:flex-start;border-bottom:1px solid #293b54;padding:15px 0}.wallet:last-child{border-bottom:0}.wallet>div{min-width:0}.name{font-weight:650;overflow-wrap:anywhere}.address{font:12px/1.7 ui-monospace,monospace;color:#a3b8d6;overflow-wrap:anywhere}.chain{font-size:12px;color:#42d7b1}.warning{border-left:3px solid #edbc61;padding:10px 14px;color:#e7c78e;background:#2b251b;border-radius:8px;margin:14px 0}#status{min-height:25px}.help{font-size:14px}.summary{display:flex;justify-content:space-between;gap:10px;flex-wrap:wrap}.empty{padding:30px 0;color:#a3b8d6}@media(max-width:600px){body{padding:12px}.panel{padding:14px}h1{font-size:23px}button{font-size:14px}}
</style><main><div class="tag">GMGN / WALLET TRACKER</div>
<h1>Кого отслеживать</h1><p>Отметь кошельки, покупки и продажи которых должны приходить в Telegram.</p>
<div class="panel"><div class="summary"><span>Источник: __SOURCE__</span><b id="count"></b></div>
<div id="coverage" class="warning"></div><p id="note" class="help"></p>
<div class="controls"><input type="search" id="search" placeholder="Найти по имени или адресу" aria-label="Найти кошелёк"><label><input type="checkbox" id="selected-only"> Только выбранные</label></div>
<div class="controls" style="margin-top:12px"><button id="select-visible">Отметить показанные</button><button id="clear">Снять все галочки</button></div>
<div id="list"></div></div><div class="panel"><div class="controls">
<button id="export" class="primary">Скачать мой выбор</button><button id="save-page">Сохранить страницу</button>
</div><p id="status" role="status"></p><div class="help muted">После выбора нажми «Скачать мой выбор» и прикрепи небольшой файл GMGN_PRIORITIES.json к чату. Это сохранит настройки для бота; сама страница сообщения не отправляет. Секретов и API-ключей в файле нет.</div></div></main>
<script id="wallet-data" type="application/json">__DATA__</script>
<script>
(()=>{'use strict';
const payload=JSON.parse(document.querySelector('#wallet-data').textContent),wallets=payload.wallets;
const storageKey='gmgn-priorities-v1-'+payload.identity,chosen=new Set();
const key=w=>w.chain+':'+w.address;
let stored=null;try{stored=JSON.parse(localStorage.getItem(storageKey));}catch{}
for(const w of wallets)if(Array.isArray(stored)?stored.includes(key(w)):w.priority)chosen.add(key(w));
const note=document.querySelector('#note');note.textContent=payload.note;
const coverage=document.querySelector('#coverage');
coverage.textContent=wallets.length===0?'Список ещё не получен из GMGN. Ноль показанных кошельков не означает, что твой Wallet Tracker пуст.':payload.complete?'Показаны все записи из полученного списка. Выбор галочками не меняет подписки в GMGN.':'Показан неполный список. Кошельки без сделок могут отсутствовать; это не весь Wallet Tracker.';
const query=document.querySelector('#search'),only=document.querySelector('#selected-only'),list=document.querySelector('#list');
function visible(){const q=query.value.trim().toLowerCase();return wallets.filter(w=>(!q||(w.label+' '+w.address+' '+w.chain).toLowerCase().includes(q))&&(!only.checked||chosen.has(key(w))));}
function persist(){try{localStorage.setItem(storageKey,JSON.stringify([...chosen]));}catch{}
 for(const w of wallets)w.priority=chosen.has(key(w));
 document.querySelector('#wallet-data').textContent=JSON.stringify(payload).replace(/</g,'\\u003c');
}
function draw(){list.replaceChildren();const shown=visible();
 document.querySelector('#count').textContent=`Выбрано ${chosen.size} из ${wallets.length}`;
 document.querySelector('#export').disabled=chosen.size===0;
 document.querySelector('#select-visible').disabled=shown.length===0;
 document.querySelector('#clear').disabled=chosen.size===0;
 if(!shown.length){const e=document.createElement('div');e.className='empty';e.textContent=wallets.length?'По этому поиску кошельков нет.':'Ожидаем список из GMGN. Примерные или выдуманные адреса не подставляются.';list.append(e);}
 for(const w of shown){const row=document.createElement('label');row.className='wallet';const box=document.createElement('input');box.type='checkbox';box.checked=chosen.has(key(w));box.setAttribute('aria-label','Выбрать '+w.label+' '+w.address);box.onchange=()=>{box.checked?chosen.add(key(w)):chosen.delete(key(w));persist();draw();};
 const details=document.createElement('div'),name=document.createElement('div'),address=document.createElement('div'),chain=document.createElement('div');name.className='name';name.textContent=w.label;address.className='address';address.textContent=w.address;chain.className='chain';chain.textContent=w.chain==='evm'?'Сеть не указана в экспорте':w.chain;details.append(name,address,chain);row.append(box,details);list.append(row);}
}
function download(contents,type,name){const url=URL.createObjectURL(new Blob([contents],{type})),a=document.createElement('a');a.href=url;a.download=name;document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),30000);}
query.oninput=draw;only.onchange=draw;
document.querySelector('#select-visible').onclick=()=>{for(const w of visible())chosen.add(key(w));persist();draw();};
document.querySelector('#clear').onclick=()=>{chosen.clear();persist();draw();};
document.querySelector('#export').onclick=()=>{const selected=wallets.filter(w=>chosen.has(key(w))).map(w=>({...w,priority:true}));if(!selected.length)return;download(JSON.stringify(selected,null,2),'application/json;charset=utf-8','GMGN_PRIORITIES.json');document.querySelector('#status').textContent=`Сохранён выбор: ${selected.length} кошельков. Прикрепи JSON-файл к чату, чтобы применить его к боту.`;};
document.querySelector('#save-page').onclick=()=>{persist();download('<!doctype html>\n'+document.documentElement.outerHTML,'text/html;charset=utf-8','GMGN_Wallet_Selection.html');};
persist();draw();
})();
</script></html>'''


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('wallets',type=Path)
    parser.add_argument('--source',required=True)
    parser.add_argument('--complete',action='store_true')
    parser.add_argument('--note',default='')
    parser.add_argument('--output',type=Path,default=Path('data/gmgn/wallet_selector.html'))
    args=parser.parse_args()
    wallets=load_wallets(args.wallets)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(render(wallets,args.source,args.complete,args.note),encoding='utf-8')
    print(f'Created selector: {len(wallets)} wallets; complete inventory: {args.complete}; {args.output}')


if __name__=='__main__':main()
