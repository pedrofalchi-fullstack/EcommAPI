"""
state.py
Estado local em SQLite. Guarda, por SKU: o id no Bling, o último estoque
e o último preço que vimos. É o que permite o "diff" (mandar só o que mudou)
e o que evita estourar o limite diário do Bling.
"""

import os
import sqlite3
from pathlib import Path
from contextlib import contextmanager

DB_PATH = Path(os.getenv("SYNC_DB", "sync_state.db"))


def init_db() -> None:
    with _conn() as c:
        c.execute("""
            CREATE TABLE IF NOT EXISTS produtos (
                sku          TEXT PRIMARY KEY,
                bling_id     INTEGER,
                estoque      REAL,
                preco        REAL,
                ativo        INTEGER DEFAULT 1,
                atualizado   TEXT DEFAULT (datetime('now'))
            )
        """)


@contextmanager
def _conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def get_estado(sku: str) -> dict | None:
    with _conn() as c:
        row = c.execute("SELECT * FROM produtos WHERE sku = ?", (sku,)).fetchone()
        return dict(row) if row else None


def upsert_estado(sku: str, *, bling_id=None, estoque=None, preco=None, ativo=None) -> None:
    atual = get_estado(sku) or {}
    novo = {
        "bling_id": bling_id if bling_id is not None else atual.get("bling_id"),
        "estoque": estoque if estoque is not None else atual.get("estoque"),
        "preco": preco if preco is not None else atual.get("preco"),
        "ativo": ativo if ativo is not None else atual.get("ativo", 1),
    }
    with _conn() as c:
        c.execute("""
            INSERT INTO produtos (sku, bling_id, estoque, preco, ativo, atualizado)
            VALUES (?, ?, ?, ?, ?, datetime('now'))
            ON CONFLICT(sku) DO UPDATE SET
                bling_id=excluded.bling_id, estoque=excluded.estoque,
                preco=excluded.preco, ativo=excluded.ativo,
                atualizado=datetime('now')
        """, (sku, novo["bling_id"], novo["estoque"], novo["preco"], novo["ativo"]))
