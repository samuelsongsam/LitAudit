import json

import pytest

from src.conversation import _write_conversation
from src.research_workspace import _atomic_json


@pytest.mark.parametrize('writer', [_write_conversation, _atomic_json])
def test_transient_file_sharing_conflict_keeps_atomic_user_record(tmp_path, monkeypatch, writer):
    import src.io_utils as io
    path = tmp_path/'record.json'
    path.write_text('{"note":"previous"}', encoding='utf-8')
    original = io.os.replace
    attempts = []
    def temporary_conflict(source, destination):
        attempts.append(1)
        assert json.loads(path.read_text()) == {'note': 'previous'}
        if len(attempts) < 3:
            raise PermissionError('simulated Windows file-sharing conflict')
        original(source, destination)
    monkeypatch.setattr(io.os, 'replace', temporary_conflict)
    monkeypatch.setattr(io.time, 'sleep', lambda value: None)
    writer(path, {'note': 'saved completely'})
    assert json.loads(path.read_text()) == {'note': 'saved completely'}
    assert not list(tmp_path.glob('*.tmp'))


@pytest.mark.parametrize('writer', [_write_conversation, _atomic_json])
def test_persistent_conflict_reports_failure_and_preserves_previous_record(tmp_path, monkeypatch, writer):
    import src.io_utils as io
    path = tmp_path/'record.json'
    path.write_text('{"note":"previous"}', encoding='utf-8')
    def conflict(*args):
        raise PermissionError('file remains locked')
    monkeypatch.setattr(io.os, 'replace', conflict)
    monkeypatch.setattr(io.time, 'sleep', lambda value: None)
    with pytest.raises(PermissionError):
        writer(path, {'note': 'must not be reported saved'})
    assert json.loads(path.read_text()) == {'note': 'previous'}
    assert not list(tmp_path.glob('*.tmp'))
