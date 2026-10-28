"""Isolated yt-dlp process. Input/output are private local JSON files."""
import json
import os
from pathlib import Path
import resource
import sys
from security import canonical_url, install_network_guard

MAX = 300 * 1024 * 1024

def emit(obj):
    print(json.dumps(obj, ensure_ascii=False), flush=True)

class Silent:
    def debug(self, *a): pass
    def warning(self, *a): pass
    def error(self, *a): pass

def choices(entry):
    formats = [f for f in entry.get('formats', []) if f.get('protocol') in ('http', 'https') and not f.get('has_drm')]
    audios = [f for f in formats if f.get('acodec') not in (None, 'none') and f.get('vcodec') == 'none']
    aac = [f for f in audios if f.get('ext') == 'm4a']
    audio = max(aac, key=lambda f:f.get('abr') or 0, default=None)
    results = {}
    for f in formats:
        height = f.get('height')
        if f.get('ext') != 'mp4' or not height or f.get('vcodec') in (None, 'none'): continue
        if f.get('filesize', 0) and f['filesize'] > MAX: continue
        fid = f['format_id']
        if not __import__('re').fullmatch(r'[A-Za-z0-9_-]+', fid): continue
        if f.get('acodec') == 'none':
            if audio is None: continue
            fid += '+' + audio['format_id']
        results[f'mp4-{height}'] = {'id':f'mp4-{height}', 'label':f'MP4 · {height}p', 'format':fid, 'ext':'mp4'}
    if audios or any(f.get('acodec') not in (None, 'none') for f in formats):
        a = max(audios or [f for f in formats if f.get('acodec') not in (None, 'none')], key=lambda f:f.get('abr') or 0)
        results['mp3'] = {'id':'mp3','label':'MP3 · 192 кбит/с','format':a['format_id'],'ext':'mp3'}
    return list(results.values())

def main():
    resource.setrlimit(resource.RLIMIT_FSIZE, (MAX * 2, MAX * 2))
    resource.setrlimit(resource.RLIMIT_CPU, (300, 300))
    resource.setrlimit(resource.RLIMIT_NOFILE, (128, 128))
    install_network_guard()
    from yt_dlp import YoutubeDL
    from yt_dlp.networking._urllib import UrllibRH
    request = json.loads(Path(sys.argv[1]).read_text())
    url = canonical_url(request['url'])
    opts = dict(quiet=True, no_warnings=True, logger=Silent(), proxy='', socket_timeout=15,
        retries=1, fragment_retries=1, noplaylist=True, playlistend=20, cachedir=False,
        max_filesize=MAX, allowed_extractors=['youtube', 'instagram'],
        allow_unplayable_formats=False, check_formats=False, js_runtimes={'node':{}},
        remote_components=[], extract_flat=False)
    with YoutubeDL(opts) as ydl:
        # Avoid native curl transports, which would bypass the socket guard.
        ydl._request_director.handlers.clear()
        ydl._request_director.add_handler(UrllibRH(logger=Silent(), proxies={'all':None}, timeout=15))
        data = ydl.extract_info(url, download=False)
        entries = list(data.get('entries') or [data])[:20]
        available = []
        for idx, e in enumerate(entries):
            if not e or e.get('is_live') or e.get('has_drm'): continue
            if e.get('availability') not in (None, 'public', 'unlisted'): continue
            if not e.get('duration') or e['duration'] > 1800: continue
            options = choices(e)
            if options:
                available.append((idx,e,options))
        if not available:
            raise ValueError('Видео недоступно без авторизации, защищено или не имеет поддерживаемых форматов. Лимит — 30 минут.')
        if request['mode'] == 'info':
            emit({'items':[{'index':idx,'title':e.get('title') or 'Видео Instagram',
                'thumbnail': e.get('thumbnail'), 'duration':e.get('duration'),
                'formats':[{k:v for k,v in o.items() if k != 'format'} for o in options]} for idx,e,options in available]})
            return
        _, entry, options = next(x for x in available if x[0] == request['index'])
        option = next(o for o in options if o['id'] == request['format'])
        def progress(d):
            total = d.get('total_bytes') or d.get('total_bytes_estimate')
            done = d.get('downloaded_bytes', 0)
            if done > MAX: raise ValueError('Файл превышает 300 МБ.')
            emit({'progress':min(95, int(done / total * 90)) if total else None})
        ydl.format_selector = ydl.build_format_selector(option['format'])
        ydl.params.update(format=option['format'], outtmpl={'default':str(Path.cwd()/'media.%(ext)s')},
            merge_output_format='mp4', noprogress=True,
            postprocessor_args={'ffmpeg_i':['-protocol_whitelist','file,pipe']})
        ydl.add_progress_hook(progress)
        if option['ext'] == 'mp3':
            from yt_dlp.postprocessor import FFmpegExtractAudioPP
            ydl.add_post_processor(FFmpegExtractAudioPP(ydl, preferredcodec='mp3', preferredquality='192'))
        # Reprocess already extracted metadata, with only direct HTTP(S) formats.
        entry['formats'] = [f for f in entry['formats'] if f.get('protocol') in ('http','https') and not f.get('has_drm')]
        ydl.process_ie_result(entry, download=True)
        output = Path('media.' + option['ext'])
        if not output.is_file() or output.stat().st_size > MAX: raise ValueError('Файл превышает лимит или не создан.')
        emit({'file':output.name})

if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        import re
        diagnostic = re.sub(r'https?://\S+', '[URL]', str(error))[:500]
        print(type(error).__name__ + ': ' + diagnostic, file=sys.stderr, flush=True)
        message = str(error).lower()
        if 'not a bot' in message or 'confirm you' in message:
            explanation = 'YouTube требует вход и проверку «Я не робот» для запросов с этого сервера. Скачивание сейчас недоступно. FrameSave не обходит эту защиту.'
        elif 'empty media response' in message:
            explanation = 'Instagram не предоставил медиа без авторизации. Публикация недоступна этому серверу; вход и cookies не используются.'
        elif 'private' in message or 'login' in message or 'sign in' in message:
            explanation = 'Платформа требует вход или ограничила доступ к публикации. FrameSave поддерживает только доступный без авторизации контент.'
        elif 'unavailable' in message or 'not available' in message:
            explanation = 'Видео недоступно: публикация удалена или платформа ограничила доступ.'
        else:
            explanation = 'Не удалось получить видео. Возможны сетевой сбой, ограничение платформы или превышение лимитов. Обход ограничений не выполняется.'
        emit({'error':explanation})
        sys.exit(1)
