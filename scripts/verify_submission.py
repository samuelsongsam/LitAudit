"""Extract the exact release ZIP and verify it with an independent interpreter."""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess
import time
from urllib.request import Request, urlopen
from uuid import uuid4
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--python', required=True, type=Path)
    args = parser.parse_args()
    archive = ROOT/'output/submission/01-牛来和豹拉-代码.zip'
    target = ROOT/'tmp'/('独立解压验收-'+uuid4().hex[:8])
    target.mkdir(parents=True)
    with zipfile.ZipFile(archive) as z:
        assert z.testzip() is None
        for name in z.namelist():
            assert (target/name).resolve().is_relative_to(target.resolve())
        z.extractall(target)
    app = target/'LitAudit'
    entries = json.loads((app/'submission-manifest.json').read_text(encoding='utf-8'))['files']
    for entry in entries:
        content = (app/entry['path']).read_bytes()
        assert len(content)==entry['bytes'] and sha256(content).hexdigest()==entry['sha256'], entry['path']
    assert not (app/'.env').exists()
    env = {**os.environ, 'LITAUDIT_HOME': str(app), 'LITAUDIT_MAP_EMBEDDER':'hash', 'LITAUDIT_RERANK_EMBEDDER':'hash'}
    for key in ['LITAUDIT_DATA_DIR', 'LITAUDIT_RUNS_DIR', 'LITAUDIT_LLM_API_KEY', 'OPENAI_API_KEY',
                'OPENALEX_API_KEY', 'SEMANTIC_SCHOLAR_API_KEY']:
        env.pop(key, None)
    base='http://127.0.0.1:8793'
    result={'archive_sha256':sha256(archive.read_bytes()).hexdigest(), 'interpreter':str(args.python),
            'extracted_workspace':str(app), 'manifest_files_verified':len(entries), 'credentials_loaded':False,
            'llm_calls':0, 'online_search_calls':0, 'checks':[]}
    def api(path, body=None):
        req=Request(base+path, data=json.dumps(body,ensure_ascii=False).encode() if body is not None else None,
                    headers={'Content-Type':'application/json'} if body is not None else {})
        with urlopen(req, timeout=90) as r:
            return json.load(r)
    def start():
        p=subprocess.Popen([str(args.python.resolve()),'-m','src.cli','ui','--run-id','acceptance_20261104_lora',
                            '--port','8793','--no-browser'],cwd=app,env=env,
                           stdout=(target/'server.log').open('a'),stderr=subprocess.STDOUT)
        for _ in range(60):
            try:
                health=api('/api/health')
                assert not health['capabilities']['llm_configured']
                return p
            except Exception:
                if p.poll() is not None:
                    raise RuntimeError('Extracted server exited; see '+str(target/'server.log'))
                time.sleep(.25)
        p.terminate()
        raise RuntimeError('Extracted server did not start')
    server=start()
    try:
        with urlopen(base,timeout=10) as r:
            assert r.status==200 and b'app.js' in r.read()
        result['checks'].append('standalone_source_and_static_ui_started')
        for run in ['validation-v2-lora','validation-v2-segmentation','import_20261104T121122Z_479655']:
            payload=api('/api/run/'+run)
            assert payload['stats']['error_count']==0
            docs=[d for d in payload['fulltext_audit']['documents'] if d['status']=='parsed']
            assert docs
            doc=docs[0]
            with urlopen(base+f'/api/fulltext/{run}/{doc["paper_id"]}',timeout=10) as r:
                assert r.read().startswith(b'%PDF')
            with urlopen(base+f'/api/pdf-page/{run}/{doc["paper_id"]}/1',timeout=10) as r:
                content=r.read()
                assert r.headers['Content-Type']=='image/png' and content.startswith(b'\x89PNG') and len(content)>2000
            result['checks'].append(run+'_local_pdf_and_real_page_render')
        run='acceptance_20261104_lora'
        conversation=api('/api/chat/'+run)
        assert len(conversation['messages'])>=4
        matrix=api('/api/methods/'+run)
        assert len(matrix['fields'])==10
        api('/api/library/save',{'run_id':run,'paper_id':'paper-008','reading_status':'done','favorite':True,
                                 'notes':'独立解压后的笔记，重启后仍保留。','tags':['搬迁验收']})
        for fmt in ['csv','markdown','bibtex','ris']:
            exported=api(f'/api/library/{run}/export?format={fmt}&paper_id=paper-008')
            assert exported['paper_count']==1 and exported['content'].strip()
        report=api('/api/run/'+run+'/report')
        assert '独立解压后的笔记' in report['content']
        result['checks'].append('conversation_methods_notes_and_four_exports')
        server.terminate();server.wait(timeout=10)
        server=start()
        item=next(p for p in api('/api/library/'+run)['items'] if p['paper_id']=='paper-008')
        assert item['favorite'] and item['reading_status']=='done' and '重启后仍保留' in item['notes']
        result['checks'].append('saved_material_survives_actual_server_restart')
        result['status']='passed'
    finally:
        server.terminate();server.wait(timeout=10)
        out=ROOT/'output/submission/relocation-check.json'
        out.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=='__main__':
    main()
