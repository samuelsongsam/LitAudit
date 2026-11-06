"""Killable research tool process; credentials never travel in its output."""
import json
import sys
from pathlib import Path

if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def execute(options):
    import os
    os.environ['LITAUDIT_HOME'] = options['root']
    from src.config import load_settings
    from src.research_agent import Action
    from src.research_workspace import workspace_papers, search_fulltext
    settings = load_settings(runs_dir=options['runs_dir'])
    action = Action.model_validate(options['action'])
    run_id = options['run_id']
    papers = workspace_papers(settings.runs_dir, run_id)
    if not action.paper_ids or not set(action.paper_ids) <= set(papers):
        raise ValueError('invalid_scope')
    if action.tool == 'read_papers':
        return {'papers': [{'paper_id': pid, 'title': papers[pid].title,
                            'abstract': (papers[pid].abstract or '')[:8000]} for pid in action.paper_ids]}
    if action.tool == 'search_fulltext':
        result = search_fulltext(settings.runs_dir, run_id, action.query, paper_ids=action.paper_ids)
        return {'hits': result.get('hits', [])[:8], 'status': 'completed'}
    if action.tool == 'acquire_fulltext':
        from src.pipeline import upgrade_audit
        result = upgrade_audit(settings, run_id, acquire=True, paper_ids=action.paper_ids)
        return {'run_id': result['run_id'], 'acquisition': result['acquisition']}
    raise ValueError('invalid_tool')


if __name__ == '__main__':
    from contextlib import redirect_stdout
    try:
        options = json.load(sys.stdin)
        with redirect_stdout(sys.stderr):
            result = execute(options)
        sys.stdout.buffer.write(json.dumps(result, ensure_ascii=False).encode('utf-8'))
    except Exception:
        sys.exit(1)
