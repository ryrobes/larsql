#!/usr/bin/env python3
import argparse
import hashlib
import json
import re
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

REGISTRIES_URL = "https://ui.shadcn.com/r/registries.json"

HTML_EXTS = {".html", ".htm"}
STYLE_EXTS = {".css", ".scss", ".sass", ".less"}
REACT_EXTS = {".tsx", ".jsx"}
VUE_EXTS = {".vue"}
SVELTE_EXTS = {".svelte"}
JS_EXTS = {".js", ".mjs", ".cjs", ".ts"}

REACT_PATTERNS = [
    re.compile(r"\bfrom\s+[\"']react[\"']"),
    re.compile(r"\bimport\s+React\b"),
    re.compile(r"\buse(State|Effect|Memo|Ref|Callback|Reducer|Context)\b"),
    re.compile(r"\bforwardRef\b"),
    re.compile(r"\bcreateContext\b"),
    re.compile(r"\bclassName\s*="),
    re.compile(r"\buse client\b"),
]
VUE_PATTERNS = [re.compile(r"<template>"), re.compile(r"\bdefineComponent\b")]
SVELTE_PATTERNS = [re.compile(r"<script"), re.compile(r"\bexport\s+let\b"), re.compile(r"svelte:")]
HTML_TAG = re.compile(r"<[a-zA-Z][^>]*>")
HTMX_ATTR = re.compile(r"\bhx-[a-zA-Z-]+\s*=")


class JsonCache:
    def __init__(self, cache_dir: Path, refresh: bool = False) -> None:
        self.cache_dir = cache_dir
        self.refresh = refresh
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def load(self, url: str) -> Dict[str, Any]:
        key = hashlib.sha256(url.encode("utf-8")).hexdigest()
        path = self.cache_dir / f"{key}.json"
        if path.exists() and not self.refresh:
            return json.loads(path.read_text(encoding="utf-8"))
        data = fetch_json(url)
        path.write_text(json.dumps(data, ensure_ascii=True), encoding="utf-8")
        return data


def fetch_json(url: str, timeout: int = 20) -> Dict[str, Any]:
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        raw = resp.read()
    return json.loads(raw.decode("utf-8"))


def path_exts(files: Iterable[Dict[str, Any]]) -> List[str]:
    exts = set()
    for entry in files:
        if not isinstance(entry, dict):
            continue
        path = entry.get("path", "")
        if not path:
            continue
        exts.add(Path(path).suffix.lower())
    return sorted(exts)


def classify_by_paths(exts: List[str]) -> str:
    ext_set = set(exts)
    if ext_set & REACT_EXTS:
        return "react"
    if ext_set & VUE_EXTS:
        return "vue"
    if ext_set & SVELTE_EXTS:
        return "svelte"
    if ext_set & HTML_EXTS:
        return "html"
    if ext_set & STYLE_EXTS:
        return "css"
    if ext_set & JS_EXTS:
        return "js"
    return "unknown"


def extract_html_snippet(contents: Iterable[str], max_chars: int) -> Optional[str]:
    for content in contents:
        if not content:
            continue
        lines = content.splitlines()
        start_idx = None
        for i, line in enumerate(lines):
            if "<" in line and HTML_TAG.search(line):
                start_idx = i
                break
        if start_idx is None:
            continue
        snippet = "\n".join(lines[start_idx:]).strip()
        if not snippet:
            continue
        return snippet[:max_chars]
    return None


def analyze_content(item_json: Dict[str, Any], exts: List[str], max_chars: int) -> Dict[str, Any]:
    files = item_json.get("files", []) or []
    contents = [f.get("content", "") for f in files if isinstance(f, dict)]
    combined = "\n".join(contents)

    ext_set = set(exts)
    react_signal = any(p.search(combined) for p in REACT_PATTERNS)
    vue_signal = any(p.search(combined) for p in VUE_PATTERNS)
    svelte_signal = any(p.search(combined) for p in SVELTE_PATTERNS)
    htmx_signal = HTMX_ATTR.search(combined) is not None
    html_signal = HTML_TAG.search(combined) is not None

    framework = "unknown"
    if ext_set & REACT_EXTS:
        framework = "react"
    elif ext_set & VUE_EXTS:
        framework = "vue"
    elif ext_set & SVELTE_EXTS:
        framework = "svelte"
    elif react_signal:
        framework = "react"
    elif vue_signal:
        framework = "vue"
    elif svelte_signal:
        framework = "svelte"
    elif htmx_signal:
        framework = "htmx"
    elif html_signal:
        framework = "html"
    elif set(exts) & STYLE_EXTS:
        framework = "css"

    requires_js = htmx_signal or ("<script" in combined) or bool(set(exts) & JS_EXTS)
    snippet = None
    if framework in {"html", "htmx"}:
        snippet = extract_html_snippet(contents, max_chars)

    return {
        "framework": framework,
        "requires_js": requires_js,
        "html_snippet": snippet,
        "htmx": htmx_signal,
    }


