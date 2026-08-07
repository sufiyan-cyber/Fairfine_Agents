"""Semantic memory: near-duplicate detection + MV Act retrieval.

Backed by Qdrant when `QDRANT_URL` is set. Without it, an in-process cosine
index over the same embeddings serves the same interface, so duplicate
detection and rule retrieval behave identically in a demo with no cloud
dependencies.

Duplicate detection intentionally combines a *structured* signal (same plate,
same junction, inside the 60s window) with a *semantic* one (how alike the two
event descriptions are). Vector similarity alone would happily flag two
genuinely separate helmet violations by the same rider an hour apart.
"""

from __future__ import annotations

import hashlib
import math
import re
import threading
from datetime import datetime
from typing import Any

from ..config import settings
from ..schemas import DuplicateCheck, RuleCitation
from . import mv_act

_EMBED_DIM = 256
_lock = threading.RLock()


# --------------------------------------------------------------------------- #
# Embeddings
# --------------------------------------------------------------------------- #
def _tokenize(text: str) -> list[str]:
    return [t for t in re.split(r"[^a-z0-9]+", text.lower()) if t]


def _hash_embed(text: str) -> list[float]:
    """Deterministic hashed bag-of-words with L2 normalisation.

    Not a semantic model — but for short, vocabulary-constrained strings like
    violation descriptions and statute text it gives a stable, meaningful
    cosine ordering without any network call.
    """
    vec = [0.0] * _EMBED_DIM
    tokens = _tokenize(text)
    if not tokens:
        return vec
    for token in tokens:
        digest = hashlib.md5(token.encode()).digest()
        idx = int.from_bytes(digest[:4], "big") % _EMBED_DIM
        sign = 1.0 if digest[4] % 2 == 0 else -1.0
        vec[idx] += sign
    # Bigrams add a little word-order sensitivity.
    for a, b in zip(tokens, tokens[1:]):
        digest = hashlib.md5(f"{a}_{b}".encode()).digest()
        idx = int.from_bytes(digest[:4], "big") % _EMBED_DIM
        vec[idx] += 0.5 if digest[4] % 2 == 0 else -0.5
    norm = math.sqrt(sum(v * v for v in vec))
    return [v / norm for v in vec] if norm else vec


_genai_client: Any = None


def _get_genai_client() -> Any:
    """One shared Gemini client for the whole process.

    Creating `genai.Client()` per call — as this used to — leaks a connection
    pool every time, because google-genai's client cleanup is unreliable (see
    the `_async_httpx_client` AttributeError on aclose). In live mode every
    audit embeds several times, so those leaked pools accumulated until the
    container hit its memory limit and was killed. A module-level singleton
    holds exactly one pool for the life of the process.
    """
    global _genai_client
    if _genai_client is None:
        from google import genai

        if settings.live_vertex:
            # Project and location come from the environment `get_settings()`
            # already bridged; credentials are the runtime's own.
            _genai_client = genai.Client(vertexai=True)
        else:
            _genai_client = genai.Client(api_key=settings.gemini_api_key)
    return _genai_client


def embed(text: str) -> list[float]:
    """Gemini embeddings when available, hashed fallback otherwise."""
    if settings.live_llm:
        try:
            result = _get_genai_client().models.embed_content(
                model="gemini-embedding-001",
                contents=text,
            )
            values = list(result.embeddings[0].values)
            norm = math.sqrt(sum(v * v for v in values))
            return [v / norm for v in values] if norm else values
        except Exception:
            pass  # fall through to local embedding
    return _hash_embed(text)


def cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    return max(-1.0, min(1.0, sum(x * y for x, y in zip(a, b))))


