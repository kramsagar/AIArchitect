"""Step 5 - RAG part 1: turn runbooks into chunks. Concepts: structure-aware chunking (split on headings),
stable chunk ids for citations (runbooks#checkout-latency), metadata for filtering.

Run:  python steps/step05_chunking.py
"""

import re
from dataclasses import dataclass, field
from pathlib import Path

from common import CORPUS_DIRS


@dataclass
class Chunk:
    id: str  # stable citation id: "<doc>#<section>"
    doc: str
    section: str
    text: str
    meta: dict = field(default_factory=dict)


def chunk_markdown(text: str, doc: str, max_chars: int = 1200) -> list[Chunk]:
    chunks = []
    for part in re.split(r"(?m)^## ", text)[1:]:  # one chunk per "## section" (a whole runbook procedure)
        title, _, body = part.partition("\n")
        section = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
        body = f"{doc} > {title.strip()}\n{body.strip()}"[:max_chars]  # heading path gives the chunk context
        meta = {
            "type": "runbook" if doc == "runbooks" else doc.rstrip("s"),
            "alerts": sorted(set(re.findall(r"ShopSphere[A-Za-z]+", body))),
            "services": sorted({s for s in ("shopsphere-shop", "payments", "postgres", "redis") if s in body.lower()}),
        }
        chunks.append(Chunk(f"{doc}#{section}", doc, title.strip(), body, meta))
    return chunks


def load_corpus(dirs: list[Path] = CORPUS_DIRS) -> list[Chunk]:
    return [c for d in dirs for f in sorted(d.glob("*.md")) for c in chunk_markdown(f.read_text("utf-8"), f.stem)]


def main() -> None:
    chunks = load_corpus()
    print(f"{len(chunks)} chunks from {[str(d.relative_to(CORPUS_DIRS[0].parents[1])) for d in CORPUS_DIRS]}\n")
    for c in chunks:
        print(f"{c.id:45} {len(c.text):5} chars  {c.meta}")
    print("\nExample chunk:\n" + chunks[0].text[:400])


if __name__ == "__main__":
    main()
