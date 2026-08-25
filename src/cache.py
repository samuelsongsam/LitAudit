from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


class FileCache:
    """将未来 API 响应当本地 JSON 缓存。离线模式只读，不发起网络请求。"""

    def __init__(self, cache_dir: Path):
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def key(self, source: str, query: str) -> str:
        digest = hashlib.sha256(f"{source}::{query}".encode("utf-8")).hexdigest()[:16]
        return f"{source}-{digest}.json"

    def path_for(self, source: str, query: str) -> Path:
        return self.cache_dir / self.key(source, query)

    def get(self, source: str, query: str) -> Any | None:
        path = self.path_for(source, query)
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def put(self, source: str, query: str, payload: Any) -> Path:
        path = self.path_for(source, query)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        return path
