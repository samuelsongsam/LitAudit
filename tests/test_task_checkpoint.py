"""Persist recoverable operation inputs without exposing request bodies or keys."""
import io
import json
import ssl
import threading
import time
from urllib.error import HTTPError, URLError

import pytest

from src.http_fetch import http_get
from src.tasks import TaskCancelled, TaskManager, check_cancelled


def terminal(manager, task_id):
    deadline = time.monotonic()+5
    while time.monotonic()<deadline:
        job=manager.get(task_id)
        if job['status'] not in {'queued','running','cancel_requested'}:
            return job
        time.sleep(.005)
    raise AssertionError('Task did not finish')


def fail():
    raise RuntimeError('controlled provider failure')


def descriptor():
    return {'path':'/api/fulltext/search', 'body':{'run_id':'my-study','query':'private research question'}}


def test_recovery_input_is_persisted_but_never_in_public_task_payloads(tmp_path):
    manager=TaskManager(tmp_path)
    try:
        request=descriptor()
        job=manager.submit('/api/fulltext/search',fail,retry_descriptor=request)
        request['body']['query']='changed by caller'
        done=terminal(manager,job['task_id'])
        assert done['status']=='failed' and done['can_retry']
        public=json.dumps([done,manager.get(job['task_id']),manager.list()])
        assert 'retry_descriptor' not in public and 'private research question' not in public
        saved=json.loads((tmp_path/'.tasks'/f'{job["task_id"]}.json').read_text(encoding='utf-8'))
        assert saved['retry_descriptor']==descriptor()
        recovered=manager.get_retry_descriptor(job['task_id'])
        recovered['body']['query']='mutated retry copy'
        assert manager.get_retry_descriptor(job['task_id'])==descriptor()
    finally:
        manager.close()


def test_retry_creates_child_without_rewriting_failure_or_reusing_idempotency_key(tmp_path):
    manager=TaskManager(tmp_path)
    try:
        original=manager.submit('/api/fulltext/search',fail,request_id='original',input_digest='a',retry_descriptor=descriptor())
        terminal(manager,original['task_id'])
        child=manager.submit('/api/fulltext/search',lambda:{'run_id':'my-study'},request_id='retry-one',
                             input_digest='a',retry_descriptor=manager.get_retry_descriptor(original['task_id']),retry_of=original['task_id'])
        done=terminal(manager,child['task_id'])
        assert done['status']=='completed' and not done['can_retry']
        assert done['retry_of']==original['task_id'] and child['task_id']!=original['task_id']
        assert manager.get(original['task_id'])['status']=='failed'
        with pytest.raises(ValueError):
            manager.get_retry_descriptor(child['task_id'])
        with pytest.raises(ValueError):
            manager.submit('/api/chat',lambda:{},retry_descriptor={'path':'/api/chat','body':{}},retry_of=original['task_id'])
    finally:
        manager.close()


def test_restart_reconstructs_private_retry_input_and_preserves_checkpoint_reference(tmp_path):
    root=tmp_path/'.tasks';root.mkdir()
    value={'task_id':'saved-task','operation':'/api/fulltext/search','status':'running',
           'run_id':'stage-saved-run','stage':'fulltext','created_at':'2026-11-04T00:00:00Z',
           'retry_descriptor':descriptor()}
    (root/'saved-task.json').write_text(json.dumps(value),encoding='utf-8')
    manager=TaskManager(tmp_path)
    try:
        job=manager.get('saved-task')
        assert job['status']=='interrupted' and job['run_id']=='stage-saved-run' and job['can_retry']
        assert manager.get_retry_descriptor('saved-task')==descriptor()
        assert 'private research question' not in json.dumps(manager.list())
    finally:
        manager.close()


@pytest.mark.parametrize('value',[
    {'path':'https://example.org/api/chat','body':{}},
    {'path':'/api/chat?api_key=sensitive','body':{}},
    {'path':'/api/chat','body':[]},
    {'path':'/api/chat','body':{},'method':'GET'},
    {'path':'/api/chat','body':{'api_key':'never persist'}},
    {'path':'/api/chat','body':{'constraints':{'PASSWORD':'never persist'}}},
    {'path':'/api/chat','body':{'user_resources':{'accessToken':'never persist'}}},
    {'path':'/api/chat','body':{},'headers':{'Authorization':'never persist'}},
    {'path':'/api/import/pdf','body':{'content_base64':'cGRm'}},
    {'path':'/api/chat','body':{'message':'中'*12000}},
    {'path':'/api/chat','body':{'message':b'binary request'}},
])
def test_unsafe_or_large_descriptors_fail_before_task_is_allocated(tmp_path,value):
    manager=TaskManager(tmp_path)
    try:
        with pytest.raises(ValueError):
            manager.submit('operation',lambda:{},retry_descriptor=value)
        assert manager.list()==[] and list((tmp_path/'.tasks').glob('*.json'))==[]
    finally:
        manager.close()


