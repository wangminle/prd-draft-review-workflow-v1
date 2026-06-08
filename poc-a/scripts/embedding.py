"""POC-A 向量嵌入接口 — 所有向量库 POC 共用。

嵌入模型选择：
- 方案 A: OpenAI text-embedding-3-small（需要 API Key）
- 方案 B: 本地 BGE-M3 或 Sentence-Transformer（需要本地推理）
- 方案 C: 使用简单的 TF-IDF 向量作为 fallback（不需要额外依赖）

POC-A 先用方案 C (TF-IDF) 作为 baseline，然后尝试方案 A/B 如果可用。
这样即使没有嵌入模型 API，也能验证向量库的索引和查询能力。
"""

import math
import hashlib
import json
from pathlib import Path
from collections import Counter

from chunking import Chunk, build_chunk_index


def _simple_tokenize(text: str) -> list[str]:
    """简单中文分词：按字符 + 2-gram。"""
    # 去除标点，保留中文和英文
    cleaned = ""
    for ch in text:
        if ch.isalnum() or ch == ' ':
            cleaned += ch
        else:
            cleaned += ' '

    tokens = cleaned.split()

    # 2-gram（中文连续两字）
    chinese_chars = [ch for ch in text if '一' <= ch <= '鿿']
    bigrams = [chinese_chars[i] + chinese_chars[i+1]
               for i in range(len(chinese_chars) - 1)]

    return tokens + bigrams


def compute_tfidf_vectors(chunks: list[Chunk]) -> tuple[list[list[float]], dict]:
    """计算 TF-IDF 向量作为 fallback 嵌入。"""
    # 词汇表
    all_tokens = []
    doc_freqs = Counter()

    for chunk in chunks:
        tokens = _simple_tokenize(chunk.text)
        all_tokens.append(tokens)
        unique_tokens = set(tokens)
        for t in unique_tokens:
            doc_freqs[t] += 1

    # 词汇表映射
    vocab = sorted(doc_freqs.keys())
    vocab_map = {t: i for i, t in enumerate(vocab)}
    n_docs = len(chunks)
    vocab_size = len(vocab)

    # 计算 TF-IDF
    vectors = []
    for tokens in all_tokens:
        tf = Counter(tokens)
        vec = [0.0] * vocab_size
        for token, count in tf.items():
            if token in vocab_map:
                idx = vocab_map[token]
                tf_val = count / len(tokens) if tokens else 0
                idf_val = math.log(n_docs / (doc_freqs[token] + 1)) + 1
                vec[idx] = tf_val * idf_val
        # 归一化
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        vec = [v / norm for v in vec]
        vectors.append(vec)

    metadata = {
        "method": "tfidf_fallback",
        "vocab_size": vocab_size,
        "n_docs": n_docs,
    }

    return vectors, metadata


def compute_vectors_with_api(chunks: list[Chunk], model: str = "text-embedding-3-small",
                             api_key: str = None) -> tuple[list[list[float]], dict]:
    """使用 OpenAI API 计算嵌入向量。"""
    import os

    api_key = api_key or os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("需要 OPENAI_API_KEY 环境变量")

    # 动态导入，不强制依赖
    try:
        import openai
    except ImportError:
        raise ImportError("需要 openai 包: pip install openai")

    client = openai.OpenAI(api_key=api_key)

    texts = [chunk.text for chunk in chunks]
    vectors = []
    batch_size = 100

    for i in range(0, len(texts), batch_size):
        batch = texts[i:i+batch_size]
        response = client.embeddings.create(model=model, input=batch)
        for item in response.data:
            vectors.append(item.embedding)

    metadata = {
        "method": f"openai_{model}",
        "embedding_dim": len(vectors[0]) if vectors else 0,
        "n_docs": len(chunks),
    }

    return vectors, metadata


def compute_vectors(chunks: list[Chunk], method: str = "tfidf") -> tuple[list[list[float]], dict]:
    """根据 method 选择嵌入方式。"""
    if method == "tfidf":
        return compute_tfidf_vectors(chunks)
    elif method == "openai":
        return compute_vectors_with_api(chunks)
    else:
        raise ValueError(f"未知的嵌入方法: {method}")


if __name__ == "__main__":
    chunks = build_chunk_index()
    print(f"Chunks: {len(chunks)}")

    vectors, meta = compute_vectors(chunks, method="tfidf")
    print(f"Method: {meta['method']}, vocab_size: {meta['vocab_size']}, dim: {len(vectors[0])}")