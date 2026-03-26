"""Memory management for the AEGIS system -- short-term and long-term MD files."""
import logging
import math
import re
from collections import Counter
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


def get_memory_dir(aegis_path: str) -> Path:
    """Return the memory root directory for the AEGIS project."""
    p = Path(aegis_path) / "memory"
    p.mkdir(parents=True, exist_ok=True)
    return p


def get_short_term_dir(aegis_path: str) -> Path:
    d = get_memory_dir(aegis_path) / "short-term"
    d.mkdir(parents=True, exist_ok=True)
    return d


def get_long_term_dir(aegis_path: str) -> Path:
    d = get_memory_dir(aegis_path) / "long-term"
    d.mkdir(parents=True, exist_ok=True)
    return d


def write_short_term_memory(aegis_path: str, content: str, timestamp: datetime = None) -> Path:
    """
    Write a short-term memory file.
    Filename format: YYYY-MM-DD-HHmm.md
    Returns the path of the written file.
    """
    if timestamp is None:
        timestamp = datetime.now(timezone.utc)
    filename = timestamp.strftime("%Y-%m-%d-%H%M") + ".md"
    fpath = get_short_term_dir(aegis_path) / filename

    frontmatter = f"""---
timestamp: "{timestamp.isoformat()}"
period: "{(timestamp - timedelta(hours=4)).strftime('%Y-%m-%d %H:%M')} ~ {timestamp.strftime('%Y-%m-%d %H:%M')}"
---

"""
    fpath.write_text(frontmatter + content, encoding="utf-8")
    logger.info(f"Short-term memory written: {fpath}")
    return fpath


def write_long_term_memory(aegis_path: str, content: str, filename: str) -> Path:
    """
    Write or update a long-term memory file.
    If the file exists, it will be overwritten (AI provides the full updated content).
    """
    if not filename.endswith(".md"):
        filename += ".md"
    fpath = get_long_term_dir(aegis_path) / filename

    frontmatter = f"""---
topic: "{filename.replace('.md', '')}"
updated_at: "{datetime.now(timezone.utc).isoformat()}"
---

"""
    fpath.write_text(frontmatter + content, encoding="utf-8")
    logger.info(f"Long-term memory written: {fpath}")
    return fpath


def read_short_term_memories(aegis_path: str, days: int = 7) -> str:
    """
    Read all short-term memories from the last N days.
    Returns concatenated content as a single string.
    """
    d = get_short_term_dir(aegis_path)
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    entries = []

    for f in sorted(d.glob("*.md")):
        try:
            # Parse date from filename: YYYY-MM-DD-HHmm.md
            date_str = f.stem  # e.g., "2026-03-07-0800"
            file_date = datetime.strptime(date_str, "%Y-%m-%d-%H%M").replace(tzinfo=timezone.utc)
            if file_date >= cutoff:
                entries.append(f"### {date_str}\n\n{f.read_text(encoding='utf-8')}")
        except (ValueError, OSError) as e:
            logger.warning(f"Skipping {f}: {e}")

    return "\n\n---\n\n".join(entries) if entries else "(no recent short-term memories)"


def read_long_term_memories(aegis_path: str) -> str:
    """
    Read all long-term memory files.
    Returns concatenated content as a single string.
    """
    d = get_long_term_dir(aegis_path)
    entries = []

    for f in sorted(d.glob("*.md")):
        try:
            entries.append(f"### {f.stem}\n\n{f.read_text(encoding='utf-8')}")
        except OSError as e:
            logger.warning(f"Skipping {f}: {e}")

    return "\n\n---\n\n".join(entries) if entries else "(no long-term memories yet)"


def parse_memory_output(ai_output: str) -> dict:
    """
    Parse AI output from the memory consolidation cron job.

    Expected format:
    ---SHORT_TERM---
    (short-term content)
    ---LONG_TERM---
    (long-term content, or "no update needed")
    ---LONG_TERM_FILE---
    (filename like recurring-issues.md)

    Returns dict with keys: short_term, long_term, long_term_file
    """
    result = {"short_term": "", "long_term": "", "long_term_file": ""}

    if "---SHORT_TERM---" in ai_output:
        parts = ai_output.split("---SHORT_TERM---", 1)
        remainder = parts[1] if len(parts) > 1 else ""

        if "---LONG_TERM---" in remainder:
            st_part, lt_remainder = remainder.split("---LONG_TERM---", 1)
            result["short_term"] = st_part.strip()

            if "---LONG_TERM_FILE---" in lt_remainder:
                lt_part, file_part = lt_remainder.split("---LONG_TERM_FILE---", 1)
                result["long_term"] = lt_part.strip()
                result["long_term_file"] = file_part.strip()
            else:
                result["long_term"] = lt_remainder.strip()
        else:
            result["short_term"] = remainder.strip()
    else:
        # If no delimiters, treat entire output as short-term
        result["short_term"] = ai_output.strip()

    return result