def normalize_categories(item: Dict[str, Any]) -> List[str]:
    cats: List[str] = []
    for key in ("categories", "category", "tags"):
        value = item.get(key)
        if isinstance(value, list):
            cats.extend(str(v) for v in value if v)
        elif isinstance(value, str):
            cats.append(value)
    return list(dict.fromkeys(cats))


def build_record(
    registry_id: str,
    registry_pattern: str,
    registry_homepage: Optional[str],
    item: Dict[str, Any],
    exts: List[str],
    analysis: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    categories = normalize_categories(item)
    record = {
        "name": item.get("name"),
        "library": registry_id.lstrip("@"),
        "registry": registry_id,
        "registry_url_template": registry_pattern,
        "registry_homepage": registry_homepage,
        "type": item.get("type"),
        "title": item.get("title"),
        "description": item.get("description"),
        "categories": categories,
        "category": categories[0] if categories else None,
        "variants": [],
        "files": item.get("files", []),
        "file_extensions": exts,
    }
    if analysis:
        record.update(analysis)
    else:
        record.update(
            {
                "framework": classify_by_paths(exts),
                "requires_js": bool(set(exts) & JS_EXTS),
                "html_snippet": None,
                "htmx": False,
            }
        )
    return record


def iter_registries(
    cache: JsonCache,
    max_registries: Optional[int],
    delay: float,
) -> Iterable[Tuple[str, str, Dict[str, Any]]]:
    registries = cache.load(REGISTRIES_URL)
    for idx, (registry_id, pattern) in enumerate(registries.items()):
        if max_registries is not None and idx >= max_registries:
            break
        registry_url = pattern.replace("{name}", "registry")
        try:
            data = cache.load(registry_url)
        except Exception as exc:
            print(f"warn: failed registry {registry_id} {registry_url}: {exc}", file=sys.stderr)
            continue
        yield registry_id, pattern, data
        if delay:
            time.sleep(delay)


def main() -> int:
    parser = argparse.ArgumentParser(description="Scrape shadcn registry directory for HTML/HTMX candidates.")
    parser.add_argument("--output", default="data/shadcn-html-components.jsonl", help="Output JSONL path.")
    parser.add_argument("--cache-dir", default="data/.cache", help="Cache directory for fetched JSON.")
    parser.add_argument("--refresh", action="store_true", help="Ignore cache and re-fetch.")
    parser.add_argument("--scan-content", action="store_true", help="Fetch item JSON and scan contents.")
    parser.add_argument("--only-html", action="store_true", help="Only emit html/htmx/css records.")
    parser.add_argument("--max-registries", type=int, default=None, help="Limit registries (debug).")
    parser.add_argument("--max-items", type=int, default=None, help="Limit items per registry (debug).")
    parser.add_argument("--delay", type=float, default=0.0, help="Delay between registry fetches.")
    parser.add_argument("--snippet-chars", type=int, default=800, help="Max HTML snippet chars.")
    args = parser.parse_args()

    cache = JsonCache(Path(args.cache_dir), refresh=args.refresh)
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    total = 0
    kept = 0
    with output_path.open("w", encoding="utf-8") as handle:
        for registry_id, pattern, registry in iter_registries(cache, args.max_registries, args.delay):
            registry_homepage = registry.get("homepage")
            items = registry.get("items", []) or []
            if args.max_items is not None:
                items = items[: args.max_items]
            for item in items:
                files = item.get("files", []) or []
                exts = path_exts(files)
                total += 1

                analysis = None
                if args.scan_content:
                    item_url = pattern.replace("{name}", str(item.get("name")))
                    try:
                        item_json = cache.load(item_url)
                    except Exception as exc:
                        print(f"warn: failed item {registry_id}/{item.get('name')}: {exc}", file=sys.stderr)
                        continue
                    analysis = analyze_content(item_json, exts, args.snippet_chars)

                record = build_record(
                    registry_id,
                    pattern,
                    registry_homepage,
                    item,
                    exts,
                    analysis,
                )

                if args.only_html and record.get("framework") not in {"html", "htmx", "css"}:
                    continue

                handle.write(json.dumps(record, ensure_ascii=True) + "\n")
                kept += 1

    print(f"wrote {kept} records out of {total} items to {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
