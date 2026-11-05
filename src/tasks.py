"""Bounded local research tasks with persisted progress and cooperative cancel."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import threading
from uuid import uuid4

from src.conversation import _write_conversation

_context = threading.local()


class TaskCancelled(RuntimeError):
    pass


def check_cancelled() -> None:
    """Stop at a safe boundary; this does not forcibly interrupt blocked I/O."""
    event = getattr(_context, 'cancel_event', None)
    if event is not None and event.is_set():
        raise TaskCancelled('任务已停止；已保存的研究记录保持可用')


RETRYABLE_STATES = {'failed', 'cancelled', 'interrupted'}
_PRIVATE_JOB_FIELDS = {'retry_descriptor'}


def _retry_descriptor(value: object) -> dict | None:
    """Accept bounded, secret-free operation inputs, never service credentials.

    The HTTP layer owns the operation/body allowlist. This lower-level check is
    an additional guard against accidentally persisting headers, credentials,
    binary documents or arbitrarily large requests in a background-task record.
    """
    if value is None:
        return None
    if not isinstance(value, dict) or set(value) - {'path', 'body', 'method'}:
        raise ValueError('任务恢复描述只允许POST路径和请求参数')
    path, body = value.get('path'), value.get('body')
    if (not isinstance(path, str) or len(path) > 160 or not re.fullmatch(r'/api/[A-Za-z0-9_/-]+', path)
            or not isinstance(body, dict) or value.get('method', 'POST') != 'POST'):
        raise ValueError('任务恢复路径或参数格式无效')
    def inspect(item, depth=0):
        if depth > 12:
            raise ValueError('任务恢复参数嵌套过深')
        if isinstance(item, dict):
            if len(item) > 80:
                raise ValueError('任务恢复参数过多')
            for key, entry in item.items():
                if not isinstance(key, str) or re.search(r'key|token|password|secret|authorization|credential|headers?|content_base64', key, re.I):
                    raise ValueError('任务恢复参数不能包含密钥、认证头或文档内容')
                inspect(entry, depth+1)
        elif isinstance(item, list):
            if len(item) > 100:
                raise ValueError('任务恢复列表过长')
            for entry in item:
                inspect(entry, depth+1)
        elif item is not None and not isinstance(item, (str, bool, int, float)):
            raise ValueError('任务恢复参数必须为普通JSON数据')
    inspect(body)
    try:
        encoded = json.dumps(value, ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ValueError('任务恢复参数必须为有效JSON数据') from exc
    if len(encoded.encode('utf-8')) > 32 * 1024:
        raise ValueError('任务恢复参数不得超过32KB；文档应使用已保存的研究材料')
    for name in ['LITAUDIT_LLM_API_KEY', 'OPENAI_API_KEY', 'OPENALEX_API_KEY', 'SEMANTIC_SCHOLAR_API_KEY']:
        configured = os.getenv(name)
        if configured and len(configured) >= 8 and configured in encoded:
            raise ValueError('任务恢复参数中含有已配置密钥，不能保存')
    return json.loads(encoded)


def report_progress(stage: str, status: str = 'running', run_id: str | None = None) -> None:
    callback = getattr(_context, 'progress', None)
    if callback:
        callback(stage, status, run_id)


class TaskManager:
    def __init__(self, runs_dir: Path, workers: int = 2):
        self.root = Path(runs_dir) / '.tasks'
        self.root.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix='litaudit-task')
        self.jobs: dict[str, dict] = {}
        self.events: dict[str, threading.Event] = {}
        for path in self.root.glob('*.json'):
            try:
                if path.is_symlink():
                    continue
                data = json.loads(path.read_text(encoding='utf-8'))
                if (not isinstance(data, dict) or not isinstance(data.get('task_id'), str)
                        or not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', data['task_id'])
                        or data['task_id'] != path.stem or not isinstance(data.get('operation'), str)
                        or not isinstance(data.get('created_at'), str)
                        or not isinstance(data.get('status'), str)
                        or data['status'] not in {'queued', 'running', 'cancel_requested', 'completed', 'failed', 'cancelled', 'interrupted'}):
                    raise ValueError('invalid_task_record')
                if data.get('retry_descriptor') is not None:
                    try:
                        data['retry_descriptor'] = _retry_descriptor(data['retry_descriptor'])
                    except ValueError:
                        data.pop('retry_descriptor', None)
                        data['retry_unavailable_reason'] = '保存的恢复参数不符合安全范围，请重新提交'
                        _write_conversation(path, data)
                if data.get('status') in {'running', 'queued', 'cancel_requested'}:
                    data.update(status='interrupted', error='服务已重启，已有研究记录保留，可重新提交或回放。')
                    _write_conversation(path, data)
                self.jobs[data['task_id']] = data
            except (ValueError, KeyError, OSError):
                continue

    def _save(self, job):
        job['updated_at'] = datetime.now(timezone.utc).isoformat()
        _write_conversation(self.root / (job['task_id'] + '.json'), job)

    def submit(self, operation: str, work, request_id: str | None = None, input_digest: str | None = None,
               retry_descriptor: dict | None = None, retry_of: str | None = None) -> dict:
        descriptor = _retry_descriptor(retry_descriptor)
        with self.lock:
            if retry_of is not None:
                if not isinstance(retry_of, str) or retry_of not in self.jobs:
                    raise ValueError('找不到要重试的原任务')
                if self.jobs[retry_of]['status'] not in RETRYABLE_STATES:
                    raise ValueError('只能重新提交失败、已停止或服务中断的任务')
                if self.jobs[retry_of]['operation'] != operation:
                    raise ValueError('重试任务必须与原任务操作一致')
                children = [row for row in self.jobs.values() if row.get('retry_of') == retry_of]
                if children:
                    child = max(children, key=lambda row: row['created_at'])
                    if child.get('retry_descriptor') != descriptor:
                        raise ValueError('同一任务的重试输入不能改写；请提交新的研究请求')
                    return self.get(child['task_id'])
            if request_id:
                previous = next((x for x in self.jobs.values() if x.get('request_id') == request_id), None)
                if previous:
                    if (previous['operation'] != operation or previous.get('input_digest') != input_digest
                            or previous.get('retry_descriptor') != descriptor or previous.get('retry_of') != retry_of):
                        raise ValueError('该请求编号已用于不同任务，请使用新的请求编号')
                    return self.get(previous['task_id'])
            active = sum(j['status'] in {'running', 'queued', 'cancel_requested'} for j in self.jobs.values())
            if active >= 8:
                raise ValueError('当前任务较多，请等待已有任务完成后重试')
            task_id = uuid4().hex
            job = {'task_id': task_id, 'operation': operation, 'status': 'queued', 'stage': 'queued',
                   'request_id': request_id, 'input_digest': input_digest, 'events': [], 'created_at': datetime.now(timezone.utc).isoformat()}
            if descriptor is not None:
                job['retry_descriptor'] = descriptor
            if retry_of is not None:
                job['retry_of'] = retry_of
            self.jobs[task_id] = job
            event = self.events[task_id] = threading.Event()
            self._save(job)

        def progress(stage, status='running', run_id=None):
            with self.lock:
                if event.is_set() and status == 'running':
                    raise TaskCancelled('任务已停止；已保存的研究结果可在历史记录中继续查看')
                job['stage'] = stage
                if run_id:
                    job['run_id'] = run_id
                job['events'] = (job['events'] + [{'stage': stage, 'status': status,
                    'at': datetime.now(timezone.utc).isoformat()}])[-40:]
                self._save(job)

        def execute():
            _context.progress = progress
            _context.cancel_event = event
            try:
                progress('starting')
                with self.lock:
                    job['status'] = 'running'
                    self._save(job)
                result = work()
                with self.lock:
                    if event.is_set():
                        raise TaskCancelled('任务已停止，已完成的研究数据保持保存')
                    job.update(status='completed', result=result)
                    if isinstance(result, dict) and result.get('run_id'):
                        job['run_id'] = result['run_id']
                    self._save(job)
            except Exception as exc:
                with self.lock:
                    job.update(status='cancelled' if isinstance(exc, TaskCancelled) or event.is_set() else 'failed', error=str(exc)[:600])
                    self._save(job)
            finally:
                _context.progress = None
                _context.cancel_event = None

        self.pool.submit(execute)
        return self.get(task_id)

    def get(self, task_id: str) -> dict:
        with self.lock:
            if task_id not in self.jobs:
                raise FileNotFoundError('找不到该研究任务')
            job = self.jobs[task_id]
            public = {k: v for k, v in job.items() if k not in _PRIVATE_JOB_FIELDS}
            children = [row for row in self.jobs.values() if row.get('retry_of') == task_id]
            public['can_retry'] = (job['status'] in RETRYABLE_STATES and isinstance(job.get('retry_descriptor'), dict)
                                   and not children)
            if children:
                public['retry_task_id'] = max(children, key=lambda row: row['created_at'])['task_id']
            return json.loads(json.dumps(public, ensure_ascii=False))

    def get_retry_descriptor(self, task_id: str) -> dict:
        with self.lock:
            if task_id not in self.jobs:
                raise FileNotFoundError('找不到该研究任务')
            job = self.jobs[task_id]
            if job['status'] not in RETRYABLE_STATES:
                raise ValueError('只有失败、已停止或服务中断的任务可以重新提交')
            descriptor = _retry_descriptor(job.get('retry_descriptor'))
            if descriptor is None:
                raise ValueError('该任务没有可恢复的输入，请重新提交研究问题')
            return descriptor

    def cancel(self, task_id: str) -> dict:
        with self.lock:
            job = self.jobs.get(task_id)
            if job is None:
                raise FileNotFoundError('找不到该研究任务')
            if job['status'] in {'running', 'queued'}:
                self.events[task_id].set()
                job['status'] = 'cancel_requested'
                self._save(job)
            return self.get(task_id)

    def list(self) -> list[dict]:
        with self.lock:
            return [{k: v for k, v in self.get(row['task_id']).items() if k != 'result'} for row in
                    sorted(self.jobs.values(), key=lambda j: j['created_at'], reverse=True)[:30]]

    def close(self):
        self.pool.shutdown(wait=False, cancel_futures=True)