def process_memory_output(aegis_path: str, ai_output: str) -> dict:
    """
    Parse AI memory output and write to appropriate files.
    Returns dict with paths of written files.
    """
    parsed = parse_memory_output(ai_output)
    written = {}

    if parsed["short_term"]:
        path = write_short_term_memory(aegis_path, parsed["short_term"])
        written["short_term"] = str(path)

    lt = parsed["long_term"].lower()
    if parsed["long_term"] and "no update" not in lt and "no need" not in lt:
        filename = parsed["long_term_file"] or "general-observations.md"
        path = write_long_term_memory(aegis_path, parsed["long_term"], filename)
        written["long_term"] = str(path)

    return written


def cleanup_short_term(aegis_path: str, retention_days: int = 30) -> int:
    """
    Delete short-term memory files older than retention_days.
    Returns number of files deleted.
    """
    d = get_short_term_dir(aegis_path)
    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
    deleted = 0

    for f in d.glob("*.md"):
        try:
            date_str = f.stem
            file_date = datetime.strptime(date_str, "%Y-%m-%d-%H%M").replace(tzinfo=timezone.utc)
            if file_date < cutoff:
                f.unlink()
                deleted += 1
                logger.info(f"Deleted old short-term memory: {f}")
        except (ValueError, OSError) as e:
            logger.warning(f"Skipping cleanup of {f}: {e}")

    return deleted


# ── 背景 Embedding 寫入 ──

def _background_embed(entity_type: str, entity_key: str, content: str, member_slug: str):
    """在背景執行 embed_and_store，不阻塞主流程。"""
    import asyncio
    import threading

    async def _run():
        try:
            from app.core.embedding import embed_and_store
            await embed_and_store(entity_type, entity_key, content, member_slug)
        except Exception as e:
            logger.warning(f"[background_embed] {e}")

    def _thread():
        asyncio.run(_run())

    threading.Thread(target=_thread, daemon=True).start()


# ── Member-level memory (delegates to member_profile for paths) ──

def _get_member_short_term_dir(member_slug: str) -> Path:
    from app.core.member_profile import get_member_memory_dir
    d = get_member_memory_dir(member_slug) / "short-term"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _get_member_long_term_dir(member_slug: str) -> Path:
    from app.core.member_profile import get_member_memory_dir
    d = get_member_memory_dir(member_slug) / "long-term"
    d.mkdir(parents=True, exist_ok=True)
    return d


def write_member_short_term_memory(member_slug: str, content: str, timestamp: datetime = None, category: str = None) -> Path:
    """Write a short-term memory file for a specific member."""
    if timestamp is None:
        timestamp = datetime.now(timezone.utc)
    filename = timestamp.strftime("%Y-%m-%d-%H%M%S") + ".md"
    fpath = _get_member_short_term_dir(member_slug) / filename

    cat_line = f'\ncategory: "{category}"' if category else ""
    frontmatter = f"""---
timestamp: "{timestamp.isoformat()}"
member: "{member_slug}"{cat_line}
---

"""
    fpath.write_text(frontmatter + content, encoding="utf-8")
    logger.info(f"Member short-term memory written: {fpath}")
    _background_embed("memory", str(fpath), content, member_slug)
    return fpath


def read_member_short_term_memories(member_slug: str, days: int = 7) -> str:
    """Read all short-term memories for a member from the last N days."""
    d = _get_member_short_term_dir(member_slug)
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    entries = []

    for f in sorted(d.glob("*.md")):
        try:
            date_str = f.stem
            # 支援秒級 (%H%M%S) 與分鐘級 (%H%M) 兩種格式
            for fmt in ("%Y-%m-%d-%H%M%S", "%Y-%m-%d-%H%M"):
                try:
                    file_date = datetime.strptime(date_str, fmt).replace(tzinfo=timezone.utc)
                    break
                except ValueError:
                    continue
            else:
                continue
            if file_date >= cutoff:
                entries.append(f"### {date_str}\n\n{f.read_text(encoding='utf-8')}")
        except OSError as e:
            logger.warning(f"Skipping {f}: {e}")

    return "\n\n---\n\n".join(entries) if entries else "(no recent short-term memories)"


