# ZaxbyGraph handoff — push this to ZaxbyHub/zaxbygraph

**Date:** 2026-09-12  
**Author of this work:** Grok Build (xAI App Builder sandbox), acting for the maintainer of ZaxbyHub.  
**Status:** Implementation complete. Org-repo write failed. This document is for a follow-on agent with GitHub **Contents: Write** on `ZaxbyHub`.

If you can `git push` to https://github.com/ZaxbyHub/zaxbygraph, you are the intended reader. Do that. Do not rebuild the product.

- Product tree (complete): https://github.com/zaxbysauce/zaxbygraph
- Zip of that tree: https://github.com/zaxbysauce/zaxbygraph/archive/refs/heads/main.zip
- This file (raw): https://raw.githubusercontent.com/zaxbysauce/zaxbygraph/main/HANDOFF.md

---

## 0. Your job in one paragraph

The ZaxbyGraph v0.1 Python package (CLI + tests + Agent Skills) is already at https://github.com/zaxbysauce/zaxbygraph. Put that tree onto `ZaxbyHub/zaxbygraph`. Delete the placeholder `test.md` if it is still the only file there. Do **not** create the org. Do **not** create the repo. Do **not** dump the App Builder explorer into that GitHub repo unless the maintainer explicitly asks. Verify with `pip install -e . && python -m unittest discover -s tests` — expect **47 tests, OK**.

Fastest path, if you have org-transfer rights: delete or rename the empty org repo (name collision), then **transfer** the personal repo to `ZaxbyHub`.

---

## 1. Why Grok could not push to the org

| Attempt | Result |
|---|---|
| GET `ZaxbyHub/zaxbygraph` while private | 404 |
| Create repo under org `ZaxbyHub` | 403 — user correctly said do not create |
| After user made it public | GET succeeded; contents = `test.md` only |
| `push_files` on org repo | **403 Resource not accessible by integration** |
| Same write to `zaxbysauce/zaxbygraph` | **Succeeded** |
| Re-request GitHub connector with org write | `unavailable` |
| Create gist | 403 |

Cause: GitHub App installed on user `zaxbysauce`, not org `ZaxbyHub` (or org install lacks Contents: Write). Chat file cards in App Builder also failed to attach, which is why this file lives in the personal repo.

---

## 2. What to push

Python 3.11+ **stdlib-only** package `zaxbygraph` 0.1.0, Apache-2.0.

```
pyproject.toml
README.md LICENSE AGENTS.md .gitignore HANDOFF.md
.github/workflows/ci.yml
docs/frontier-audit-hook.md
skills/zaxbygraph/SKILL.md
skills/frontier-audit-enhance/   (SKILL.md, PASTE_PROMPT.md, references)
src/zaxbygraph/                  (cli, db, extract, github, paths, query, repo, schema.sql, store, sync, __main__.py)
tests/                           (FakeGitHubSource + 47 tests)
```

Do **not** include explorer/, node_modules, history.db, or a PAT.

---

## 3. How to push

### Path A — transfer (preferred)

1. Confirm https://github.com/zaxbysauce/zaxbygraph has `src/zaxbygraph/`, `tests/`, `skills/frontier-audit-enhance/`.
2. Delete or rename empty https://github.com/ZaxbyHub/zaxbygraph (test.md only as of 2026-09-12).
3. Personal repo: Settings → General → Danger zone → Transfer ownership → `ZaxbyHub`.
4. Confirm CI is green.
5. Optional: install the Grok/xAI GitHub App on org `ZaxbyHub` with Contents: Write.

### Path B — copy tree onto the empty org repo

```bash
git clone https://github.com/zaxbysauce/zaxbygraph.git /tmp/zg-src
git clone git@github.com:ZaxbyHub/zaxbygraph.git /tmp/zg-org
rsync -a --exclude .git /tmp/zg-src/ /tmp/zg-org/
cd /tmp/zg-org
git rm -f test.md || true
git add -A
git commit -m "Initial import: ZaxbyGraph v0.1 CLI, tests, and frontier-audit skill"
git push origin HEAD:main
```

---

## 4. Verification (mandatory)

```bash
pip install -e .
zaxbygraph --help
python -m unittest discover -s tests -v
```

Expect CLI: `sync status search item related churn open path sql export-graph`  
Expect `Ran 47 tests` / `OK`. No PAT in CI. No live GitHub in tests.

After a successful sync, agents must **not** page `gh api --paginate` of issues/PRs/comments into the lead.

---

## 5. Binding invariants (do not reverse)

- Edges `confidence='EXTRACTED'` only. No LLM, purpose, INFERRED, clustering in the fetcher.
- Node types in edges: `actor`, `item`, `label`, `file` only.
- Unique key `(repo, src_type, src_id, rel, dst_type, dst_id)` — evidence not in the key.
- Actor `commented`/`reviewed` collapse last-write-wins. History in tables.
- Mentions/closes from comments roll up to the owning item.
- On upsert, delete **owned** edges only. Never inbound mentions/closes from other items.
- `closes` then `mentions`, excluding numbers already closed. Same-repo `#N`/URL only.
- `closes` is keyword-in-body (`close[sd]?`, `fix(e[sd])?`, `resolve[sd]?`). Not GitHub connected-issue / timeline / commit-message close.
- Store `items.id` from the **issues list**. Never overwrite with GET `/pulls/{n}` id or `updated_at`.
- Watermark `issues_since` is list `updated_at`, verbatim inclusive. Do not subtract 1s.
- Each item is one `BEGIN IMMEDIATE` including the watermark bump.
- FTS5 external content (`content='items'`/`'comments'`). Delete triggers pass OLD values. No contentless FTS.
- `sql`: `PRAGMA query_only=ON`, first keyword SELECT/WITH/EXPLAIN only, no executescript.
- `--include-patches` off by default; backfill needs `--force`.
- `--jsonl [DIR]` writes `DIR/events.jsonl`. Resume may duplicate; key by `(resource, payload.id)`.
- Stdlib only. Auth is `gh`. No PAT stored.
- Package name `zaxbygraph` (not `ghgraph`). Schema via `importlib.resources`.
- Skip comments GET when comments==0; skip files GET when changed_files==0.
- FakeGitHubSource: `since`, `comment_on`, `fail_after`. Keep tests: PR keeps issue id, close-not-mention, mention-survival, FTS rebuild, unique-key collapse, sql bypass, 429 resume.
- Frontier-audit collectors gather only. Lead generates every candidate. Independent reviewers/critics. Integrity-only. Phase 1 Path A is zaxbygraph query, not gh pagination.
- Do not wrap github-to-sqlite.
- Do not merge explorer into the Python repo unless asked.
- Do not rewrite the product while pushing.

---

## 6. Suggested commit message

```
Initial import: ZaxbyGraph v0.1

Stdlib Python CLI for a local incremental GitHub issue/PR knowledge graph.
EXTRACTED edges only, gh auth, SQLite WAL + FTS5, 47 tests on FakeGitHubSource.
Includes zaxbygraph skill and frontier-audit-enhance (collectors gather, lead generates).
```

---

## 7. Next product work (only if the maintainer asks)

v0.1 is closed. Not started: timeline/commit-message auto-close, Graphify join on `touches`, cross-repo mentions, explorer jsonl load, org GitHub App install.

End of handoff.
