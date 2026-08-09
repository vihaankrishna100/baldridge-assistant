from __future__ import annotations

import math
import re
import threading
from collections import Counter
from dataclasses import dataclass

import numpy as np
from sklearn.decomposition import TruncatedSVD
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.preprocessing import normalize

from config import settings

TOKEN_RE = re.compile(r"[a-z0-9]+")

# Below this many chunks the LSA projection carries no real signal.
MIN_CHUNKS_FOR_LSA = 40

# Kept deliberately short. Over-aggressive stopword lists hurt policy lookups
# ("time off", "on call", "no contact") where the short words carry meaning.
STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "but", "by", "do", "does", "for",
    "from", "how", "i", "in", "is", "it", "of", "or", "that", "the", "there",
    "these", "this", "to", "was", "were", "what", "when", "where", "which",
    "who", "why", "with", "you", "your",
}


# Suffix stripping, applied to documents and queries alike. Staff type
# "resident", the handbook says "residents"; without this they don't match and
# the assistant escalates a question it could have answered.
#
# Deliberately limited to plurals and -ing/-ed. Broader rules (-est, -er, -ment)
# do more harm than good on a policy corpus: "-est" mangles request, test, and
# forest, and "-er" collapses under/other/after into nonsense. The goal is not
# linguistic correctness, only that a word and its inflections land on the SAME
# key — which is why the final step drops a trailing "e" (vehicle/vehicles and
# arrange/arranged agree only once both lose it).
_NO_STEM = {
    "less", "unless", "address", "process", "access", "witness", "illness",
    "business", "premises", "series", "species", "always", "plus", "gas",
    "bus", "class", "pass", "miss", "loss", "cross", "press", "dress", "staff",
    "is", "was", "has", "does", "yes", "this", "his", "us", "as", "its",
}

_ES_PLURAL = ("ses", "xes", "zes", "ches", "shes")


def stem(token: str) -> str:
    if token in _NO_STEM or len(token) <= 3:
        return token

    if token.endswith("ies") and len(token) > 4:
        token = token[:-3] + "y"
    elif token.endswith("sses"):
        token = token[:-2]
    elif token.endswith(_ES_PLURAL) and len(token) > 4:
        token = token[:-2]
    elif token.endswith("s") and not token.endswith("ss"):
        token = token[:-1]

    if token.endswith("ing") and len(token) > 5:
        token = token[:-3]
    elif token.endswith("ed") and len(token) > 4:
        token = token[:-2]

    # "submitted" -> "submitt" -> "submit"; leave ll/ss/zz alone.
    if len(token) > 3 and token[-1] == token[-2] and token[-1] not in "aeioulsz":
        token = token[:-1]

    if len(token) > 3 and token.endswith("e"):
        token = token[:-1]

    return token


def tokenize(text: str) -> list[str]:
    return [
        stem(t)
        for t in TOKEN_RE.findall(text.lower())
        if t not in STOPWORDS and len(t) > 1
    ]


# Staff type how they speak, not how a regulation is written. "A kid ran off"
# has to reach a standard that says "absent without permission"; without this
# the passage is never retrieved and the assistant hands over a phone number
# for something the documents plainly cover.
#
# Query-side only — documents are never rewritten. Each entry adds terms, so a
# miss costs nothing and a hit costs one extra token in the query vector.
SYNONYMS: dict[str, tuple[str, ...]] = {
    # who
    "kid": ("child", "youth", "resident"),
    "teen": ("youth", "adolescent", "child"),
    "boy": ("child", "youth", "resident"),
    "client": ("child", "youth", "resident"),
    # leaving without permission
    "ran": ("runaway", "absent", "permission"),
    "run": ("runaway", "absent", "permission"),
    "runaway": ("absent", "permission", "premises"),
    "awol": ("runaway", "absent", "permission"),
    "eloped": ("runaway", "absent", "permission"),
    "fled": ("runaway", "absent", "permission"),
    "missing": ("runaway", "absent", "permission"),
    "escaped": ("runaway", "absent", "premises"),
    # paperwork
    "writeup": ("incident", "report"),
    "paperwork": ("document", "report", "form"),
    "log": ("document", "record", "report"),
    "file": ("document", "submit", "report"),
    # people and roles
    "boss": ("supervisor", "director"),
    "manager": ("supervisor", "director"),
    "coworker": ("staff", "employee"),
    # medical
    "meds": ("medication", "medical"),
    "med": ("medication", "medical"),
    "doctor": ("medical", "physician", "health"),
    "sick": ("medical", "health", "illness"),
    "hurt": ("injury", "medical"),
    "injured": ("injury", "medical"),
    # behaviour
    "fight": ("altercation", "behavior", "incident"),
    "fighting": ("altercation", "behavior", "incident"),
    "hit": ("physical", "altercation", "incident"),
    "restrain": ("restraint", "seclusion", "physical"),
    "timeout": ("seclusion", "behavior"),
    "punish": ("discipline", "punishment", "behavior"),
    # time off / employment
    "pto": ("leave", "time", "off"),
    "vacation": ("leave", "time", "off"),
    "hire": ("employment", "staff", "hiring"),
    "fired": ("termination", "employment"),
    "training": ("train", "orientation", "education"),
    # money
    "money": ("funds", "expense", "purchase"),
    "buy": ("purchase", "expense"),
    "spend": ("purchase", "expense", "funds"),
    "reimburse": ("expense", "purchase", "funds"),
}