def cleanup_member_short_term(member_slug: str, retention_days: int = 30) -> int:
    """Delete member short-term memory files older than retention_days."""
    d = _get_member_short_term_dir(member_slug)
    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
    deleted = 0

    for f in d.glob("*.md"):
        try:
            date_str = f.stem
            for fmt in ("%Y-%m-%d-%H%M%S", "%Y-%m-%d-%H%M"):
                try:
                    file_date = datetime.strptime(date_str, fmt).replace(tzinfo=timezone.utc)
                    break
                except ValueError:
                    continue
            else:
                continue
            if file_date < cutoff:
                f.unlink()
                deleted += 1
        except OSError:
            pass

    return deleted


# ── 結構化 CRUD 操作 ──

def _parse_frontmatter(text: str) -> dict:
    """解析 Markdown frontmatter，回傳 key-value dict。"""
    meta: dict = {}
    if not text.startswith("---"):
        return meta
    end = text.find("---", 3)
    if end == -1:
        return meta
    for line in text[3:end].strip().splitlines():
        if ":" not in line:
            continue
        key, _, val = line.partition(":")
        meta[key.strip()] = val.strip().strip('"')
    return meta


def list_member_memories(member_slug: str, memory_type: str = "all") -> list[dict]:
    """列出成員的記憶檔案（含 frontmatter 解析）。

    memory_type: "short-term", "long-term", "all"
    """
    results: list[dict] = []
    dirs: list[tuple[str, Path]] = []
    if memory_type in ("short-term", "all"):
        dirs.append(("short-term", _get_member_short_term_dir(member_slug)))
    if memory_type in ("long-term", "all"):
        dirs.append(("long-term", _get_member_long_term_dir(member_slug)))

    for mtype, d in dirs:
        for f in sorted(d.glob("*.md")):
            try:
                text = f.read_text(encoding="utf-8")
            except OSError:
                continue
            meta = _parse_frontmatter(text)
            # 取得 body（frontmatter 之後）
            body = text
            if text.startswith("---"):
                end = text.find("---", 3)
                if end != -1:
                    body = text[end + 3:].strip()
            results.append({
                "filename": f.name,
                "type": mtype,
                "topic": meta.get("topic", ""),
                "timestamp": meta.get("timestamp", ""),
                "category": meta.get("category", ""),
                "snippet": body[:150],
            })
    return results


def delete_member_memory(member_slug: str, filename: str) -> bool:
    """刪除指定的成員記憶檔案（支援 short-term 和 long-term）。"""
    if not filename or ".." in filename or "/" in filename or "\\" in filename:
        return False
    for d in (_get_member_short_term_dir(member_slug), _get_member_long_term_dir(member_slug)):
        fpath = d / filename
        if fpath.exists():
            fpath.unlink()
            logger.info(f"Deleted member memory: {fpath}")
            return True
    return False


def update_member_long_term_memory(member_slug: str, filename: str, content: str, category: str = None) -> Path:
    """更新指定長期記憶的內容，保留或更新 frontmatter。"""
    if not filename.endswith(".md"):
        filename += ".md"
    fpath = _get_member_long_term_dir(member_slug) / filename

    # 讀取既有 frontmatter
    old_meta: dict = {}
    if fpath.exists():
        try:
            old_meta = _parse_frontmatter(fpath.read_text(encoding="utf-8"))
        except OSError:
            pass

    topic = old_meta.get("topic", filename.replace(".md", ""))
    cat_line = f'\ncategory: "{category}"' if category else (
        f'\ncategory: "{old_meta["category"]}"' if old_meta.get("category") else ""
    )
    frontmatter = f"""---
topic: "{topic}"
updated_at: "{datetime.now(timezone.utc).isoformat()}"{cat_line}
---

"""
    fpath.write_text(frontmatter + content, encoding="utf-8")
    logger.info(f"Updated member long-term memory: {fpath}")
    _background_embed("memory", str(fpath), content, member_slug)
    return fpath


# ── MMR 重排序輔助函式 ──