# --------------------------------------------------------------------------- #
# Store
# --------------------------------------------------------------------------- #
class SemanticMemory:
    def __init__(self) -> None:
        self._local_rules: list[tuple[list[float], dict]] = []
        self._local_events: list[tuple[list[float], dict]] = []
        self._field_tokens: list[dict[str, set[str]]] = []
        self._idf: dict[str, float] = {}
        self._qdrant: Any = None
        self._dim = _EMBED_DIM
        self._ready = False
        self._backend = "local"

    # -- lifecycle ---------------------------------------------------------- #
    def ensure_ready(self) -> None:
        with _lock:
            if self._ready:
                return
            if settings.live_qdrant:
                try:
                    self._init_qdrant()
                    self._backend = "qdrant"
                except Exception:
                    self._qdrant = None
                    self._backend = "local"
            self._index_rules()
            self._ready = True

    def _collection(self, suffix: str) -> str:
        """Collection name, namespaced by prefix *and* embedding dimension.

        The dimension suffix matters: embeddings are 256-d from the local
        fallback but 3072-d from `gemini-embedding-001`, so a deployment that
        adds a Gemini key later would otherwise start writing wide vectors into
        a narrow collection and fail every upsert. Encoding the dimension in
        the name means the two never collide — and, unlike recreating the
        collection, it destroys nothing. That also makes it safe to point this
        at a Qdrant cluster shared with another project.
        """
        return f"{settings.qdrant_collection}_{suffix}_d{self._dim}"

    def _init_qdrant(self) -> None:
        from qdrant_client import QdrantClient
        from qdrant_client.models import Distance, VectorParams

        client = QdrantClient(
            url=settings.qdrant_url,
            api_key=settings.qdrant_api_key or None,
            timeout=10,
        )
        self._dim = len(embed("dimension probe"))
        for suffix in ("rules", "events"):
            name = f"{settings.qdrant_collection}_{suffix}_d{self._dim}"
            if not client.collection_exists(name):
                client.create_collection(
                    collection_name=name,
                    vectors_config=VectorParams(size=self._dim, distance=Distance.COSINE),
                )
        self._qdrant = client

    def _index_rules(self) -> None:
        docs = mv_act.corpus_documents()
        vectors = [(embed(d["text"]), d) for d in docs]
        self._local_rules = vectors
        self._build_lexical_index(docs)

        if self._qdrant is None:
            return
        try:
            from qdrant_client.models import PointStruct

            points = [
                PointStruct(
                    id=idx,
                    vector=vec,
                    payload={"section": doc["id"], **doc["metadata"]},
                )
                for idx, (vec, doc) in enumerate(vectors)
            ]
            self._qdrant.upsert(
                collection_name=self._collection("rules"), points=points
            )
        except Exception:
            self._qdrant = None
            self._backend = "local"

    def _build_lexical_index(self, docs: list[dict]) -> None:
        """IDF-weighted lexical index over the statute corpus.

        Plain token overlap ranks "helmet not worn on a two wheeler" under the
        *overloading* section, because "two" and "wheeler" appear in more
        documents than "helmet" does and so contribute more raw matches. IDF
        fixes that by weighting each query token by how rare it is in the
        corpus, letting the one discriminating word decide.
        """
        self._field_tokens = []
        doc_frequency: dict[str, int] = {}

        for doc in docs:
            meta = doc["metadata"]
            fields = {
                "keywords": {t for k in meta.get("keywords", []) for t in _tokenize(k)},
                "title": set(_tokenize(meta.get("title", ""))),
                "text": set(_tokenize(meta.get("text", ""))),
            }
            self._field_tokens.append(fields)
            for token in fields["keywords"] | fields["title"] | fields["text"]:
                doc_frequency[token] = doc_frequency.get(token, 0) + 1

        total = max(len(docs), 1)
        self._idf = {
            token: math.log(1 + total / (1 + df)) for token, df in doc_frequency.items()
        }

    def _lexical_score(self, query: str, doc_index: int) -> float:
        """Share of the query's *information* this document accounts for."""
        if doc_index >= len(self._field_tokens):
            return 0.0
        fields = self._field_tokens[doc_index]
        query_tokens = _tokenize(query)
        if not query_tokens:
            return 0.0

        # Unknown tokens still get a floor weight so a novel term is not free.
        total_weight = sum(self._idf.get(t, 1.0) for t in query_tokens)
        if total_weight <= 0:
            return 0.0

        matched = 0.0
        for token in query_tokens:
            weight = self._idf.get(token, 1.0)
            if token in fields["keywords"]:
                matched += weight * 1.0
            elif token in fields["title"]:
                matched += weight * 0.75
            elif token in fields["text"]:
                matched += weight * 0.5

        return min(matched / total_weight, 1.0)

    @property
    def backend(self) -> str:
        return self._backend

    # -- retrieval ---------------------------------------------------------- #
    def search_rules(self, query: str, top_k: int = 3) -> list[RuleCitation]:
        self.ensure_ready()
        query_vec = embed(query)
        scored: list[tuple[float, dict]] = []

        if self._qdrant is not None:
            try:
                hits = self._qdrant.query_points(
                    collection_name=self._collection("rules"),
                    query=query_vec,
                    limit=top_k,
                ).points
                for hit in hits:
                    payload = hit.payload or {}
                    scored.append((float(hit.score), payload))
            except Exception:
                scored = []

        if not scored:
            for idx, (vec, doc) in enumerate(self._local_rules):
                meta = doc["metadata"]
                score = 0.30 * cosine(query_vec, vec) + 0.70 * self._lexical_score(query, idx)
                if any(v in query for v in meta.get("violations", []) if v != "none"):
                    score += 0.5
                scored.append((score, meta))
            scored.sort(key=lambda x: x[0], reverse=True)
            scored = scored[:top_k]

        return [
            RuleCitation(
                section=meta.get("section", ""),
                title=meta.get("title", ""),
                text=meta.get("text", ""),
                penalty=meta.get("penalty", ""),
                relevance=round(min(max(score, 0.0), 1.0), 3),
            )
            for score, meta in scored
            if meta
        ]

    def rule_for_violation(self, violation_type: str) -> RuleCitation | None:
        """Statute lookup is deterministic; RAG supplements it with context."""
        entry = mv_act.section_for_violation(violation_type)
        if not entry:
            return None
        return RuleCitation(
            section=entry["section"],
            title=entry["title"],
            text=entry["text"],
            penalty=entry["penalty"],
            relevance=1.0,
        )

    # -- duplicate detection ------------------------------------------------ #
    def remember_event(
        self, challan_id: str, plate: str, location: str, violation_type: str, ts: str, description: str
    ) -> None:
        self.ensure_ready()
        text = f"{violation_type} {plate} {location} {description}"
        vec = embed(text)
        payload = {
            "challan_id": challan_id,
            "plate": plate,
            "location": location,
            "violation_type": violation_type,
            "ts": ts,
            "description": description,
        }
        with _lock:
            self._local_events.append((vec, payload))
            if len(self._local_events) > 2000:
                self._local_events = self._local_events[-2000:]

        if self._qdrant is not None:
            try:
                from qdrant_client.models import PointStruct

                point_id = int(hashlib.sha256(challan_id.encode()).hexdigest()[:12], 16) % (2**60)
                self._qdrant.upsert(
                    collection_name=self._collection("events"),
                    points=[PointStruct(id=point_id, vector=vec, payload=payload)],
                )
            except Exception:
                pass

    def check_duplicate(
        self,
        plate: str,
        location: str,
        violation_type: str,
        ts: str,
        description: str,
        candidates: list[dict],
    ) -> DuplicateCheck:
        """Flag a re-submission of an event we already ruled on.

        `candidates` are same-plate rows pulled from SQLite. A duplicate must
        satisfy all three: same plate, same location, and inside the configured
        time window. Semantic similarity is reported for transparency but is
        not on its own sufficient.
        """
        self.ensure_ready()
        if not plate or plate.upper() in {"UNKNOWN", "UNREADABLE"}:
            return DuplicateCheck(
                is_duplicate=False, note="Plate unreadable — duplicate check not meaningful."
            )

        event_vec = embed(f"{violation_type} {plate} {location} {description}")
        try:
            event_time = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            event_time = None

        best: tuple[float, dict, float] | None = None
        for cand in candidates:
            if cand.get("plate", "").upper() != plate.upper():
                continue
            try:
                cand_time = datetime.fromisoformat(
                    str(cand.get("event_ts", "")).replace("Z", "+00:00")
                )
            except (ValueError, AttributeError):
                continue
            if event_time is None:
                continue
            delta = abs((event_time - cand_time).total_seconds())
            if delta > settings.duplicate_window_seconds:
                continue
            if _normalise_location(cand.get("location", "")) != _normalise_location(location):
                continue

            cand_vec = embed(
                f"{cand.get('violation_type','')} {cand.get('plate','')} "
                f"{cand.get('location','')} {cand.get('description','')}"
            )
            sim = cosine(event_vec, cand_vec)
            if best is None or sim > best[0]:
                best = (sim, cand, delta)

        if best is None:
            return DuplicateCheck(
                is_duplicate=False,
                note=(
                    f"No prior event for {plate} at this location within "
                    f"{settings.duplicate_window_seconds}s."
                ),
            )

        sim, cand, delta = best
        same_violation = cand.get("violation_type") == violation_type
        is_dup = same_violation and sim >= 0.80
        return DuplicateCheck(
            is_duplicate=is_dup,
            similarity=round(sim, 3),
            matched_challan_id=cand.get("challan_id"),
            matched_ts=cand.get("event_ts"),
            seconds_apart=round(delta, 1),
            note=(
                f"Near-identical event {cand.get('challan_id')} logged {delta:.0f}s earlier "
                f"at the same location for the same plate."
                if is_dup
                else f"Prior event {delta:.0f}s earlier but different violation or low similarity."
            ),
        )


def _normalise_location(location: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (location or "").lower())


memory = SemanticMemory()
