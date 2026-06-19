#!/usr/bin/env python3
"""Ingest tradecraft documents into RAG knowledge base."""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from config import config
from core.rag import RAGStore


def main():
    parser = argparse.ArgumentParser(description="Ingest documents into NEXUS-01 RAG")
    parser.add_argument("path", nargs="?", default=config.docs_path, help="File or directory to ingest")
    parser.add_argument("--pattern", default="**/*.md", help="Glob pattern for directories")
    args = parser.parse_args()

    rag = RAGStore(
        chroma_path=config.chroma_path,
        supabase_url=config.supabase_url,
        supabase_key=config.supabase_key,
    )

    target = Path(args.path)
    if target.is_file():
        n = rag.ingest_file(target)
        print(f"Ingested {n} chunks from {target}")
    elif target.is_dir():
        stats = rag.ingest_directory(target, args.pattern)
        print(f"Ingested {stats['chunks']} chunks from {stats['files']} files")
        if stats["errors"]:
            for e in stats["errors"]:
                print(f"  Error: {e}")
    else:
        print(f"Path not found: {target}")
        sys.exit(1)

    print(f"RAG stats: {rag.stats()}")


if __name__ == "__main__":
    main()
