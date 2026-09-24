"""
vectors.py - a small local semantic index.

Text becomes a fixed-size vector by hashing words, word pairs and character
trigrams into buckets (the "hashing trick"), so "guitar" and "guitars" - or
"puppy" and "puppies" - land close together without any model download, and
recall works fully offline on a machine with no RAM to spare.

VectorIndex is the seam: anything with add / remove / search can replace it (a
Chroma or Qdrant collection fed by real embeddings, say) without touching the
memory code above it.
"""

import re
import zlib

import numpy as np

DIM = 768

STOPWORDS = frozenset("""
a about after again all also am an and any are as at be because been before being but by can could did do does
doing don't down for from had has have having he her here hers him his how i if in into is it its just me more most
my no nor not now of off on once only or other our out over own same she should so some such than that the their
them then there these they this those through to too under until up very was we were what when where which while
who why will with would you your yours yeah okay ok um uh like really get got let s t
going fine think thinking lately tonight today something thing things want know tell say said make made back still well
right good great sure maybe actually pretty little much many take took come came look looking need needs
""".split())

_WORD = re.compile(r"[a-z0-9']+")


def tokens(text):
    """Content words of `text` (no stopwords, no very short words)."""
    # contractions ("i'm", "it's") are grammar, not topics
    return [w for w in _WORD.findall(text.lower()) if len(w) > 2 and "'" not in w and w not in STOPWORDS]


def _bucket(feature):
    h = zlib.crc32(feature.encode("utf-8"))
    return h % DIM, 1.0 if (h >> 16) & 1 else -1.0


def embed(text) -> np.ndarray:
    vec = np.zeros(DIM, dtype=np.float32)
    words = tokens(text)
    for w in words:
        i, s = _bucket("w:" + w)
        vec[i] += s
        padded = f"^{w}$"
        for j in range(len(padded) - 2):  # character trigrams: fuzzy match across word forms
            i, s = _bucket("c:" + padded[j:j + 3])
            vec[i] += 0.25 * s
    for a, b in zip(words, words[1:]):
        i, s = _bucket(f"b:{a}_{b}")
        vec[i] += 0.6 * s
    n = float(np.linalg.norm(vec))
    return vec / n if n > 0 else vec


class VectorIndex:
    def __init__(self):
        self.ids = []
        self._vecs = np.zeros((0, DIM), dtype=np.float32)

    def __len__(self):
        return len(self.ids)

    def add(self, item_id, text_or_vec):
        vec = text_or_vec if isinstance(text_or_vec, np.ndarray) else embed(text_or_vec)
        self.ids.append(item_id)
        self._vecs = np.vstack([self._vecs, vec.reshape(1, -1)])

    def remove(self, item_id):
        if item_id in self.ids:
            i = self.ids.index(item_id)
            self.ids.pop(i)
            self._vecs = np.delete(self._vecs, i, axis=0)

    def search(self, query, k=5, min_score=0.0):
        """[(id, cosine similarity)] best first."""
        if not self.ids:
            return []
        q = query if isinstance(query, np.ndarray) else embed(query)
        if not np.any(q):
            return []
        scores = self._vecs @ q
        order = np.argsort(-scores)[:k]
        return [(self.ids[i], float(scores[i])) for i in order if scores[i] >= min_score]

    def similarity(self, item_id, query):
        if item_id not in self.ids:
            return 0.0
        q = query if isinstance(query, np.ndarray) else embed(query)
        return float(self._vecs[self.ids.index(item_id)] @ q)
