"""Live configured-model follow-up acceptance; never stores credentials."""
from pathlib import Path
import json
import os
import shutil
import subprocess
import sys
import time
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT/'output/validation/v2/reading'
RUNS = ROOT/'tmp/research-v2/reading-runs'


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    RUNS.mkdir(parents=True, exist_ok=True)
    run = 'validation-v2-lora'
    run_copy = RUNS/run
    if run_copy.exists():
        run = run + '-' + str(int(time.time()))
    shutil.copytree(ROOT/'runs'/'validation-v2-lora', RUNS/run)
    env = {**os.environ, 'LITAUDIT_RUNS_DIR': str(RUNS), 'LITAUDIT_RERANK_EMBEDDER': 'hash'}
    server = subprocess.Popen([sys.executable, '-m', 'src.cli', 'ui', '--run-id', run,
                               '--port', '8795', '--no-browser'], cwd=ROOT, env=env,
                              stdout=(OUT/'server.log').open('w'), stderr=subprocess.STDOUT)
    base = 'http://127.0.0.1:8795'
    rows = []
    try:
        for _ in range(50):
            try:
                urlopen(base+'/api/health', timeout=1).close()
                break
            except Exception:
                time.sleep(.3)
        for question in ['请只基于当前 paper-008 的正文，用中文解释QLoRA的4-bit quantization和内存节省方法，给出原文依据，不需要检索新论文。',
                         '刚才这个方法的实验比较基线是什么？请继续使用这篇论文的正文，区分论文报告和你的解释。']:
            started = time.monotonic()
            req = Request(base+'/api/chat', json.dumps({'run_id': run, 'message': question, 'reading_mode': True,
                           'user_resources': {'compute': '单张8GB显存GPU', 'time': '两周'}}).encode(),
                          {'Content-Type': 'application/json', 'Prefer': 'respond-async'})
            job = json.load(urlopen(req, timeout=10))
            while job['status'] in {'queued', 'running', 'cancel_requested'}:
                time.sleep(.75)
                job = json.load(urlopen(base+'/api/tasks/'+job['task_id'], timeout=10))
            result = job.get('result') or {}
            response = result.get('response') or {}
            audit = response.get('answer_audit') or {}
            rows.append({'question': question, 'elapsed_seconds': round(time.monotonic()-started, 2),
                         'task_status': job['status'], 'run_id': result.get('run_id'),
                         'status': result.get('status'), 'response': response,
                         'error': job.get('error')})
            print(json.dumps({'question': question, 'task_status': job['status'], 'status': result.get('status'),
                              'audit_kind': audit.get('kind'), 'citations': len(audit.get('citations', []))}, ensure_ascii=False), flush=True)
            if result.get('run_id'):
                run = result['run_id']
        conversation = json.load(urlopen(base+'/api/chat/'+run, timeout=10))
        result = {'run_id': run, 'representation': 'explicit_hash_for_bounded_live_model_check',
                  'model_service': 'actual_configured_endpoint', 'turns': rows,
                  'replayed_message_count': len(conversation.get('messages', [])),
                  'ok': all(r['status']=='completed' and r['response'].get('answer_audit', {}).get('kind')=='grounded_reading'
                            for r in rows) and len(conversation.get('messages', [])) >= 4}
        (OUT/'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
        assert result['ok'], 'See reading/result.json; a fallback is not counted as a completed Chinese explanation.'
    finally:
        server.terminate()
        server.wait(timeout=10)


if __name__ == '__main__':
    main()
