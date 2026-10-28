const $ = id => document.getElementById(id);
let generation = 0;
function message(text, error=false) { $('message').textContent=text; $('message').className=error?'error':''; }
async function api(path, body) {
  const controller = new AbortController();
  const timeout = setTimeout(()=>controller.abort(), 55000);
  try {
    const response = await fetch(path, {method:body?'POST':'GET',headers:body?{'Content-Type':'application/json'}:{},body:body?JSON.stringify(body):undefined,signal:controller.signal});
    const data = await response.json();
    if (!response.ok) throw new Error(typeof data.detail==='string'?data.detail:'Не удалось выполнить запрос. Проверьте данные и попробуйте ещё раз.');
    return data;
  } catch(e) { if(e.name==='AbortError') throw new Error('Сервер не ответил вовремя. Попробуйте снова.'); throw e; }
  finally { clearTimeout(timeout); }
}
$('paste').onclick = async()=> {
  try { $('url').value=await navigator.clipboard.readText(); $('url').focus(); }
  catch { message('Буфер обмена недоступен. Вставьте ссылку вручную в поле.'); $('url').focus(); }
};
function element(tag,text,className) {const e=document.createElement(tag);if(text)e.textContent=text;if(className)e.className=className;return e;}
function render(data, revision) {
  $('results').replaceChildren(); $('results').hidden=false;
  data.items.forEach(item=>{
    const card=element('article',null,'result'), media=element('div',null,'media'), meta=element('div');
    if(item.thumbnail && /^https:\/\//.test(item.thumbnail)) {const img=element('img');img.src=item.thumbnail;img.alt='Превью видео';img.referrerPolicy='no-referrer';img.onerror=()=>img.remove();media.append(img);}
    meta.append(element('span',data.platform+' · '+Math.floor(item.duration/60)+':'+String(Math.floor(item.duration%60)).padStart(2,'0'),'badge'),element('h3',item.title));media.append(meta);
    const label=element('label','Формат и качество'), select=element('select');
    item.formats.forEach(f=>{const o=element('option',f.label);o.value=f.id;select.append(o);});label.append(select);
    const button=element('button','Скачать','primary');button.type='button';
    const state=element('div',null,'progress');state.setAttribute('role','status');
    const bar=element('progress');bar.max=100;bar.value=0;bar.hidden=true;
    const link=element('a','Сохранить файл на устройство ↓','primary save-link');link.hidden=true;link.setAttribute('download','');
    card.append(media,label,button,state,bar,link);$('results').append(card);
    button.onclick=async()=>{
      button.disabled=true;select.disabled=true;link.hidden=true;bar.hidden=false;bar.value=0;
      try {
        const {id}=await api('/api/download',{ticket:data.ticket,index:item.index,format:select.value});
        state.textContent='Задача в очереди…';
        const deadline=Date.now()+1600000;
        while(revision===generation && Date.now()<deadline) {
          await new Promise(r=>setTimeout(r,2000));
          const s=await api('/api/status/'+encodeURIComponent(id));
          if(s.status==='error')throw new Error(s.error);
          if(s.status==='ready') {state.textContent='Файл готов. Сохраните его в течение 15 минут.';bar.value=100;link.href='/api/file/'+encodeURIComponent(id);link.hidden=false;break;}
          state.textContent=s.status==='queued'?'Задача в очереди…':'Скачиваем и обрабатываем видео…';
          if(s.progress==null)bar.removeAttribute('value');else bar.value=s.progress;
        }
        if(Date.now()>=deadline)throw new Error('Время ожидания истекло. Повторите поиск.');
      } catch(e) {state.textContent=e.message;button.textContent='Попробовать снова';bar.hidden=true;}
      finally {button.disabled=false;select.disabled=false;}
    };
  });
}
$('form').onsubmit=async e=>{
  e.preventDefault();const revision=++generation;
  $('find').disabled=true;$('find').classList.add('busy');$('find').textContent='Ищем доступные форматы…';$('results').hidden=true;
  message('Проверяем ссылку. Это может занять до 45 секунд.');
  try {const data=await api('/api/info',{url:$('url').value.trim(),rights:$('rights').checked});render(data,revision);message('Видео найдено. Выберите формат для скачивания.');}
  catch(e){message(e.message,true);}
  finally{$('find').disabled=false;$('find').classList.remove('busy');$('find').textContent='Найти видео →';}
};
