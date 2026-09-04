"""Digital Knowledge Memory: Collect, interpret, store, restore, and efficiently recall digital knowledge."""

from __future__ import annotations
import json
import math
import re
import time
from collections import Counter
from typing import Any, Dict, List, Optional, Set, Tuple


_STOPWORDS: Set[str] = {
    "a", "about", "above", "after", "again", "against", "all", "am", "an", "and",
    "any", "are", "aren't", "as", "at", "be", "because", "been", "before", "being",
    "below", "between", "both", "but", "by", "can", "can't", "cannot", "could",
    "couldn't", "did", "didn't", "do", "does", "doesn't", "doing", "don't", "down",
    "during", "each", "few", "for", "from", "further", "had", "hadn't", "has",
    "hasn't", "have", "haven't", "having", "he", "he'd", "he'll", "he's", "her",
    "here", "here's", "hers", "herself", "him", "himself", "his", "how", "how's",
    "i", "i'd", "i'll", "i'm", "i've", "if", "in", "into", "is", "isn't", "it",
    "it's", "its", "itself", "let's", "me", "more", "most", "mustn't", "my",
    "myself", "no", "nor", "not", "of", "off", "on", "once", "only", "or",
    "other", "ought", "our", "ours", "ourselves", "out", "over", "own", "same",
    "shan't", "she", "she'd", "she'll", "she's", "should", "shouldn't", "so",
    "some", "such", "than", "that", "that's", "the", "their", "theirs", "them",
    "themselves", "then", "there", "there's", "these", "they", "they'd", "they'll",
    "they're", "they've", "this", "those", "through", "to", "too", "under",
    "until", "up", "very", "was", "wasn't", "we", "we'd", "we'll", "we're",
    "we've", "were", "weren't", "what", "what's", "when", "when's", "where",
    "where's", "which", "while", "who", "who's", "whom", "why", "why's", "with",
    "won't", "would", "wouldn't", "you", "you'd", "you'll", "you're", "you've",
    "your", "yours", "yourself", "yourselves"
}


def tokenize(text: str) -> List[str]:
    """Tokenize text into lowercase alphanumeric words."""
    return re.findall(r"\b[a-zA-Z0-9_-]{2,}\b", text.lower())


def extract_keywords(text: str, top_n: int = 5) -> List[Tuple[str, int]]:
    """Extract significant keywords from text, filtered by stopwords."""
    tokens = [t for t in tokenize(text) if t not in _STOPWORDS]
    counts = Counter(tokens)
    return counts.most_common(top_n)


