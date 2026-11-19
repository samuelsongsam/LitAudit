"""Build the competition source ZIP from an explicit, secret-free file set."""
from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
from importlib.metadata import PackageNotFoundError, version
import json
import os
from pathlib import Path
import shutil
import sys
from uuid import uuid4
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.run_paths import resolve_run_file


def main() -> None:
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    stage = ROOT / 'tmp' / ('submission-' + stamp + '-' + uuid4().hex[:6]) / 'LitAudit'
    stage.mkdir(parents=True)
    excluded = {'__pycache__', '.pytest_cache', '.git', '.venv', 'node_modules'}
    roots = ['src', 'tests', 'data', 'scripts', 'skills/conversational-research-routing']
    files = []
    for folder in roots:
        for path in (ROOT / folder).rglob('*'):
            rel = path.relative_to(ROOT)
            if (path.is_file() and not path.is_symlink() and not excluded.intersection(rel.parts)
                    and path.suffix not in {'.pyc', '.pyo'} and not path.name.startswith('.env')
                    and not path.name.endswith('-pages.txt')):
                files.append(path)
    for name in ['README.md', '.env.example', '.gitignore', 'pyproject.toml', 'requirements.txt',
                 'docs/workspace_guide.md', 'docs/data_contract.md', 'docs/research_scope.md',
                 'docs/evaluation.md', 'docs/falsification_rules.md',
                 'docs/system_improvement_plan.md', 'docs/research_delivery.md']:
        path = ROOT / name
        if path.is_file():
            files.append(path)
    for path in files:
        target = stage / path.relative_to(ROOT)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
    # Keep a small baseline and one complete, real PDF reading case.
    for run_id in ['demo', 'phase2-real', 'audit_20260915T131753Z_a42e86',
                   'validation-v2-lora', 'validation-v2-segmentation', 'import_20261104T121122Z_479655',
                   'acceptance_20261104_lora']:
        source = ROOT / 'runs' / run_id
        if not source.is_dir():
            continue
        target = stage / 'runs' / run_id
        ignored = ('*.log', '__pycache__') if run_id == 'acceptance_20261104_lora' else ('conversation.json', '*.log', '__pycache__')
        shutil.copytree(source, target, ignore=shutil.ignore_patterns(*ignored))

        def portable(value):
            if isinstance(value, list):
                return [portable(x) for x in value]
            if not isinstance(value, dict):
                return value
            result = {}
            for key, item in value.items():
                if key in {'response_path', 'text_path', 'source_pdf_path'} and isinstance(item, str):
                    try:
                        item = resolve_run_file(source, item).relative_to(source.resolve()).as_posix()
                    except (ValueError, OSError):
                        pass
                elif key in {'root', 'data_dir', 'cache_dir', 'run_dir'} and isinstance(item, str):
                    item = {'root': '.', 'data_dir': 'data', 'cache_dir': 'cache', 'run_dir': '.'}[key]
                result[key] = portable(item)
            return result

        for path in target.rglob('*'):
            if path.suffix == '.json':
                data = portable(json.loads(path.read_text(encoding='utf-8')))
                path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
            elif path.suffix == '.jsonl':
                data = [portable(json.loads(line)) for line in path.read_text(encoding='utf-8').splitlines() if line.strip()]
                path.write_text(''.join(json.dumps(row, ensure_ascii=False) + '\n' for row in data), encoding='utf-8')

    # Reproducible new-topic measurements; original PDFs are already in each
    # run's portable cache. Do not include private workspace copies or logs.
    validation_source = ROOT / 'output/validation/v2'
    validation_target = stage / 'output/validation/v2'
    for name in ['README.md', 'report.json', 'report-initial.json', 'lora-task.json',
                 'segmentation-task.json', 'pca-task.json', 'discovery-comparison.json', 'sources.json', 'tasks.json',
                 'exact-id-lookup.json', 'clean_install.json', 'clean_install_wheel.json',
                 'clean_install_tests.json', 'startup_script.json',
                 'method_quality.json', 'method_quality.md', 'ui/result.json',
                 'reading/result.json', 'checks/results.json', 'checks/results-final.json']:
        source = validation_source / name
        if source.is_file():
            target = validation_target / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
    for folder in ['sources', 'http', 'discovery', 'discovery-after', 'exact-id-discovery']:
        source = validation_source / folder
        if source.is_dir():
            shutil.copytree(source, validation_target / folder, ignore=shutil.ignore_patterns('*.log', '__pycache__'))

    environment = {'python': sys.version.split()[0], 'packages': {}}
    for name in ['pydantic', 'python-dotenv', 'pypdf', 'pytest', 'adapters', 'networkx', 'numpy',
                 'torch', 'transformers', 'huggingface-hub', 'tokenizers', 'PyMuPDF', 'Pillow', 'pytesseract']:
        try:
            environment['packages'][name] = version(name)
        except PackageNotFoundError:
            continue
    (stage / 'environment-tested.json').write_text(json.dumps(environment, indent=2), encoding='utf-8')
    (stage / 'requirements-verified-py312.txt').write_text(
        '# Tested constraints for Python 3.12; see README for lightweight/full install\n' +
        ''.join(f'{name}=={value}\n' for name, value in environment['packages'].items()), encoding='utf-8')
    guide = (stage / 'docs/workspace_guide.md').read_text(encoding='utf-8')
    (stage / 'README.md').write_text('# LitAudit 参赛代码运行说明\n\n赛道：01\n\n团队：牛来和豹拉\n\n作品：LitAudit\n\n' +
        (ROOT / 'README.md').read_text(encoding='utf-8') + '\n\nPython 3.12可选使用 requirements-verified-py312.txt 作为依赖约束；轻量安装不需要map依赖。\n', encoding='utf-8')

    # Check for the actual configured secret bytes without printing their values.
    from dotenv import dotenv_values
    configured = {**dotenv_values(ROOT / '.env'), **os.environ}
    secrets = [value.encode() for key, value in configured.items()
               if value and ('KEY' in key or 'TOKEN' in key or 'PASSWORD' in key) and len(value) >= 12]
    problems = []
    manifest = []
    for path in sorted(stage.rglob('*')):
        if not path.is_file():
            continue
        data = path.read_bytes()
        if any(secret in data for secret in secrets):
            problems.append(str(path.relative_to(stage)))
        manifest.append({'path': path.relative_to(stage).as_posix(), 'bytes': len(data), 'sha256': sha256(data).hexdigest()})
    if problems:
        raise RuntimeError('Secret scan blocked files: ' + ', '.join(problems))
    (stage / 'submission-manifest.json').write_text(json.dumps({'files': manifest}, ensure_ascii=False, indent=2), encoding='utf-8')
    output = ROOT / 'output/submission'
    output.mkdir(parents=True, exist_ok=True)
    archive = output / '01-牛来和豹拉-代码.zip'
    with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for path in sorted(stage.rglob('*')):
            if path.is_file():
                z.write(path, Path('LitAudit') / path.relative_to(stage))
    with zipfile.ZipFile(archive) as z:
        assert z.testzip() is None
        assert not any('/.env' in name and not name.endswith('/.env.example') for name in z.namelist())
    (output / '01-牛来和豹拉-代码.zip.sha256').write_text(sha256(archive.read_bytes()).hexdigest() + '  ' + archive.name + '\n', encoding='utf-8')
    (output / 'build-result.json').write_text(json.dumps({'archive': str(archive), 'staging': str(stage),
        'file_count': len(manifest) + 1, 'size_bytes': archive.stat().st_size, 'secret_scan': 'passed'}, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'archive': str(archive), 'files': len(manifest) + 1,
                      'bytes': archive.stat().st_size, 'secret_scan': 'passed'}, ensure_ascii=False))


if __name__ == '__main__':
    main()
