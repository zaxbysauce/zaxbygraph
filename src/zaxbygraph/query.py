from __future__ import annotations

import re
import sqlite3
from collections import defaultdict, deque

_SQL_COMMENT_LINE = re.compile(r"--[^\n]*")
_SQL_COMMENT_BLOCK = re.compile(r"/\*.*?\*/", re.S)
_FIRST_KW = re.compile(r"\s*([A-Za-z]+)", re.I)


def fts_query(raw: str) -> str:
    """Quote each whitespace token so AND/OR/NEAR are literals."""
    tokens = [t for t in raw.split() if t]
    if not tokens:
        return '""'
    quoted: list[str] = []
    for tok in tokens:
        cleaned = tok.replace('"', " ")
        quoted.append(f'"{cleaned}"')
    return " ".join(quoted)


def _row_to_dict(row: sqlite3.Row) -> dict:
    return {k: row[k] for k in row.keys()}


def status(conn: sqlite3.Connection, repo: str | None = None) -> dict:
    if repo:
        state = conn.execute("SELECT * FROM sync_state WHERE repo = ?", (repo,)).fetchone()
        states = [] if state is None else [_row_to_dict(state)]
    else:
        states = [_row_to_dict(r) for r in conn.execute("SELECT * FROM sync_state").fetchall()]
    items = conn.execute(
        "SELECT repo, kind, state, COUNT(*) AS c FROM items "
        + ("WHERE repo = ?" if repo else "")
        + " GROUP BY repo, kind, state",
        (repo,) if repo else (),
    ).fetchall()
    return {
        "repos": states,
        "counts": [dict(r) for r in items],
    }


def search(conn: sqlite3.Connection, query: str, limit: int = 20, repo: str | None = None) -> dict:
    match = fts_query(query)
    sql = """
        SELECT items.repo, items.number, items.kind, items.title, items.state, items.author,
               items.updated_at, items.html_url,
               snippet(items_fts, 0, '«', '»', '…', 12) AS snippet
        FROM items_fts
        JOIN items ON items.id = items_fts.rowid
        WHERE items_fts MATCH ?
    """
    params: list[object] = [match]
    if repo:
        sql += " AND items.repo = ?"
        params.append(repo)
    sql += " ORDER BY items.updated_at DESC LIMIT ?"
    params.append(int(limit))
    rows = conn.execute(sql, params).fetchall()
    comment_sql = """
        SELECT comments.repo, comments.number, comments.kind, comments.author,
               snippet(comments_fts, 0, '«', '»', '…', 12) AS snippet
        FROM comments_fts
        JOIN comments ON comments.pk = comments_fts.rowid
        WHERE comments_fts MATCH ?
    """
    cparams: list[object] = [match]
    if repo:
        comment_sql += " AND comments.repo = ?"
        cparams.append(repo)
    comment_sql += " LIMIT ?"
    cparams.append(int(limit))
    comments = conn.execute(comment_sql, cparams).fetchall()
    return {
        "items": [_row_to_dict(r) for r in rows],
        "comments": [_row_to_dict(r) for r in comments],
    }


def item(conn: sqlite3.Connection, number: int, repo: str | None = None) -> dict | None:
    if repo:
        row = conn.execute(
            "SELECT * FROM items WHERE repo = ? AND number = ?", (repo, number)
        ).fetchone()
    else:
        row = conn.execute("SELECT * FROM items WHERE number = ?", (number,)).fetchone()
    if row is None:
        return None
    rec = _row_to_dict(row)
    rec.pop("raw_json", None)
    r = rec["repo"]
    n = rec["number"]
    rec["labels"] = [
        _row_to_dict(x)
        for x in conn.execute(
            "SELECT name, color FROM labels WHERE repo = ? AND number = ?", (r, n)
        ).fetchall()
    ]
    rec["comments"] = [
        _row_to_dict(x)
        for x in conn.execute(
            "SELECT pk, github_id, kind, author, created_at, body, html_url "
            "FROM comments WHERE repo = ? AND number = ? ORDER BY created_at",
            (r, n),
        ).fetchall()
    ]
    rec["reviews"] = [
        _row_to_dict(x)
        for x in conn.execute(
            "SELECT id, author, state, submitted_at, body, html_url "
            "FROM reviews WHERE repo = ? AND number = ? ORDER BY submitted_at",
            (r, n),
        ).fetchall()
    ]
    rec["files"] = [
        _row_to_dict(x)
        for x in conn.execute(
            "SELECT path, status, additions, deletions, changes "
            "FROM pr_files WHERE repo = ? AND number = ? ORDER BY path",
            (r, n),
        ).fetchall()
    ]
    rec["edges"] = [
        _row_to_dict(x)
        for x in conn.execute(
            "SELECT src_type, src_id, rel, dst_type, dst_id, confidence, evidence "
            "FROM edges WHERE repo = ? AND ("
            "(src_type = 'item' AND src_id = ?) OR (dst_type = 'item' AND dst_id = ?)"
            ")",
            (r, str(n), str(n)),
        ).fetchall()
    ]
    return rec


