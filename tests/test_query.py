from __future__ import annotations

import sqlite3

from fixtures import REPO, TempDBTest, issue, pr_file, pull
from zaxbygraph.db import connect_readonly_query
from zaxbygraph.query import (
    assert_read_sql,
    churn,
    open_items,
    path_between,
    related,
    run_sql,
    search,
)


class QueryTests(TempDBTest):
    def seed_two_prs(self) -> None:
        self.src.add_pr(
            issue(10, title="wal store", body="adds wal", kind="pr", state="closed"),
            pull(10, changed_files=2, merged=True),
            files=[pr_file("src/store.py"), pr_file("src/db.py")],
        )
        self.src.add_pr(
            issue(11, title="fts rebuild", body="fixes fts", kind="pr", state="closed"),
            pull(11, changed_files=1, merged=True),
            files=[pr_file("src/store.py")],
        )
        self.src.add_issue(issue(12, title="open watermark", state="open", body="need inclusive since"))
        self.src.add_issue(issue(5, title="mentions twelve", body="see #12"))
        self.sync()

    def test_related_one_hop(self) -> None:
        self.seed_two_prs()
        data = related(self.conn, 10, depth=1, repo=REPO)
        rels = {e["rel"] for e in data["edges"]}
        self.assertIn("touches", rels)
        self.assertIn("authored", rels)
        files = [e["dst_id"] for e in data["edges"] if e["rel"] == "touches"]
        self.assertIn("src/store.py", files)

    def test_churn_groups_by_path(self) -> None:
        self.seed_two_prs()
        rows = churn(self.conn, repo=REPO)
        by_path = {r["path"]: r["prs"] for r in rows}
        self.assertEqual(by_path["src/store.py"], 2)
        self.assertEqual(by_path["src/db.py"], 1)

    def test_path_between_two_prs_sharing_file(self) -> None:
        self.seed_two_prs()
        data = path_between(self.conn, "10", "11", repo=REPO)
        self.assertIsNotNone(data["path"])
        ids = [step["id"] for step in data["path"]]
        self.assertEqual(ids[0], "10")
        self.assertEqual(ids[-1], "11")
        self.assertIn("src/store.py", ids)

    def test_open_filter(self) -> None:
        self.seed_two_prs()
        rows = open_items(self.conn, repo=REPO)
        numbers = {r["number"] for r in rows}
        self.assertIn(12, numbers)
        self.assertNotIn(10, numbers)

    def test_search_fts(self) -> None:
        self.seed_two_prs()
        data = search(self.conn, "watermark", repo=REPO)
        titles = [i["title"] for i in data["items"]]
        self.assertTrue(any("watermark" in t for t in titles))

    def test_sql_prefix_rejects_insert(self) -> None:
        with self.assertRaises(ValueError):
            assert_read_sql("INSERT INTO items VALUES (1)")

    def test_sql_rejects_pragma(self) -> None:
        with self.assertRaises(ValueError):
            assert_read_sql("PRAGMA journal_mode=DELETE")

    def test_sql_rejects_stacked_statements(self) -> None:
        with self.assertRaises(ValueError):
            assert_read_sql("SELECT 1; DELETE FROM items")

    def test_sql_with_insert_fails_query_only(self) -> None:
        self.seed_two_prs()
        assert_read_sql("WITH x AS (SELECT 1) INSERT INTO items(id, repo, number, kind, title, state, raw_json) VALUES (1,'r',1,'issue','t','open','{}')")
        qconn = connect_readonly_query(self.db_path)
        try:
            with self.assertRaises(ValueError):
                run_sql(
                    qconn,
                    "WITH x AS (SELECT 1) INSERT INTO items(id, repo, number, kind, title, state, raw_json) "
                    "VALUES (1,'r',1,'issue','t','open','{}')",
                )
        finally:
            qconn.close()

    def test_sql_select_works(self) -> None:
        self.seed_two_prs()
        qconn = connect_readonly_query(self.db_path)
        try:
            data = run_sql(qconn, "SELECT number FROM items ORDER BY number")
        finally:
            qconn.close()
        self.assertIn("number", data["columns"])
        self.assertTrue(data["rows"])