def _jaccard_similarity(tokens_a: list[str], tokens_b: list[str]) -> float:
    """計算兩組 token 集合的 Jaccard 相似度（0~1）。"""
    set_a = set(tokens_a)
    set_b = set(tokens_b)
    if not set_a and not set_b:
        return 1.0
    intersection = len(set_a & set_b)
    union = len(set_a | set_b)
    return intersection / union if union else 0.0


def _mmr_rerank(
    candidates: list[dict],
    query_tokens: list[str],
    top_k: int,
    lambda_param: float = 0.5,
) -> list[dict]:
    """
    MMR（Maximal Marginal Relevance）重排序。

    每次迭代從候選中選出 lambda*relevance - (1-lambda)*max_similarity 最高的文件，
    兼顧相關性與多樣性。

    candidates 每筆需含 tokens（list[str]）與 score（float，BM25+decay 分數）。
    """
    if not candidates:
        return []

    # 正規化分數（最高分為 1）
    max_score = max(c["score"] for c in candidates)
    if max_score <= 0:
        return candidates[:top_k]

    selected: list[dict] = []
    remaining = list(candidates)

    for _ in range(min(top_k, len(candidates))):
        best_idx = -1
        best_mmr = float("-inf")

        for i, cand in enumerate(remaining):
            relevance = cand["score"] / max_score

            # 計算與已選文件的最大相似度
            max_sim = 0.0
            for sel in selected:
                sim = _jaccard_similarity(cand["tokens"], sel["tokens"])
                if sim > max_sim:
                    max_sim = sim

            mmr = lambda_param * relevance - (1 - lambda_param) * max_sim

            if mmr > best_mmr:
                best_mmr = mmr
                best_idx = i

        selected.append(remaining.pop(best_idx))

    return selected


# ── BM25 + 時間衰減記憶搜尋 ──

def _tokenize(text: str) -> list[str]:
    """將文字拆分為小寫 token（支援中英文混合）。"""
    return re.findall(r"[a-zA-Z0-9]+|[\u4e00-\u9fff]", text.lower())


