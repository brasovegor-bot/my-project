import {extractTrackerSample} from './capture.js';
const capture=document.querySelector('#capture'),download=document.querySelector('#download'),status=document.querySelector('#status');
let priorities=[],sample=null;
try{
  priorities=await (await fetch(chrome.runtime.getURL('priorities.json'))).json();
  if(!Array.isArray(priorities)||!priorities.length||priorities.some(w=>!/^0x[a-fA-F0-9]{40}$/.test(w.address)||typeof w.label!=='string'||!w.priority))throw Error();
  document.querySelector('#wallets').textContent=`В пакете твой выбор: ${priorities.length} кошельков.`;
  capture.disabled=false;
}catch{status.textContent='Не удалось прочитать список кошельков из пакета расширения.';}
capture.onclick=async()=>{
  capture.disabled=true;download.disabled=true;sample=null;status.textContent='Читаю видимые строки…';
  try{
    const [tab]=await chrome.tabs.query({active:true,currentWindow:true});
    const url=new URL(tab.url);
    if(url.protocol!=='https:'||!['gmgn.ai','www.gmgn.ai'].includes(url.hostname)){
      status.textContent='Переключись на вкладку GMGN с Wallet Tracker, затем снова открой расширение.';return;
    }
    const results=await chrome.scripting.executeScript({target:{tabId:tab.id},func:extractTrackerSample,args:[priorities]});
    sample=results[0]?.result;
    if(sample?.format!=='gmgn-visible-tracker-sample-v1')throw Error();
    download.disabled=false;
    status.textContent=sample.visible_row_count
      ?`Найдено видимых строк: ${sample.visible_row_count}. Скачай JSON и прикрепи его в чат. Уведомления пока выключены.`
      :'Подходящие строки не найдены. Покажи трекер и сделку выбранного кошелька. Можно скачать диагностику — она поможет уточнить структуру страницы.';
  }catch{status.textContent='Не удалось прочитать страницу. Открой обычную вкладку GMGN, дождись загрузки трекера и повтори.';}
  finally{capture.disabled=false;}
};
download.onclick=()=>{
  if(!sample)return;
  const url=URL.createObjectURL(new Blob([JSON.stringify(sample,null,2)],{type:'application/json;charset=utf-8'}));
  const a=document.createElement('a');a.href=url;a.download='GMGN_TRACKER_SAMPLE.json';document.body.append(a);a.click();a.remove();
  setTimeout(()=>URL.revokeObjectURL(url),30000);
};