def related(conn: sqlite3.Connection, number: int, depth: int = 1, repo: str | None = None) -> dict:
    if repo is None:
        row = conn.execute("SELECT repo FROM items WHERE number = ?", (number,)).fetchone()
        if row is None:
            return {"number": number, "nodes": [], "edges": []}
        repo = row["repo"]
    seen_edges: list[dict] = []
    frontier = {str(number)}
    visited = set(frontier)
    for _ in range(max(1, depth)):
        nxt: set[str] = set()
        for nid in frontier:
            rows = conn.execute(
                "SELECT src_type, src_id, rel, dst_type, dst_id, confidence, evidence "
                "FROM edges WHERE repo = ? AND ("
                "(src_type = 'item' AND src_id = ?) OR (dst_type = 'item' AND dst_id = ?)"
                ")",
                (repo, nid, nid),
            ).fetchall()
            for row in rows:
                rec = _row_to_dict(row)
                seen_edges.append(rec)
                for typ, ident in ((rec["src_type"], rec["src_id"]), (rec["dst_type"], rec["dst_id"])):
                    if typ == "item" and ident not in visited:
                        nxt.add(ident)
                        visited.add(ident)
        frontier = nxt
    nodes = []
    for nid in visited:
        it = conn.execute(
            "SELECT number, kind, title, state FROM items WHERE repo = ? AND number = ?",
            (repo, int(nid)),
        ).fetchone()
        if it:
            nodes.append(_row_to_dict(it))
        else:
            nodes.append({"number": int(nid), "kind": None, "title": None, "state": None})
    return {"number": number, "repo": repo, "nodes": nodes, "edges": seen_edges}


def churn(conn: sqlite3.Connection, limit: int = 30, repo: str | None = None) -> list[dict]:
    sql = """
        SELECT path, COUNT(*) AS prs,
               SUM(additions) AS additions, SUM(deletions) AS deletions
        FROM pr_files
    """
    params: list[object] = []
    if repo:
        sql += " WHERE repo = ?"
        params.append(repo)
    sql += " GROUP BY path ORDER BY prs DESC, path ASC LIMIT ?"
    params.append(int(limit))
    return [_row_to_dict(r) for r in conn.execute(sql, params).fetchall()]


def open_items(conn: sqlite3.Connection, repo: str | None = None) -> list[dict]:
    sql = """
        SELECT repo, number, kind, title, author, updated_at, html_url
        FROM items WHERE state = 'open'
    """
    params: list[object] = []
    if repo:
        sql += " AND repo = ?"
        params.append(repo)
    sql += " ORDER BY updated_at DESC"
    return [_row_to_dict(r) for r in conn.execute(sql, params).fetchall()]


