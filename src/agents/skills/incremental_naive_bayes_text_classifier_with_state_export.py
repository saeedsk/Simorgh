import io
import json
import math
import re
from collections import Counter, defaultdict
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple, Union


class IncrementalNaiveBayes:
    """Incremental Multinomial Naive Bayes text classifier with state export.

    Supports online/incremental updates, tokenization with optional stopword
    filtering, additive (Laplace) smoothing, probability prediction with
    log-sum-exp stabilization, feature importance inspection, and full
    state export/import via dictionaries, JSON, or files.
    """

    def __init__(
        self,
        alpha: float = 1.0,
        lowercase: bool = True,
        token_pattern: str = r"\b\w+\b",
        stopwords: Optional[Iterable[str]] = None,
    ) -> None:
        if alpha <= 0:
            raise ValueError(f"Smoothing parameter alpha must be positive, got {alpha}")
        self.alpha = float(alpha)
        self.lowercase = bool(lowercase)
        self.token_pattern = token_pattern
        self._compiled_regex = re.compile(token_pattern)

        if stopwords is not None:
            self.stopwords: Optional[set] = {
                s.lower() if self.lowercase else s for s in stopwords
            }
        else:
            self.stopwords = None

        # Learned state
        self.class_doc_counts: Dict[str, int] = defaultdict(int)
        self.class_token_counts: Dict[str, int] = defaultdict(int)
        self.feature_counts: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
        self.vocabulary: set = set()
        self.total_docs: int = 0

    def _tokenize(self, text: str) -> List[str]:
        """Extract tokens from input text according to configured pattern and stopwords."""
        if not isinstance(text, str):
            raise TypeError(f"Expected text string, got {type(text).__name__}")
        if self.lowercase:
            text = text.lower()
        tokens = self._compiled_regex.findall(text)
        if self.stopwords:
            tokens = [t for t in tokens if t not in self.stopwords]
        return tokens

    def train_one(self, text: str, label: Union[str, int]) -> "IncrementalNaiveBayes":
        """Incrementally update the model with a single document and label."""
        label_str = str(label)
        tokens = self._tokenize(text)

        self.class_doc_counts[label_str] += 1
        self.total_docs += 1

        cls_features = self.feature_counts[label_str]
        if tokens:
            token_counts = Counter(tokens)
            for token, count in token_counts.items():
                cls_features[token] += count
                self.vocabulary.add(token)
            self.class_token_counts[label_str] += len(tokens)
        else:
            # Ensure class is registered even if document produces no tokens
            _ = cls_features

        return self

    def train(
        self,
        texts: Sequence[str],
        labels: Sequence[Union[str, int]],
    ) -> "IncrementalNaiveBayes":
        """Incrementally update the model with a batch of documents and labels."""
        if len(texts) != len(labels):
            raise ValueError(
                f"Number of texts ({len(texts)}) and labels ({len(labels)}) must match"
            )
        for text, label in zip(texts, labels):
            self.train_one(text, label)
        return self

    @property
    def classes(self) -> List[str]:
        """List of observed class labels sorted lexicographically."""
        return sorted(self.class_doc_counts.keys())

    @property
    def vocabulary_size(self) -> int:
        """Total number of unique tokens in the training vocabulary."""
        return len(self.vocabulary)

    def _compute_log_posteriors(self, text: str) -> Dict[str, float]:
        """Compute unnormalized log joint probabilities log P(c, d) for each class."""
        if not self.class_doc_counts:
            raise RuntimeError("Classifier has not been trained on any data.")

        tokens = self._tokenize(text)
        token_counts = Counter(t for t in tokens if t in self.vocabulary)
        vocab_size = max(len(self.vocabulary), 1)

        log_posteriors: Dict[str, float] = {}
        for c, doc_count in self.class_doc_counts.items():
            log_prior = math.log(doc_count / self.total_docs)
            total_tokens_c = self.class_token_counts[c]
            denominator = total_tokens_c + self.alpha * vocab_size
            log_denom = math.log(denominator)

            cls_features = self.feature_counts[c]
            log_likelihood = 0.0
            for token, count in token_counts.items():
                word_count = cls_features.get(token, 0)
                log_p_w_given_c = math.log(word_count + self.alpha) - log_denom
                log_likelihood += count * log_p_w_given_c

            log_posteriors[c] = log_prior + log_likelihood

        return log_posteriors

    def predict_log_proba_one(self, text: str) -> Dict[str, float]:
        """Predict normalized log posterior probabilities for a single document."""
        log_post = self._compute_log_posteriors(text)
        max_log = max(log_post.values())
        sum_exp = sum(math.exp(lp - max_log) for lp in log_post.values())
        log_norm = max_log + math.log(sum_exp)
        return {c: log_post[c] - log_norm for c in sorted(log_post.keys())}

    def predict_proba_one(self, text: str) -> Dict[str, float]:
        """Predict class posterior probabilities for a single document."""
        log_post = self._compute_log_posteriors(text)
        max_log = max(log_post.values())
        exp_post = {c: math.exp(lp - max_log) for c, lp in log_post.items()}
        sum_exp = sum(exp_post.values())
        return {c: exp_post[c] / sum_exp for c in sorted(exp_post.keys())}

    def predict_one(self, text: str) -> str:
        """Predict the most likely class label for a single document."""
        log_post = self._compute_log_posteriors(text)
        return max(sorted(log_post.keys()), key=lambda c: log_post[c])

    def predict(self, texts: Sequence[str]) -> List[str]:
        """Predict class labels for a sequence of documents."""
        return [self.predict_one(text) for text in texts]

    def predict_proba(self, texts: Sequence[str]) -> List[Dict[str, float]]:
        """Predict class probabilities for a sequence of documents."""
        return [self.predict_proba_one(text) for text in texts]

    def predict_log_proba(self, texts: Sequence[str]) -> List[Dict[str, float]]:
        """Predict normalized log class probabilities for a sequence of documents."""
        return [self.predict_log_proba_one(text) for text in texts]

    def score(
        self, texts: Sequence[str], labels: Sequence[Union[str, int]]
    ) -> float:
        """Compute classification accuracy on given texts and labels."""
        if len(texts) != len(labels):
            raise ValueError(
                f"Number of texts ({len(texts)}) and labels ({len(labels)}) must match"
            )
        if not texts:
            return 0.0
        preds = self.predict(texts)
        correct = sum(1 for p, y in zip(preds, labels) if p == str(y))
        return correct / len(texts)

    def get_top_features(
        self,
        label: Union[str, int],
        n: int = 10,
        metric: str = "prob",
    ) -> List[Tuple[str, float]]:
        """Return top n features for a given class label.

        Args:
            label: Class label name.
            n: Number of top features to return.
            metric: 'prob' for smoothed conditional probability P(w|c),
                    or 'count' for raw token frequency in the class.
        """
        label_str = str(label)
        if label_str not in self.class_doc_counts:
            raise KeyError(f"Unknown class label: {label_str}")
        if metric not in ("prob", "count"):
            raise ValueError(f"Unknown metric '{metric}'. Choose 'prob' or 'count'.")

        if n <= 0 or not self.vocabulary:
            return []

        vocab_size = max(len(self.vocabulary), 1)
        total_tokens_c = self.class_token_counts[label_str]
        denominator = total_tokens_c + self.alpha * vocab_size
        cls_features = self.feature_counts[label_str]

        results: List[Tuple[str, float]] = []
        for token in self.vocabulary:
            cnt = cls_features.get(token, 0)
            if metric == "prob":
                score_val = (cnt + self.alpha) / denominator
            else:
                score_val = float(cnt)
            results.append((token, score_val))

        results.sort(key=lambda item: (-item[1], item[0]))
        return results[:n]

    def to_dict(self) -> Dict[str, Any]:
        """Export complete internal state to a JSON-serializable dictionary."""
        return {
            "version": 1,
            "alpha": self.alpha,
            "lowercase": self.lowercase,
            "token_pattern": self.token_pattern,
            "stopwords": sorted(self.stopwords) if self.stopwords is not None else None,
            "total_docs": self.total_docs,
            "class_doc_counts": dict(self.class_doc_counts),
            "class_token_counts": dict(self.class_token_counts),
            "feature_counts": {c: dict(feats) for c, feats in self.feature_counts.items()},
            "vocabulary": sorted(self.vocabulary),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "IncrementalNaiveBayes":
        """Restore a classifier instance from a state dictionary."""
        model = cls(
            alpha=data["alpha"],
            lowercase=data.get("lowercase", True),
            token_pattern=data.get("token_pattern", r"\b\w+\b"),
            stopwords=data.get("stopwords"),
        )
        model.total_docs = data["total_docs"]
        model.class_doc_counts = defaultdict(int, data["class_doc_counts"])
        model.class_token_counts = defaultdict(int, data["class_token_counts"])
        model.feature_counts = defaultdict(
            lambda: defaultdict(int),
            {c: defaultdict(int, feats) for c, feats in data["feature_counts"].items()},
        )
        model.vocabulary = set(data["vocabulary"])
        return model

    def to_json(self, indent: Optional[int] = None) -> str:
        """Export classifier state to a JSON string."""
        return json.dumps(self.to_dict(), indent=indent, sort_keys=True)

    @classmethod
    def from_json(cls, json_str: str) -> "IncrementalNaiveBayes":
        """Restore a classifier instance from a JSON string."""
        data = json.loads(json_str)
        return cls.from_dict(data)

    def save(self, target: Any) -> None:
        """Save classifier state to a file path or writable text stream."""
        payload = self.to_json()
        if hasattr(target, "write"):
            target.write(payload)
        else:
            with open(target, "w", encoding="utf-8") as f:
                f.write(payload)

    @classmethod
    def load(cls, source: Any) -> "IncrementalNaiveBayes":
        """Load classifier state from a file path or readable text stream."""
        if hasattr(source, "read"):
            payload = source.read()
        else:
            with open(source, "r", encoding="utf-8") as f:
                payload = f.read()
        return cls.from_json(payload)