def expand(tokens: list[str]) -> list[str]:
    """Adds domain synonyms for terms the query actually used."""
    extra: list[str] = []
    for t in tokens:
        for alt in SYNONYMS.get(t, ()):  # stems below, so both sides match
            extra.append(stem(alt))
    return tokens + extra


def analyze(text: str) -> list[str]:
    """Unigrams + bigrams from the same tokenizer BM25 uses.

    Sharing the analyzer matters: sklearn's smoothed IDF never decays a term to
    zero, so on a small corpus its built-in tokenizer lets "what/is/the/for"
    carry real weight and every query looks like a partial match. Feeding it
    our stopword-filtered tokens keeps the cosine an honest overlap measure —
    which is what the refusal threshold is reading.
    """
    tokens = tokenize(text)
    return tokens + [f"{a}_{b}" for a, b in zip(tokens, tokens[1:])]


@dataclass
class Hit:
    chunk_id: str
    document_id: str
    document_title: str
    category: str
    visibility: str
    heading: str
    page: int | None
    text: str
    score: float          # 0..1 lexical-overlap confidence (the refusal gate)
    rank_score: float     # fused rank score (ordering only)


@dataclass
class _Entry:
    chunk_id: str
    document_id: str
    document_title: str
    category: str
    visibility: str
    heading: str
    page: int | None
    text: str
    tokens: list[str]


class BM25:
    """Okapi BM25. ~40 lines beats pulling in another dependency."""

    def __init__(self, corpus: list[list[str]], k1: float = 1.5, b: float = 0.75):
        self.k1 = k1
        self.b = b
        self.n_docs = len(corpus)
        self.doc_len = [len(d) for d in corpus]
        self.avg_len = (sum(self.doc_len) / self.n_docs) if self.n_docs else 0.0
        self.freqs: list[Counter[str]] = [Counter(d) for d in corpus]

        df: Counter[str] = Counter()
        for doc in corpus:
            df.update(set(doc))
        self.idf = {
            term: math.log(1 + (self.n_docs - count + 0.5) / (count + 0.5))
            for term, count in df.items()
        }

    def scores(self, query_tokens: list[str]) -> np.ndarray:
        out = np.zeros(self.n_docs, dtype=np.float32)
        if not self.n_docs or not self.avg_len:
            return out
        for term in set(query_tokens):
            idf = self.idf.get(term)
            if idf is None:
                continue
            for i, freq in enumerate(self.freqs):
                f = freq.get(term, 0)
                if not f:
                    continue
                denom = f + self.k1 * (
                    1 - self.b + self.b * self.doc_len[i] / self.avg_len
                )
                out[i] += idf * (f * (self.k1 + 1)) / denom
        return out