def path_between(conn: sqlite3.Connection, a: str, b: str, repo: str | None = None) -> dict:
    """Undirected BFS over item\u2194item and item\u2194file edges."""
    if repo is None:
        row = conn.execute("SELECT repo FROM items LIMIT 1").fetchone()
        if row is None:
            return {"a": a, "b": b, "path": None, "reason": "empty graph"}
        repo = row["repo"]

    def node_key(kind: str, ident: str) -> str:
        return f"{kind}:{ident}"

    def parse_endpoint(value: str) -> tuple[str, str]:
        if value.isdigit():
            return "item", value
        return "file", value

    start_t, start_id = parse_endpoint(a)
    goal_t, goal_id = parse_endpoint(b)
    start = node_key(start_t, start_id)
    goal = node_key(goal_t, goal_id)

    STRUCTURAL = {"touches", "closes", "mentions"}
    adj: dict[str, list[tuple[str, str]]] = defaultdict(list)
    rows = conn.execute(
        "SELECT src_type, src_id, rel, dst_type, dst_id FROM edges WHERE repo = ?",
        (repo,),
    ).fetchall()
    for row in rows:
        if row["rel"] not in STRUCTURAL:
            continue
        src = node_key(row["src_type"], row["src_id"])
        dst = node_key(row["dst_type"], row["dst_id"])
        adj[src].append((dst, row["rel"]))
        adj[dst].append((src, row["rel"]))

    if start == goal:
        return {"a": a, "b": b, "repo": repo, "path": [{"type": start_t, "id": start_id}]}

    prev: dict[str, tuple[str, str] | None] = {start: None}
    q: deque[str] = deque([start])
    found = False
    while q:
        cur = q.popleft()
        if cur == goal:
            found = True
            break
        for nxt, rel in adj.get(cur, []):
            if nxt not in prev:
                prev[nxt] = (cur, rel)
                q.append(nxt)
    if not found:
        return {"a": a, "b": b, "repo": repo, "path": None}

    chain: list[dict] = []
    cur = goal
    while cur is not None:
        typ, ident = cur.split(":", 1)
        chain.append({"type": typ, "id": ident})
        step = prev[cur]
        if step is None:
            break
        cur = step[0]
    chain.reverse()
    return {"a": a, "b": b, "repo": repo, "path": chain}


def _strip_sql_comments(sql: str) -> str:
    sql = _SQL_COMMENT_BLOCK.sub(" ", sql)
    sql = _SQL_COMMENT_LINE.sub(" ", sql)
    return sql


def assert_read_sql(sql: str) -> None:
    stripped = _strip_sql_comments(sql).strip()
    if not stripped:
        raise ValueError("empty SQL")
    if ";" in stripped.rstrip(";"):
        raise ValueError("multiple statements are not allowed")
    match = _FIRST_KW.match(stripped)
    if match is None:
        raise ValueError("SQL must start with SELECT, WITH, or EXPLAIN")
    kw = match.group(1).upper()
    if kw not in {"SELECT", "WITH", "EXPLAIN"}:
        raise ValueError("SQL must start with SELECT, WITH, or EXPLAIN")


def run_sql(conn: sqlite3.Connection, sql: str, limit: int = 200) -> dict:
    assert_read_sql(sql)
    cur = conn.cursor()
    try:
        cur.execute(sql)
    except sqlite3.Error as exc:
        raise ValueError(str(exc)) from exc
    if cur.description is None:
        return {"columns": [], "rows": []}
    cols = [d[0] for d in cur.description]
    rows = []
    for i, row in enumerate(cur.fetchall()):
        if i >= limit:
            break
        rows.append([row[c] if isinstance(row, sqlite3.Row) else row[idx] for idx, c in enumerate(cols)])
    return {"columns": cols, "rows": rows}


def export_graph(conn: sqlite3.Connection, repo: str | None = None) -> dict:
    item_rows = conn.execute(
        "SELECT repo, number, kind, title, state FROM items" + (" WHERE repo = ?" if repo else ""),
        (repo,) if repo else (),
    ).fetchall()
    nodes: list[dict] = []
    seen: set[str] = set()
    for row in item_rows:
        nid = f"item:{row['number']}"
        nodes.append(
            {
                "id": nid,
                "type": "item",
                "label": f"#{row['number']} {row['title']}",
                "kind": row["kind"],
                "state": row["state"],
            }
        )
        seen.add(nid)
    edge_rows = conn.execute(
        "SELECT src_type, src_id, rel, dst_type, dst_id, confidence FROM edges"
        + (" WHERE repo = ?" if repo else ""),
        (repo,) if repo else (),
    ).fetchall()
    edges = []
    for row in edge_rows:
        src = f"{row['src_type']}:{row['src_id']}"
        dst = f"{row['dst_type']}:{row['dst_id']}"
        if src not in seen:
            nodes.append({"id": src, "type": row["src_type"], "label": row["src_id"]})
            seen.add(src)
        if dst not in seen:
            nodes.append({"id": dst, "type": row["dst_type"], "label": row["dst_id"]})
            seen.add(dst)
        edges.append(
            {
                "source": src,
                "target": dst,
                "rel": row["rel"],
                "confidence": row["confidence"],
            }
        )
    return {"nodes": nodes, "edges": edges}
