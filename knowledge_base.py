"""База знаний: разбивка текста на фрагменты + поиск BM25.

Без внешних сервисов и без embeddings — только стандартная библиотека.
Подходит для FAQ, прайса и описания услуг до ~нескольких сотен строк.
"""

import math
import re
from collections import Counter

_WORD_RE = re.compile(r"[а-яёa-z0-9]+", re.IGNORECASE)


def tokenize(text):
    return _WORD_RE.findall(text.lower())


def split_into_chunks(text, chunk_size=700, overlap=120):
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    chunks, current = [], ""
    for para in paragraphs:
        if len(current) + len(para) + 2 <= chunk_size:
            current = f"{current}\n\n{para}" if current else para
        else:
            if current:
                chunks.append(current)
            current = para
    if current:
        chunks.append(current)
    return chunks


class KnowledgeBase:
    def __init__(self, path, chunk_size=700, overlap=120, k1=1.5, b=0.75):
        with open(path, "r", encoding="utf-8") as f:
            raw = f.read()
        self.chunks = split_into_chunks(raw, chunk_size, overlap)
        self.k1, self.b = k1, b
        self._index()

    def _index(self):
        self.docs_tokens = [tokenize(c) for c in self.chunks]
        self.doc_len = [len(t) for t in self.docs_tokens]
        self.avgdl = sum(self.doc_len) / max(len(self.doc_len), 1)
        self.doc_freqs = [Counter(t) for t in self.docs_tokens]

        df = Counter()
        for freqs in self.doc_freqs:
            for term in freqs:
                df[term] += 1
        n = len(self.chunks)
        self.idf = {
            term: math.log(1 + (n - freq + 0.5) / (freq + 0.5))
            for term, freq in df.items()
        }

    def _score(self, query_tokens, idx):
        freqs = self.doc_freqs[idx]
        dl = self.doc_len[idx]
        score = 0.0
        for term in query_tokens:
            if term not in freqs:
                continue
            f = freqs[term]
            denom = f + self.k1 * (1 - self.b + self.b * dl / self.avgdl)
            score += self.idf.get(term, 0.0) * (f * (self.k1 + 1)) / denom
        return score

    def search(self, query, k=3):
        query_tokens = tokenize(query)
        if not query_tokens or not self.chunks:
            return []
        scored = [(self._score(query_tokens, i), i) for i in range(len(self.chunks))]
        scored.sort(reverse=True)
        return [self.chunks[i] for score, i in scored[:k] if score > 0]