def interpret_data(text: str, metadata: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Analyze and interpret raw text data to extract insights and structure."""
    tokens = tokenize(text)
    keywords = extract_keywords(text, top_n=8)
    urls = re.findall(r'https?://[^\s<>"]+|www\.[^\s<>"]+', text)
    emails = re.findall(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b', text)
    numbers = re.findall(r'\b\d+(?:\.\d+)?\b', text)

    return {
        "length_chars": len(text),
        "word_count": len(tokens),
        "unique_words": len(set(tokens)),
        "keywords": [kw for kw, _ in keywords],
        "top_frequencies": dict(keywords),
        "urls": urls,
        "emails": emails,
        "numeric_values": [float(n) for n in numbers[:10]],
        "inferred_tags": [kw for kw, count in keywords if count > 1],
        "metadata": metadata or {},
    }


class DigitalMemory:
    """An efficient associative memory store with BM25 indexing and retention tracking."""

    def __init__(self, k1: float = 1.5, b: float = 0.75):
        self.k1 = k1
        self.b = b
        self.memories: Dict[str, Dict[str, Any]] = {}
        self.doc_freq: Counter[str] = Counter()
        self.next_id: int = 1

    @property
    def total_docs(self) -> int:
        return len(self.memories)

    @property
    def avg_doc_len(self) -> float:
        if not self.memories:
            return 0.0
        return sum(m["doc_len"] for m in self.memories.values()) / len(self.memories)

    def record(
        self,
        content: str,
        tags: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        item_id: Optional[str] = None
    ) -> str:
        """Store a new piece of digital knowledge and index it."""
        if item_id is None:
            item_id = f"mem_{self.next_id}"
            self.next_id += 1
        elif item_id in self.memories:
            self.remove(item_id)

        tokens = tokenize(content)
        interpretation = interpret_data(content, metadata)
        all_tags = set(tags or [])
        all_tags.update(interpretation["inferred_tags"])

        term_counts = Counter(tokens)
        for term in term_counts:
            self.doc_freq[term] += 1

        now = time.time()
        memory_entry = {
            "id": item_id,
            "content": content,
            "tokens": tokens,
            "term_counts": dict(term_counts),
            "doc_len": len(tokens),
            "tags": sorted(list(all_tags)),
            "metadata": metadata or {},
            "interpretation": interpretation,
            "created_at": now,
            "last_accessed": now,
            "access_count": 0,
            "strength": 1.0,
        }
        self.memories[item_id] = memory_entry
        return item_id

    def recall(
        self,
        query: str,
        top_k: int = 5,
        tag_filter: Optional[str] = None,
        reinforce_hits: bool = True
    ) -> List[Dict[str, Any]]:
        """Retrieve relevant memories using BM25 scoring adjusted by memory strength."""
        if not self.memories:
            return []

        q_tokens = tokenize(query)
        if not q_tokens:
            return []

        n_docs = self.total_docs
        avg_dl = self.avg_doc_len or 1.0
        now = time.time()

        scores: List[Tuple[float, str]] = []

        for item_id, doc in self.memories.items():
            if tag_filter and tag_filter not in doc["tags"]:
                continue

            # BM25 lexical score
            bm25_score = 0.0
            dl = doc["doc_len"]
            for token in q_tokens:
                if token in doc["term_counts"]:
                    tf = doc["term_counts"][token]
                    df = self.doc_freq.get(token, 0)
                    idf = math.log(1.0 + (n_docs - df + 0.5) / (df + 0.5))
                    numerator = tf * (self.k1 + 1.0)
                    denominator = tf + self.k1 * (1.0 - self.b + self.b * (dl / avg_dl))
                    bm25_score += idf * (numerator / denominator)

            if bm25_score <= 0:
                continue

            # Retention decay & reinforcement factor:
            # Retention decreases over time, but is sustained by access count and strength
            elapsed_hours = (now - doc["last_accessed"]) / 3600.0
            decay = math.exp(-0.05 * elapsed_hours / max(1.0, doc["strength"]))
            final_score = bm25_score * (0.5 + 0.5 * decay)

            scores.append((final_score, item_id))

        scores.sort(key=lambda x: x[0], reverse=True)
        results: List[Dict[str, Any]] = []

        for score, item_id in scores[:top_k]:
            entry = self.memories[item_id]
            if reinforce_hits:
                entry["access_count"] += 1
                entry["last_accessed"] = now
                entry["strength"] = min(10.0, entry["strength"] + 0.2)

            results.append({
                "id": entry["id"],
                "score": round(score, 4),
                "content": entry["content"],
                "tags": entry["tags"],
                "strength": round(entry["strength"], 2),
                "access_count": entry["access_count"],
                "metadata": entry["metadata"],
            })

        return results

    def reinforce(self, item_id: str, amount: float = 1.0) -> bool:
        """Reinforce the strength of a specific memory item."""
        if item_id in self.memories:
            self.memories[item_id]["strength"] = min(10.0, self.memories[item_id]["strength"] + amount)
            self.memories[item_id]["last_accessed"] = time.time()
            self.memories[item_id]["access_count"] += 1
            return True
        return False

    def remove(self, item_id: str) -> bool:
        """Remove a memory item and update inverted index counters."""
        if item_id not in self.memories:
            return False

        doc = self.memories.pop(item_id)
        for term in doc["term_counts"]:
            if self.doc_freq[term] > 1:
                self.doc_freq[term] -= 1
            else:
                del self.doc_freq[term]
        return True

    def store_to_json(self) -> str:
        """Serialize memory store state to a JSON string."""
        data = {
            "version": 1,
            "next_id": self.next_id,
            "k1": self.k1,
            "b": self.b,
            "memories": list(self.memories.values()),
        }
        return json.dumps(data, indent=2)

    @classmethod
    def restore_from_json(cls, json_str: str) -> "DigitalMemory":
        """Reconstruct a DigitalMemory store from serialized JSON."""
        data = json.loads(json_str)
        instance = cls(k1=data.get("k1", 1.5), b=data.get("b", 0.75))
        instance.next_id = data.get("next_id", 1)

        for mem in data.get("memories", []):
            instance.memories[mem["id"]] = mem
            for term in mem.get("term_counts", {}):
                instance.doc_freq[term] += 1

        return instance

    def summarize(self) -> Dict[str, Any]:
        """Summarize current state of the memory store."""
        tag_counts: Counter[str] = Counter()
        for doc in self.memories.values():
            for t in doc["tags"]:
                tag_counts[t] += 1

        avg_strength = (
            sum(m["strength"] for m in self.memories.values()) / len(self.memories)
            if self.memories else 0.0
        )

        return {
            "total_items": len(self.memories),
            "unique_terms_indexed": len(self.doc_freq),
            "tag_distribution": dict(tag_counts),
            "average_strength": round(avg_strength, 2),
        }