def test_known_configured_secret_in_free_text_is_not_persisted(tmp_path,monkeypatch):
    secret='test-only-configured-provider-secret'
    monkeypatch.setenv('LITAUDIT_LLM_API_KEY',secret)
    manager=TaskManager(tmp_path)
    try:
        with pytest.raises(ValueError) as caught:
            manager.submit('operation',lambda:{},retry_descriptor={'path':'/api/chat','body':{'message':secret}})
        assert secret not in str(caught.value)
        assert list((tmp_path/'.tasks').glob('*.json'))==[]
    finally:
        manager.close()


def test_legacy_bad_descriptor_is_removed_instead_of_exposed_or_used(tmp_path):
    root=tmp_path/'.tasks';root.mkdir()
    value={'task_id':'legacy','operation':'/api/chat','status':'failed','created_at':'2026-11-04T00:00:00Z',
           'retry_descriptor':{'path':'/api/chat','body':{'token':'private legacy key'}}}
    path=root/'legacy.json';path.write_text(json.dumps(value),encoding='utf-8')
    manager=TaskManager(tmp_path)
    try:
        assert not manager.get('legacy')['can_retry']
        assert 'private legacy key' not in path.read_text(encoding='utf-8')
        with pytest.raises(ValueError):
            manager.get_retry_descriptor('legacy')
    finally:
        manager.close()


def test_running_task_cannot_be_retried(tmp_path):
    ready,release=threading.Event(),threading.Event()
    manager=TaskManager(tmp_path,workers=1)
    def work():
        ready.set();assert release.wait(5)
        return {}
    try:
        job=manager.submit('reading',work,retry_descriptor={'path':'/api/chat','body':{}})
        assert ready.wait(5)
        with pytest.raises(ValueError):
            manager.get_retry_descriptor(job['task_id'])
        with pytest.raises(ValueError):
            manager.submit('reading',lambda:{},retry_of=job['task_id'])
    finally:
        release.set();terminal(manager,job['task_id']);manager.close()


@pytest.mark.parametrize('boundary',['before_request','after_connect','after_read','http_error','network_error','ssl_retry'])
def test_network_cancellation_is_observed_without_swallowing_it(tmp_path,monkeypatch,boundary):
    ready,release=threading.Event(),threading.Event()
    manager=TaskManager(tmp_path,workers=1)
    calls=[]
    class Response:
        status=200
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def read(self,*args):
            calls.append('read')
            if boundary=='after_read':
                ready.set();assert release.wait(5)
            return b'provider response'
    def open_url(*args,**kwargs):
        calls.append('open')
        if boundary=='ssl_retry' and calls.count('open')==1:
            raise ssl.SSLError('controlled certificate failure')
        if boundary in {'after_connect','http_error','network_error','ssl_retry'}:
            ready.set();assert release.wait(5)
        if boundary=='http_error':
            raise HTTPError('https://example.org',503,'controlled failure',{},io.BytesIO(b'error body'))
        if boundary=='network_error':
            raise URLError('controlled network failure')
        return Response()
    monkeypatch.setattr('src.http_fetch.urlopen',open_url)
    monkeypatch.setenv('LITAUDIT_ALLOW_INSECURE_TLS','1')
    def work():
        if boundary=='before_request':
            ready.set();assert release.wait(5)
        return {'result':http_get('https://example.org').text}
    try:
        job=manager.submit('fetch',work)
        assert ready.wait(5)
        manager.cancel(job['task_id']);release.set()
        result=terminal(manager,job['task_id'])
        assert result['status']=='cancelled' and 'result' not in result
        if boundary=='before_request':assert calls==[]
        if boundary=='after_connect':assert calls==['open']
        # A pooled worker must not inherit the cancelled event on its next job.
        following=manager.submit('next',lambda:check_cancelled() or {'ok':True})
        assert terminal(manager,following['task_id'])['status']=='completed'
    finally:
        release.set();manager.close()


def test_check_cancelled_is_a_noop_outside_background_work():
    check_cancelled()


def test_malformed_task_cache_does_not_block_startup_or_escape_its_directory(tmp_path):
    root=tmp_path/'.tasks';root.mkdir()
    (root/'invalid-array.json').write_text('[]',encoding='utf-8')
    (root/'escape.json').write_text(json.dumps({'task_id':'../elsewhere','operation':'read','created_at':'now','status':'running'}),encoding='utf-8')
    (root/'invalid-status.json').write_text(json.dumps({'task_id':'invalid-status','operation':'read','created_at':'now','status':{}}),encoding='utf-8')
    manager=TaskManager(tmp_path)
    try:
        assert manager.list()==[]
        assert not (tmp_path/'elsewhere.json').exists()
    finally:
        manager.close()
