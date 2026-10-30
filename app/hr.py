"""HR document RAG: PDF text extraction, chunking, and a Qdrant store using multilingual-e5 embeddings."""

import io
import logging
import re
import threading
import uuid
from dataclasses import dataclass

from pypdf import PdfReader
from qdrant_client import QdrantClient, models

from app.config import get_settings
from app.db import SessionLocal
from app.models import HrDocument
from app.vectors import HashEmbedder

log = logging.getLogger(__name__)


# --- text -----------------------------------------------------------------------------------


def extract_pages(data: bytes) -> list[str]:
    """Text of each PDF page, whitespace-normalised. Empty strings for pages without a text layer."""
    reader = PdfReader(io.BytesIO(data))
    pages = []
    for page in reader.pages:
        text = page.extract_text() or ""
        text = re.sub(r"(\w)-\n(\w)", r"\1\2", text)  # re-join words hyphenated across lines
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        pages.append(text.strip())
    return pages


@dataclass(frozen=True)
class Chunk:
    page: int  # 1-based
    index: int
    text: str


def _pieces(text: str, size: int) -> list[str]:
    """Split text into pieces of at most `size` chars at paragraph, line, sentence or word boundaries."""
    if len(text) <= size:
        return [text]
    for sep in ("\n\n", "\n", ". ", " "):
        parts = text.split(sep)
        if len(parts) > 1:
            out: list[str] = []
            for i, part in enumerate(parts):
                part = part + (sep.strip() if sep == ". " and i < len(parts) - 1 else "")
                out.extend(_pieces(part, size) if len(part) > size else [part])
            return [p for p in out if p.strip()]
    return [text[i : i + size] for i in range(0, len(text), size)]


def chunk_pages(pages: list[str], size: int, overlap: int) -> list[Chunk]:
    """Greedy packing of boundary-aligned pieces into ~`size`-char chunks, per page, with a tail overlap."""
    chunks: list[Chunk] = []
    for page_no, text in enumerate(pages, start=1):
        current = ""
        for piece in _pieces(text, size):
            piece = piece.strip()
            if current and len(current) + 1 + len(piece) > size:
                chunks.append(Chunk(page_no, len(chunks), current))
                tail = current[-overlap:]
                current = tail[tail.find(" ") + 1 :] if " " in tail else ""
            current = f"{current} {piece}".strip() if current else piece
        if current:
            chunks.append(Chunk(page_no, len(chunks), current))
    return chunks


# --- embeddings + store ---------------------------------------------------------------------


class E5Embedder:
    """multilingual-e5 expects 'query: ' / 'passage: ' prefixes."""

    def __init__(self, model_name: str) -> None:
        from fastembed import TextEmbedding

        self._model = TextEmbedding(model_name)
        self.dim = len(next(iter(self._model.embed(["query: dim"]))))

    def passages(self, texts: list[str]) -> list[list[float]]:
        return [v.tolist() for v in self._model.embed([f"passage: {t}" for t in texts], batch_size=16)]

    def query(self, text: str) -> list[float]:
        return next(iter(self._model.embed([f"query: {text}"]))).tolist()


class HashPassageEmbedder(HashEmbedder):
    """Offline embedder for tests (same interface as E5Embedder)."""

    def passages(self, texts: list[str]) -> list[list[float]]:
        return self.embed(texts)

    def query(self, text: str) -> list[float]:
        return self.embed([text])[0]


@dataclass(frozen=True)
class Passage:
    document_id: int
    document: str
    topic: str
    page: int
    text: str
    score: float


class HrStore:
    def __init__(self, client: QdrantClient, collection: str, embedder: E5Embedder | HashPassageEmbedder) -> None:
        self.client = client
        self.collection = collection
        self.embedder = embedder

    def ensure_collection(self) -> None:
        if self.client.collection_exists(self.collection):
            return
        self.client.create_collection(
            self.collection,
            vectors_config=models.VectorParams(size=self.embedder.dim, distance=models.Distance.COSINE),
        )
        for field, schema in (("document_id", models.PayloadSchemaType.INTEGER), ("topic", models.PayloadSchemaType.KEYWORD)):
            self.client.create_payload_index(self.collection, field, field_schema=schema)

    def add(self, doc: HrDocument, chunks: list[Chunk]) -> None:
        self.ensure_collection()
        batch = 64
        for start in range(0, len(chunks), batch):
            part = chunks[start : start + batch]
            vectors = self.embedder.passages([c.text for c in part])
            self.client.upsert(
                self.collection,
                points=[
                    models.PointStruct(
                        id=str(uuid.uuid5(uuid.NAMESPACE_URL, f"hr/{doc.id}/{c.index}")),
                        vector=v,
                        payload={
                            "document_id": doc.id,
                            "document": doc.title,
                            "topic": doc.topic,
                            "page": c.page,
                            "chunk": c.index,
                            "text": c.text,
                        },
                    )
                    for c, v in zip(part, vectors)
                ],
                wait=True,
            )

    def delete_document(self, document_id: int) -> None:
        if not self.client.collection_exists(self.collection):
            return
        self.client.delete(
            self.collection,
            points_selector=models.FilterSelector(
                filter=models.Filter(
                    must=[models.FieldCondition(key="document_id", match=models.MatchValue(value=document_id))]
                )
            ),
            wait=True,
        )

    def search(self, query: str, limit: int, topic: str | None = None) -> list[Passage]:
        if not self.client.collection_exists(self.collection):
            return []
        flt = None
        if topic:
            flt = models.Filter(must=[models.FieldCondition(key="topic", match=models.MatchValue(value=topic))])
        result = self.client.query_points(
            self.collection, query=self.embedder.query(query), query_filter=flt, limit=limit, with_payload=True
        )
        return [
            Passage(p.payload["document_id"], p.payload["document"], p.payload["topic"], p.payload["page"],
                    p.payload["text"], round(p.score, 3))
            for p in result.points
        ]


_store: HrStore | None = None
_store_lock = threading.Lock()


def get_hr_store() -> HrStore:
    """Created once, on first use: loading multilingual-e5-large takes a while (and downloads ~2.2 GB once).
    The lock keeps the startup warm-up and an early upload from loading the model twice."""
    global _store
    with _store_lock:
        if _store is None:
            settings = get_settings()
            embedder = (
                HashPassageEmbedder()
                if settings.embedding_provider == "hash"
                else E5Embedder(settings.hr_embedding_model)
            )
            _store = HrStore(QdrantClient(url=settings.qdrant_url), settings.hr_collection, embedder)
        return _store


def process_document(document_id: int, data: bytes) -> None:
    """Background job: extract, chunk, embed and index one uploaded PDF; records the outcome on the row."""
    settings = get_settings()
    with SessionLocal() as db:
        doc = db.get(HrDocument, document_id)
        if doc is None:
            return
        try:
            pages = extract_pages(data)
            chunks = chunk_pages(pages, settings.hr_chunk_chars, settings.hr_chunk_overlap)
            if not chunks:
                raise ValueError("No extractable text (is this a scanned PDF?)")
            store = get_hr_store()
            store.delete_document(doc.id)  # idempotent re-processing
            store.add(doc, chunks)
            doc.pages, doc.chunk_count, doc.status, doc.error = len(pages), len(chunks), "ready", None
            log.info("Indexed HR document %s: %d pages, %d chunks", doc.id, len(pages), len(chunks))
        except Exception as e:
            log.exception("Failed to process HR document %s", document_id)
            doc.status, doc.error = "failed", str(e)[:500] or e.__class__.__name__
        db.commit()