class HybridIndex:
    """BM25 + TF-IDF/LSA, fused with Reciprocal Rank Fusion.

    Fully self-contained: no embedding API, no document text leaving the host.
    Swap in a hosted embedder later by replacing `_dense_scores` — the Hit
    contract above is what the rest of the app depends on.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._entries: list[_Entry] = []
        self._bm25: BM25 | None = None
        self._vectorizer: TfidfVectorizer | None = None
        self._tfidf = None
        self._svd: TruncatedSVD | None = None
        self._dense = None
        self.ready = False

    # ------------------------------------------------------------ build

    def rebuild(self, store=None) -> int:
        """Rebuilds from every active chunk in the store.

        Takes the repo rather than a database session so the index does not
        care whether the chunks came from SQLite or Firestore.
        """
        if store is None:
            from repo import get_repo

            store = get_repo()
        entries = [
            _Entry(
                chunk_id=c.id,
                document_id=c.document_id,
                document_title=c.document_title,
                category=c.category,
                visibility=c.visibility,
                heading=c.heading,
                page=c.page,
                text=c.text,
                tokens=tokenize(f"{c.document_title} {c.heading} {c.text}"),
            )
            for c in store.iter_active_chunks()
        ]

        with self._lock:
            self._entries = entries
            if not entries:
                self._bm25 = None
                self._vectorizer = None
                self._tfidf = None
                self._svd = None
                self._dense = None
                self.ready = True
                return 0

            self._bm25 = BM25([e.tokens for e in entries])

            corpus = [f"{e.document_title}\n{e.heading}\n{e.text}" for e in entries]
            self._vectorizer = TfidfVectorizer(
                analyzer=analyze,
                sublinear_tf=True,
                min_df=1,
                max_df=0.95 if len(corpus) > 20 else 1.0,
            )
            self._tfidf = self._vectorizer.fit_transform(corpus)

            # LSA gives cheap synonym tolerance ("PTO" ~ "time off") without a
            # model download. On a tiny corpus the projection is degenerate —
            # every chunk looks similar to every query — so it stays off until
            # there is enough material for the components to mean something.
            n_components = min(256, self._tfidf.shape[1] - 1, len(entries) - 1)
            if len(entries) >= MIN_CHUNKS_FOR_LSA and n_components >= 16:
                self._svd = TruncatedSVD(n_components=n_components, random_state=0)
                dense = normalize(self._svd.fit_transform(self._tfidf))
                # Randomized SVD can degenerate on a pathological corpus. A
                # non-finite projection would poison every semantic score
                # silently, so fall back to lexical-only rather than serve it.
                if np.isfinite(dense).all():
                    self._dense = dense
                else:
                    print("[index] SVD produced non-finite values — semantic search disabled")
                    self._svd = None
                    self._dense = None
            else:
                self._svd = None
                self._dense = None

            self.ready = True
            return len(entries)

    # ------------------------------------------------------------ search

    def search(
        self,
        query: str,
        allowed_visibility: list[str],
        top_k: int | None = None,
        candidates: int | None = None,
    ) -> list[Hit]:
        top_k = top_k or settings.retrieval_top_k
        candidates = candidates or settings.retrieval_candidates

        with self._lock:
            if not self._entries or self._bm25 is None or self._vectorizer is None:
                return []

            allowed = set(allowed_visibility)
            # Evaluated before ranking so out-of-tier chunks cannot even
            # influence the fused order.
            permitted = np.array(
                [e.visibility in allowed for e in self._entries], dtype=bool
            )
            if not permitted.any():
                return []

            q_tokens = expand(tokenize(query))
            bm25 = self._bm25.scores(q_tokens)

            # The vectorizer runs `analyze` itself, so the expanded terms are
            # handed to it as text rather than re-tokenised.
            q_vec = self._vectorizer.transform([query + " " + " ".join(q_tokens)])
            lexical = np.asarray((self._tfidf @ q_vec.T).todense()).ravel()

            if self._dense is not None and self._svd is not None:
                q_dense = normalize(self._svd.transform(q_vec))
                semantic = (self._dense @ q_dense.T).ravel()
            else:
                semantic = lexical

            # Ranked lists are masked so disallowed tiers never even influence
            # the fused ordering.
            bm25 = np.where(permitted, bm25, -np.inf)
            semantic_masked = np.where(permitted, semantic, -np.inf)

            pool = min(candidates, int(permitted.sum()))
            bm25_rank = self._rank_map(bm25, pool)
            sem_rank = self._rank_map(semantic_masked, pool)

            K = 60.0
            fused: dict[int, float] = {}
            for idx, rank in bm25_rank.items():
                fused[idx] = fused.get(idx, 0.0) + 1.0 / (K + rank)
            for idx, rank in sem_rank.items():
                fused[idx] = fused.get(idx, 0.0) + 1.0 / (K + rank)

            ordered = sorted(fused.items(), key=lambda kv: kv[1], reverse=True)[:top_k]

            hits: list[Hit] = []
            for idx, rank_score in ordered:
                entry = self._entries[idx]
                # `score` is a real 0..1 confidence — that's what the refusal
                # threshold reads, not the RRF value (whose scale is an artifact
                # of list length). Semantic similarity only counts when at least
                # one query term actually appears in the chunk: a dense-vector
                # match with zero shared vocabulary cannot ground a citation,
                # and LSA cosines run high even for unrelated text.
                confidence = float(lexical[idx])
                if np.isfinite(bm25[idx]) and bm25[idx] > 0:
                    confidence = max(confidence, 0.5 * float(semantic[idx]))
                hits.append(
                    Hit(
                        chunk_id=entry.chunk_id,
                        document_id=entry.document_id,
                        document_title=entry.document_title,
                        category=entry.category,
                        visibility=entry.visibility,
                        heading=entry.heading,
                        page=entry.page,
                        text=entry.text,
                        score=round(max(0.0, min(1.0, confidence)), 4),
                        rank_score=round(float(rank_score), 6),
                    )
                )
            return hits

    @staticmethod
    def _rank_map(scores: np.ndarray, pool: int) -> dict[int, int]:
        if pool <= 0:
            return {}
        order = np.argsort(-scores)[:pool]
        return {
            int(idx): rank
            for rank, idx in enumerate(order, start=1)
            if np.isfinite(scores[idx]) and scores[idx] > 0
        }

    def stats(self) -> dict:
        with self._lock:
            return {
                "ready": self.ready,
                "chunks": len(self._entries),
                "documents": len({e.document_id for e in self._entries}),
                "semantic_enabled": self._dense is not None,
            }


index = HybridIndex()
