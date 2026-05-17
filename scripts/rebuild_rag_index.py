"""Rebuild the formal Chroma RAG index from Markdown knowledge bases."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata as importlib_metadata
import importlib.util
import json
import re
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any


_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))
from _bootstrap import setup_project_paths

PROJECT_ROOT = setup_project_paths()

from mining_risk_serve.harness.knowledge_base import KnowledgeBaseManager
from mining_risk_serve.harness.vector_store import VectorStore, split_by_headers
from mining_risk_common.utils.config import get_config, resolve_project_path


DEFAULT_SOURCE_COMMIT = "2f0819487bdaf2a8495f15c260015cbf932d29d3"
DEFAULT_REPORT_PATH = "reports/rag_index_rebuild_run.json"


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _rel_project(path: Path) -> str:
    try:
        return path.resolve().relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def _dependency_state() -> dict[str, dict[str, Any]]:
    modules = {
        "chromadb": "chromadb",
        "sentence_transformers": "sentence-transformers",
        "torch": "torch",
        "transformers": "transformers",
        "safetensors": "safetensors",
        "faiss": "faiss-cpu",
    }
    state: dict[str, dict[str, Any]] = {}
    for module_name, package_name in modules.items():
        available = importlib.util.find_spec(module_name) is not None
        version = None
        if available:
            try:
                version = importlib_metadata.version(package_name)
            except importlib_metadata.PackageNotFoundError:
                version = "installed-version-unknown"
        state[module_name] = {"available": available, "version": version}
    return state


def _iter_kb_files(kb_dir: Path) -> list[Path]:
    main_files = []
    for filename in KnowledgeBaseManager.KNOWLEDGE_FILES:
        path = kb_dir / filename
        if path.exists():
            main_files.append(path)

    seen = {path.resolve() for path in main_files}
    recursive_files = [
        path for path in kb_dir.rglob("*.md")
        if path.resolve() not in seen and path.is_file()
    ]
    return main_files + sorted(recursive_files, key=lambda p: p.as_posix())


def _doc_type(path: Path) -> str:
    name = path.name
    if "合规" in name:
        return "compliance"
    if "SOP" in name or "审核" in name:
        return "sop"
    if "物理" in name or "传感器" in name:
        return "physics"
    if "执行条件" in name:
        return "conditions"
    if "事故" in name or "案例" in name:
        return "cases"
    if "历史" in name or "记忆" in name:
        return "history"
    return "general"


def _scenario(path: Path, text: str) -> str:
    parts = {part.lower() for part in path.parts}
    if "dust" in parts:
        return "dust"
    if "chemical" in parts:
        return "chemical"
    if "metallurgy" in parts:
        return "metallurgy"
    if any(token in text for token in ("粉尘", "涉爆", "除尘")):
        return "dust"
    if any(token in text for token in ("冶金", "煤气", "熔融", "高炉", "转炉")):
        return "metallurgy"
    if any(token in text for token in ("危化", "危险化学", "储罐", "泄漏")):
        return "chemical"
    if any(token in text for token in ("有限空间", "受限空间", "缺氧", "中毒窒息")):
        return "confined_space"
    return "general"


def _risk_type(text: str) -> str:
    if any(token in text for token in ("粉尘", "涉爆", "除尘")):
        return "粉尘涉爆"
    if any(token in text for token in ("冶金", "煤气", "熔融", "高炉", "转炉")):
        return "冶金煤气"
    if any(token in text for token in ("危化", "危险化学", "储罐", "泄漏", "可燃气体")):
        return "危化品"
    if any(token in text for token in ("有限空间", "受限空间", "缺氧", "中毒窒息", "中毒和窒息")):
        return "有限空间"
    if any(token in text for token in ("火灾", "爆炸")):
        return "火灾爆炸"
    return "general"


def _extract_ids(text: str, section_title: str) -> dict[str, str]:
    combined = f"{section_title}\n{text}"
    rule_ids = re.findall(r"\b(?:COM|PHY|SRC)-[A-Z]+-\d{3}\b", combined)
    sop_ids = re.findall(r"\bSOP-[A-Z]+(?:-[A-Z0-9]+)*\b", combined)
    case_ids = re.findall(r"\b[A-E]-\d{3}\b", combined)
    return {
        "rule_id": ";".join(dict.fromkeys(rule_ids)),
        "sop_id": ";".join(dict.fromkeys(sop_ids)),
        "case_id": ";".join(dict.fromkeys(case_ids)),
    }


def _build_chunks(
    kb_dir: Path,
    source_commit: str,
    build_time: str,
) -> tuple[list[str], list[dict[str, Any]], list[str], Counter[str]]:
    config = get_config()
    rag_config = config.harness.memory.long_term.rag
    chunk_size = int(rag_config.get("chunk_size", 300))
    chunk_overlap = int(rag_config.get("chunk_overlap", 50))

    documents: list[str] = []
    metadatas: list[dict[str, Any]] = []
    ids: list[str] = []
    per_file: Counter[str] = Counter()

    for path in _iter_kb_files(kb_dir):
        data = path.read_bytes()
        content = data.decode("utf-8")
        kb_sha = _sha256(data)
        source_file = _rel_project(path)
        doc_type = _doc_type(path)

        chunks = split_by_headers(content, max_chunk_size=chunk_size, overlap=chunk_overlap)
        for chunk_index, chunk in enumerate(chunks):
            text = chunk["text"].strip()
            if not text:
                continue
            section_title = str(chunk.get("metadata", {}).get("section_title", ""))
            section_level = int(chunk.get("metadata", {}).get("section_level", 0) or 0)
            parsed_ids = _extract_ids(text, section_title)
            metadata = {
                "source_file": source_file,
                "doc_type": doc_type,
                "section_title": section_title,
                "section_level": section_level,
                "risk_type": _risk_type(text),
                "scenario": _scenario(path, text),
                "rule_id": parsed_ids["rule_id"],
                "sop_id": parsed_ids["sop_id"],
                "case_id": parsed_ids["case_id"],
                "kb_sha256": kb_sha,
                "source_commit": source_commit,
                "build_time": build_time,
                "chunk_index": chunk_index,
            }
            chunk_id_seed = f"{source_file}:{chunk_index}:{kb_sha}:{text}"
            chunk_id = f"kb_{hashlib.sha256(chunk_id_seed.encode('utf-8')).hexdigest()}"
            documents.append(text)
            metadatas.append(metadata)
            ids.append(chunk_id)
            per_file[source_file] += 1

    return documents, metadatas, ids, per_file


def rebuild_index(args: argparse.Namespace) -> dict[str, Any]:
    kb_dir = resolve_project_path(args.kb_dir)
    persist_dir = resolve_project_path(args.persist_dir)
    report_path = resolve_project_path(args.report_json)
    build_time = datetime.now().isoformat(timespec="seconds")

    documents, metadatas, ids, per_file = _build_chunks(
        kb_dir=kb_dir,
        source_commit=args.source_commit,
        build_time=build_time,
    )

    store = VectorStore(
        collection_name=args.collection_name,
        persist_directory=str(persist_dir),
        embedding_backend=args.embedding_backend,
    )
    if args.clear:
        store.reset_collection()

    batch_size = args.batch_size
    for start in range(0, len(documents), batch_size):
        end = start + batch_size
        store.add_documents(
            documents=documents[start:end],
            metadatas=metadatas[start:end],
            ids=ids[start:end],
        )

    collection_count = store.collection.count()
    report = {
        "build_time": build_time,
        "kb_dir": str(kb_dir),
        "persist_directory": str(persist_dir),
        "collection_name": store.collection_name,
        "embedding_backend": store.embedding_backend,
        "fallback_embedding_used": store.embedding_backend == "fallback",
        "source_commit": args.source_commit,
        "chunk_count_added": len(documents),
        "collection_count": collection_count,
        "per_source_file_chunk_count": dict(sorted(per_file.items())),
        "dependencies": _dependency_state(),
    }

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--clear", action="store_true", help="Delete and recreate the target Chroma collection first.")
    parser.add_argument("--kb-dir", default="knowledge_base", help="Knowledge base directory to index.")
    parser.add_argument("--persist-dir", default="var/chroma", help="Chroma persist directory.")
    parser.add_argument("--collection-name", default="knowledge_base", help="Chroma collection name.")
    parser.add_argument(
        "--embedding-backend",
        default="auto",
        choices=["auto", "fallback", "deterministic", "sentence_transformers"],
        help="Embedding backend. auto falls back when real BGE dependencies are unavailable.",
    )
    parser.add_argument("--source-commit", default=DEFAULT_SOURCE_COMMIT, help="AgentFS snapshot commit id to stamp into metadata.")
    parser.add_argument("--batch-size", type=int, default=100, help="Chroma insert batch size.")
    parser.add_argument("--report-json", default=DEFAULT_REPORT_PATH, help="Path for JSON run report.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    report = rebuild_index(args)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
