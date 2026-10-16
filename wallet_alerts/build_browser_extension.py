"""Build a private Chrome diagnostic extension and in-page ZIP download."""
import base64
import json
from pathlib import Path
import shutil
import zipfile

from .core import load_priorities


def main():
    root=Path(__file__).resolve().parent.parent
    output=root/'data/gmgn'
    source=root/'browser_extension'
    wallets=load_priorities(output/'priorities.json')
    package=output/'browser_extension'
    package.mkdir(parents=True,exist_ok=True)
    names=['manifest.json','capture.js','popup.html','popup.css','popup.js','README.md']
    for name in names:
        shutil.copyfile(source/name,package/name)
    priorities=[dict(chain=w.chain,address=w.address,label=w.label,priority=w.priority)
                for w in wallets.values() if w.priority]
    (package/'priorities.json').write_text(json.dumps(priorities,ensure_ascii=False,indent=2),encoding='utf-8')
    archive=output/'GMGN_Tracker_Check.zip'
    with zipfile.ZipFile(archive,'w',compression=zipfile.ZIP_DEFLATED) as handle:
        for name in names+['priorities.json']:
            handle.write(package/name,arcname='GMGN_Tracker_Check/'+name)
    data=base64.b64encode(archive.read_bytes()).decode('ascii')
    page=PAGE.replace('__ZIP__',data).replace('__COUNT__',str(len(priorities)))
    (output/'install_browser_extension.html').write_text(page,encoding='utf-8')
    print(f'Built Chrome source checker with {len(priorities)} selected wallets; notifications are not enabled.')
    print(f'Install page: {output / "install_browser_extension.html"}')


PAGE=r'''<!doctype html><html lang="ru"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>GMGN — подключаем браузер</title>
<style>:root{color-scheme:dark;font:17px/1.65 system-ui;background:#0d1725;color:#eaf2fc}*{box-sizing:border-box}body{margin:0;padding:24px}main{max-width:850px;margin:auto}h1{line-height:1.2;font-size:32px}h2{font-size:21px}.tag{color:#4bdbb3;font-size:12px;letter-spacing:2px}.panel{padding:24px;background:#142339;border:1px solid #2d435f;border-radius:16px;margin:20px 0}p,li{color:#b8c9df}li{margin:10px 0}code{color:#eff7ff;background:#243851;padding:2px 5px;border-radius:4px;overflow-wrap:anywhere}button{font:inherit;font-weight:650;cursor:pointer;padding:12px 18px;margin:7px 8px 7px 0;border:1px solid #415975;border-radius:9px;background:#233953;color:#edf5ff}.primary{background:#4cdbb4;color:#08291f}.notice{padding:14px;border-left:3px solid #e3b565;background:#29261f;border-radius:7px;color:#edd2a3}.small{font-size:14px}#status{min-height:28px}@media(max-width:550px){body{padding:12px}.panel{padding:16px}h1{font-size:26px}ol{padding-left:22px}}</style>
<main><div class="tag">GMGN → ТВОЙ TELEGRAM</div><h1>Подключаем источник в Chrome</h1>
<p>Внутри расширения уже сохранён твой выбор: <b>__COUNT__ кошельков</b>.</p>
<div class="notice">Это первый шаг: проверка строк Wallet Tracker. Уведомления ещё не включены. Понадобится небольшой образец реальной страницы, чтобы правильно распознать сделки.</div>
<div class="panel"><h2>1. Скачай и распакуй расширение</h2>
<button class="primary" id="download">Скачать расширение ZIP</button>
<button id="save">Сохранить эту инструкцию HTML</button>
<p id="status" role="status"></p>
<ol><li>Нажми зелёную кнопку <b>«Скачать расширение ZIP»</b>.</li>
<li>Открой скачанный <code>GMGN_Tracker_Check.zip</code>. Нажми <b>«Извлечь всё»</b>.</li>
<li>Сохрани распакованную папку в постоянном месте, например в «Документах».</li></ol></div>
<div class="panel"><h2>2. Подключи папку в Chrome</h2><ol>
<li>Открой новую вкладку Chrome. В адресной строке напиши <code>chrome://extensions</code> и нажми Enter.</li>
<li>Включи <b>«Режим разработчика»</b> — переключатель справа сверху.</li>
<li>Нажми <b>«Загрузить распакованное расширение»</b>.</li>
<li>Выбери папку <code>GMGN_Tracker_Check</code>, внутри которой лежит файл <code>manifest.json</code>.</li>
</ol></div>
<div class="panel"><h2>3. Получи образец трекера</h2><ol>
<li>Вернись на вкладку GMGN. Покажи Wallet Tracker со сделками хотя бы одного выбранного кошелька — например «Рома 11», «Рома 12» или «Рома 13».</li>
<li>В Chrome справа сверху нажми значок <b>пазла 🧩</b>, затем <b>«GMGN Tracker — проверка источника»</b>.</li>
<li>Нажми <b>«Снять образец трекера»</b>, затем <b>«Скачать образец JSON»</b>.</li>
<li>Прикрепи файл <code>GMGN_TRACKER_SAMPLE.json</code> сюда в чат Codex. По нему настроим распознавание и следующий шаг — Telegram.</li>
</ol></div><p class="small">Расширение читает видимые строки по твоему нажатию. Ключи, cookies и пароль не нужны. Оно не меняет подписки GMGN, не совершает сделок и ничего не отправляет по сети. В образце могут быть имена, адреса и суммы отслеживаемых кошельков — передавай его в свой чат.</p>
<p class="small">Для будущих уведомлений потребуется работающий компьютер и открытый Wallet Tracker GMGN. Сон компьютера, скрытая/приостановленная вкладка и изменения страницы могут прерывать сбор. Постоянное подключение к интернету само по себе не гарантирует полноту событий.</p>
</main><script id="zip-data" type="application/octet-stream">__ZIP__</script><script>
function download(contents,type,name){const url=URL.createObjectURL(new Blob([contents],{type}));const a=document.createElement('a');a.href=url;a.download=name;document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),30000);}
document.querySelector('#download').onclick=()=>{const value=atob(document.querySelector('#zip-data').textContent.trim());const bytes=Uint8Array.from(value,c=>c.charCodeAt(0));download(bytes,'application/zip','GMGN_Tracker_Check.zip');document.querySelector('#status').textContent='Архив отправлен в загрузки Chrome. Затем открой его и нажми «Извлечь всё».';};
document.querySelector('#save').onclick=()=>download('<!doctype html>\n'+document.documentElement.outerHTML,'text/html;charset=utf-8','GMGN_Chrome_Инструкция.html');
</script></html>'''


if __name__=='__main__':main()
