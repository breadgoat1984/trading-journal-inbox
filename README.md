# trading-journal-inbox
Transit inbox for Sarantis's trading journal. Cloud scheduled tasks push docs here
(`<collection>/<doc_id>.json`, via `tools/ghdb.py`); a Windows job on his PC pulls every 5 minutes
and loads them into the local SQLite database, which is the canonical store.
`_seed/` is a read-only baseline snapshot (watch, setup, conids, tradable) as of 2026-11-27.
Never put secrets here.
