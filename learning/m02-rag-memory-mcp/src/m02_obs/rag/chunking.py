"""Structure-aware chunking for Markdown runbooks.

Runbooks are written in sections that each answer one question ("checkout is slow"), so the heading is the natural
chunk boundary. Long sections are split on paragraphs with a one-paragraph overlap. Every chunk keeps a stable id
(`doc#section`) that the agent cites and a reader can open."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

HEADING = re.compile(r"^(#{1,3})\s+(.*)$")
FRONT_MATTER = re.compile(r"^---\n(.*?)\n---\n", re.DOTALL)
SERVICES = ("shopsphere-shop", "payments-service", "payments", "postgres", "redis", "checkout", "search", "catalog")
ALERT = re.compile(r"ShopSphere[A-Za-z0-9]+")


@dataclass
class Chunk:
    id: str
    doc: str
    section: str
    text: str
    metadata: dict[str, object] = field(default_factory=dict)


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def _split_long(text: str, max_chars: int) -> list[str]:
    paras = [p for p in re.split(r"\n\s*\n", text) if p.strip()]
    out: list[str] = []
    cur: list[str] = []
    for p in paras:
        if cur and sum(len(x) for x in cur) + len(p) > max_chars:
            out.append("\n\n".join(cur))
            cur = cur[-1:]  # overlap: carry the last paragraph so context is not cut mid-thought
        cur.append(p)
    if cur:
        out.append("\n\n".join(cur))
    return out


def chunk_markdown(text: str, doc: str, *, max_chars: int = 1200, doc_type: str | None = None) -> list[Chunk]:
    meta_type = doc_type
    if m := FRONT_MATTER.match(text):
        for line in m.group(1).splitlines():
            if line.startswith("type:"):
                meta_type = line.split(":", 1)[1].strip()
        text = text[m.end() :]
    meta_type = meta_type or ("runbook" if "runbook" in doc else "doc")

    sections: list[tuple[str, list[str]]] = []
    title = doc
    for line in text.splitlines():
        h = HEADING.match(line)
        if h and len(h.group(1)) == 1:
            title = h.group(2).strip()
            continue
        if h:
            sections.append((h.group(2).strip(), []))
        elif sections:
            sections[-1][1].append(line)
    chunks: list[Chunk] = []
    for heading, lines in sections:
        body = "\n".join(lines).strip()
        if not body:
            continue
        parts = _split_long(body, max_chars)
        for i, part in enumerate(parts):
            slug = slugify(heading)
            lowered = (heading + " " + part).lower()
            chunks.append(
                Chunk(
                    id=f"{doc}#{slug}" + (f"-{i + 1}" if len(parts) > 1 else ""),
                    doc=doc,
                    section=heading,
                    text=f"{title} > {heading}\n{part}",  # heading path in the text improves retrieval
                    metadata={
                        "type": meta_type,
                        "services": sorted({s for s in SERVICES if s in lowered}),
                        "alerts": sorted(set(ALERT.findall(part))),
                    },
                )
            )
    return chunks


def load_corpus(dirs: list[Path], max_chars: int = 1200) -> list[Chunk]:
    chunks: list[Chunk] = []
    for d in dirs:
        for path in sorted(Path(d).glob("*.md")):
            chunks += chunk_markdown(path.read_text(encoding="utf-8"), path.stem, max_chars=max_chars)
    return chunks


def default_corpus_dirs() -> list[Path]:
    """Package corpus plus the lab runbooks (found by walking up to the repo's lab/docs)."""
    here = Path(__file__).resolve()
    dirs = [here.parent.parent / "corpus"]
    for parent in here.parents:
        if (parent / "lab" / "docs" / "runbooks.md").exists():
            dirs.append(parent / "lab" / "docs")
            break
    return dirs