def _parse_file_date(path: Path) -> Optional[datetime]:
    """從檔名解析日期，支援秒級與分鐘級格式。"""
    for fmt in ("%Y-%m-%d-%H%M%S", "%Y-%m-%d-%H%M"):
        try:
            return datetime.strptime(path.stem, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def search_member_memories(
    member_slug: str,
    query: str,
    top_k: int = 5,
    diversity: float = 0.5,
    mode: str = "bm25",
) -> list[dict]:
    """
    搜尋成員記憶，支援三種模式：

    - mode="bm25"：BM25 評分 + 時間衰減 + MMR 多樣性重排（預設）
    - mode="vector"：語義向量搜尋（需 OpenAI API Key）
    - mode="hybrid"：兩者都跑，用 RRF 合併排名

    回傳 top_k 筆結果，每筆包含 file, score, snippet。
    """
    if mode == "vector":
        return _search_vector(member_slug, query, top_k)
    if mode == "hybrid":
        return _search_hybrid(member_slug, query, top_k, diversity)
    query_tokens = _tokenize(query)
    if not query_tokens:
        return []

    # 收集所有記憶檔案
    st_dir = _get_member_short_term_dir(member_slug)
    lt_dir = _get_member_long_term_dir(member_slug)

    docs: list[dict] = []
    for d in (st_dir, lt_dir):
        for f in d.glob("*.md"):
            try:
                content = f.read_text(encoding="utf-8")
            except OSError:
                continue
            tokens = _tokenize(content)
            if not tokens:
                continue
            file_date = _parse_file_date(f) or datetime.fromtimestamp(
                f.stat().st_mtime, tz=timezone.utc
            )
            docs.append({
                "path": f,
                "content": content,
                "tokens": tokens,
                "tf": Counter(tokens),
                "date": file_date,
            })

    if not docs:
        return []

    # BM25 參數
    k1 = 1.5
    b = 0.75
    n = len(docs)
    avgdl = sum(len(d["tokens"]) for d in docs) / n

    # 計算每個 query token 的 DF（出現在幾篇文件中）
    df: dict[str, int] = Counter()
    for d in docs:
        unique = set(d["tokens"])
        for t in query_tokens:
            if t in unique:
                df[t] += 1

    now = datetime.now(timezone.utc)
    half_life_days = 7.0
    results: list[dict] = []

    for d in docs:
        dl = len(d["tokens"])
        score = 0.0
        for t in query_tokens:
            if t not in d["tf"]:
                continue
            tf_val = d["tf"][t]
            # IDF: log((N - n_t + 0.5) / (n_t + 0.5) + 1)
            n_t = df.get(t, 0)
            idf = math.log((n - n_t + 0.5) / (n_t + 0.5) + 1)
            # BM25 TF 正規化
            tf_norm = (tf_val * (k1 + 1)) / (tf_val + k1 * (1 - b + b * dl / avgdl))
            score += idf * tf_norm

        if score <= 0:
            continue

        # 時間衰減：score * 0.5^(days/7)
        days_ago = max((now - d["date"]).total_seconds() / 86400, 0)
        decay = 0.5 ** (days_ago / half_life_days)
        final_score = score * decay

        # snippet：取前 150 字元（去除 frontmatter）
        raw = d["content"]
        if raw.startswith("---"):
            end = raw.find("---", 3)
            if end != -1:
                raw = raw[end + 3:]
        snippet = raw.strip()[:150]

        results.append({
            "file": str(d["path"]),
            "score": round(final_score, 4),
            "snippet": snippet,
        })

    results.sort(key=lambda r: r["score"], reverse=True)

    # MMR 重排序：diversity > 0 時啟用
    if diversity > 0 and len(results) > 1:
        # 建立候選清單（含 tokens 供 MMR 計算相似度）
        doc_map = {str(d["path"]): d for d in docs}
        mmr_candidates = []
        for r in results[:top_k * 3]:
            doc = doc_map.get(r["file"])
            if doc:
                mmr_candidates.append({
                    "file": r["file"],
                    "score": r["score"],
                    "snippet": r["snippet"],
                    "tokens": doc["tokens"],
                })

        reranked = _mmr_rerank(mmr_candidates, query_tokens, top_k, lambda_param=1 - diversity)
        return [{"file": r["file"], "score": r["score"], "snippet": r["snippet"]} for r in reranked]

    return results[:top_k]


# ── 向量搜尋輔助函式 ──

def _search_vector(member_slug: str, query: str, top_k: int) -> list[dict]:
    """純向量語義搜尋。"""
    import asyncio
    from app.core.embedding import get_embedding, search_similar

    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                query_vec = pool.submit(
                    asyncio.run, get_embedding(query)
                ).result(timeout=15)
        else:
            query_vec = loop.run_until_complete(get_embedding(query))
    except Exception:
        query_vec = asyncio.run(get_embedding(query))

    if not query_vec:
        return []

    results = search_similar(query_vec, member_slug, top_k=top_k)
    # 補上 snippet（從檔案讀取）
    for r in results:
        r["file"] = r.pop("entity_key", "")
        try:
            text = Path(r["file"]).read_text(encoding="utf-8")
            if text.startswith("---"):
                end = text.find("---", 3)
                if end != -1:
                    text = text[end + 3:]
            r["snippet"] = text.strip()[:150]
        except OSError:
            r["snippet"] = ""
    return results


def _search_hybrid(member_slug: str, query: str, top_k: int, diversity: float) -> list[dict]:
    """混合搜尋：BM25 + Vector，用 Reciprocal Rank Fusion 合併。"""
    bm25_results = search_member_memories(member_slug, query, top_k=top_k * 2, diversity=diversity, mode="bm25")
    vector_results = _search_vector(member_slug, query, top_k=top_k * 2)

    # RRF 合併（k=60）
    k = 60
    rrf_scores: dict[str, float] = {}
    snippets: dict[str, str] = {}

    for rank, r in enumerate(bm25_results):
        key = r["file"]
        rrf_scores[key] = rrf_scores.get(key, 0) + 1.0 / (k + rank + 1)
        snippets[key] = r.get("snippet", "")

    for rank, r in enumerate(vector_results):
        key = r["file"]
        rrf_scores[key] = rrf_scores.get(key, 0) + 1.0 / (k + rank + 1)
        if key not in snippets:
            snippets[key] = r.get("snippet", "")

    merged = [
        {"file": key, "score": round(score, 4), "snippet": snippets.get(key, "")}
        for key, score in rrf_scores.items()
    ]
    merged.sort(key=lambda r: r["score"], reverse=True)
    return merged[:top_k]
