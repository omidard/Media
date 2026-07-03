import json, os, urllib.request, concurrent.futures as cf
media=json.load(open('mdive.json')); media=media.get('data',media) if isinstance(media,dict) else media
ids=[str(x['id']) for x in media]
UA={'User-Agent':'Mozilla/5.0 (research; media-repo)'}
def fetch(mid):
    p=f'details/{mid}.json'
    if os.path.exists(p) and os.path.getsize(p)>50: return 'skip'
    try:
        req=urllib.request.Request(f'https://mediadive.dsmz.de/rest/medium/{mid}', headers=UA)
        d=urllib.request.urlopen(req, timeout=30).read()
        open(p,'wb').write(d); return 'ok'
    except Exception as e:
        return 'err:'+str(e)[:40]
done=0; err=0
with cf.ThreadPoolExecutor(max_workers=12) as ex:
    for i,r in enumerate(ex.map(fetch, ids)):
        if r=='ok': done+=1
        elif r.startswith('err'): err+=1
        if (i+1)%400==0: print(f'{i+1}/{len(ids)} fetched(new)={done} err={err}', flush=True)
print(f'DONE fetched(new)={done} err={err} total_files={len([f for f in os.listdir("details") if f.endswith(".json")])}')
