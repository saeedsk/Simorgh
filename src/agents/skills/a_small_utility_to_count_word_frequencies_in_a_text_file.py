"""Utility for counting word frequencies in text files."""

from collections import Counter
from pathlib import Path
import re
from typing import List, Optional, Set, Tuple, Union


def count_words(
    text: str,
    *,
    case_sensitive: bool = False,
    min_length: int = 1,
    stopwords: Optional[Set[str]] = None,
) -> Counter:
    """Count frequencies of words in a string.

    Args:
        text: The input text to analyze.
        case_sensitive: Whether to distinguish between uppercase and lowercase.
        min_length: Minimum word length to include in counts.
        stopwords: Optional set of words to exclude from counts.

    Returns:
        A Counter mapping words to their frequency counts.
    """
    if not case_sensitive:
        text = text.lower()
        if stopwords:
            stopwords = {w.lower() for w in stopwords}

    words = re.findall(r"\b[a-zA-Z0-9]+(?:'[a-zA-Z0-9]+)?\b", text)

    if stopwords:
        words = [w for w in words if len(w) >= min_length and w not in stopwords]
    elif min_length > 1:
        words = [w for w in words if len(w) >= min_length]

    return Counter(words)


def count_word_frequencies(
    file_path: Union[str, Path],
    *,
    case_sensitive: bool = False,
    min_length: int = 1,
    stopwords: Optional[Set[str]] = None,
    encoding: str = "utf-8",
) -> Counter:
    """Count word frequencies in a given text file.

    Args:
        file_path: Path to the text file.
        case_sensitive: Whether to distinguish between uppercase and lowercase.
        min_length: Minimum word length to include in counts.
        stopwords: Optional set of words to exclude from counts.
        encoding: File encoding (defaults to 'utf-8').

    Returns:
        A Counter mapping words to their frequency counts.
    """
    path = Path(file_path)
    if not path.is_file():
        raise FileNotFoundError(f"File not found: {file_path}")

    content = path.read_text(encoding=encoding, errors="replace")
    return count_words(
        content,
        case_sensitive=case_sensitive,
        min_length=min_length,
        stopwords=stopwords,
    )


def top_words(
    file_path: Union[str, Path],
    n: int = 10,
    *,
    case_sensitive: bool = False,
    min_length: int = 1,
    stopwords: Optional[Set[str]] = None,
    encoding: str = "utf-8",
) -> List[Tuple[str, int]]:
    """Return the n most frequent words in a text file.

    Args:
        file_path: Path to the text file.
        n: Number of most common words to return.
        case_sensitive: Whether to distinguish between uppercase and lowercase.
        min_length: Minimum word length to include in counts.
        stopwords: Optional set of words to exclude from counts.
        encoding: File encoding.

    Returns:
        A list of (word, count) tuples sorted by descending frequency.
    """
    counts = count_word_frequencies(
        file_path,
        case_sensitive=case_sensitive,
        min_length=min_length,
        stopwords=stopwords,
        encoding=encoding,
    )
    return counts.most_common(n)