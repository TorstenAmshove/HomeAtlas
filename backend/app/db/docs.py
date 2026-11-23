"""Persistence for docs (see db/__init__ for the package rules)."""
from __future__ import annotations

from ._core import _conn, _new_id, _now, _row, _rows


# --------------------------------------------------------------------------------------------
# Documentation pages
# --------------------------------------------------------------------------------------------

def list_doc_pages() -> list[dict]:
    with _conn() as conn:
        return _rows(conn.execute("SELECT * FROM docPages ORDER BY sortOrder, title COLLATE NOCASE"))


def get_doc_page(slug: str) -> dict | None:
    with _conn() as conn:
        return _row(conn.execute("SELECT * FROM docPages WHERE slug = ?", (slug,)).fetchone())


_DOC_VERSION_KEEP = 50


def snapshot_doc_page(slug: str, reason: str) -> None:
    """Records the CURRENT content before it is replaced. Called by every writer -- a snapshot
    taken after the write would store the new text and lose exactly what it was meant to keep."""
    page = get_doc_page(slug)
    if page is None or not (page["bodyMd"].strip() or (page["manualMd"] or "").strip()):
        return
    with _conn() as conn:
        conn.execute(
            "INSERT INTO docPageVersions(id, slug, title, bodyMd, manualMd, generated, reason, createdAt) "
            "VALUES(?,?,?,?,?,?,?,?)",
            (_new_id(), slug, page["title"], page["bodyMd"], page["manualMd"] or "",
             page["generated"], reason, _now()),
        )
        # Unbounded history would grow by a full copy of every chapter on every scan.
        conn.execute(
            "DELETE FROM docPageVersions WHERE slug = ? AND id NOT IN "
            "(SELECT id FROM docPageVersions WHERE slug = ? ORDER BY createdAt DESC, rowid DESC LIMIT ?)",
            (slug, slug, _DOC_VERSION_KEEP),
        )


def list_doc_versions(slug: str) -> list[dict]:
    with _conn() as conn:
        return _rows(conn.execute(
            "SELECT id, slug, title, generated, reason, createdAt, length(bodyMd) AS size "
            "FROM docPageVersions WHERE slug = ? ORDER BY createdAt DESC, rowid DESC",
            (slug,),
        ))


def get_doc_version(version_id: str) -> dict | None:
    with _conn() as conn:
        return _row(conn.execute("SELECT * FROM docPageVersions WHERE id = ?", (version_id,)).fetchone())


def restore_doc_version(version_id: str) -> dict | None:
    """Restoring is itself a change, so the state being replaced is snapshotted first -- an
    accidental restore stays undoable. The page becomes `generated = 0`: a deliberately chosen old
    text must not be overwritten by the next automatic run.

    Only the chapter text is restored. The household's own notes keep their current content: they
    are independent of the text (see `set_doc_page_manual`) and have their own history, so a
    restore must not silently discard them. The snapshot above still contains both."""
    version = get_doc_version(version_id)
    if version is None:
        return None
    snapshot_doc_page(version["slug"], "vor Wiederherstellung")
    with _conn() as conn:
        conn.execute(
            "UPDATE docPages SET bodyMd = ?, generated = 0, updatedAt = ? WHERE slug = ?",
            (version["bodyMd"], _now(), version["slug"]),
        )
    return get_doc_page(version["slug"])


def set_doc_page_manual(slug: str, manual_md: str) -> dict | None:
    """Writes the household's own notes for a chapter.

    Deliberately does NOT touch `generated`: the notes and the auto-written body are independent.
    Someone should be able to add a permanent note to a chapter and still receive updated device
    tables on the next scan -- pinning the whole page for that would defeat the point.
    """
    snapshot_doc_page(slug, "vor Änderung der eigenen Notizen")
    with _conn() as conn:
        conn.execute("UPDATE docPages SET manualMd = ?, updatedAt = ? WHERE slug = ?",
                     (manual_md, _now(), slug))
    return get_doc_page(slug)


def upsert_doc_page(slug: str, topic: str, title: str, body_md: str, intro: str, sort_order: int, generated: bool = True) -> dict:
    """Regenerating documentation must not silently discard a page the user has rewritten -- a page
    with `generated = 0` keeps its body and only refreshes its title/intro metadata."""
    existing = get_doc_page(slug)
    now = _now()
    if existing is not None and existing["generated"] and existing["bodyMd"] != body_md:
        snapshot_doc_page(slug, "automatisch neu erzeugt")
    with _conn() as conn:
        if existing is None:
            conn.execute(
                "INSERT INTO docPages(id, slug, topic, title, bodyMd, intro, generated, sortOrder, updatedAt) "
                "VALUES(?,?,?,?,?,?,?,?,?)",
                (_new_id(), slug, topic, title, body_md, intro, 1 if generated else 0, sort_order, now),
            )
        elif existing["generated"]:
            conn.execute(
                "UPDATE docPages SET topic = ?, title = ?, bodyMd = ?, intro = ?, sortOrder = ?, updatedAt = ? WHERE slug = ?",
                (topic, title, body_md, intro, sort_order, now, slug),
            )
        else:
            conn.execute(
                "UPDATE docPages SET topic = ?, title = ?, sortOrder = ? WHERE slug = ?",
                (topic, title, sort_order, slug),
            )
    return get_doc_page(slug)  # type: ignore[return-value]


def set_doc_page_body(slug: str, body_md: str) -> dict | None:
    """A manual edit pins the page (`generated = 0`) so the next auto-generation leaves it alone."""
    snapshot_doc_page(slug, "vor manueller Bearbeitung")
    with _conn() as conn:
        conn.execute("UPDATE docPages SET bodyMd = ?, generated = 0, updatedAt = ? WHERE slug = ?", (body_md, _now(), slug))
    return get_doc_page(slug)


def reset_doc_page(slug: str) -> None:
    with _conn() as conn:
        conn.execute("UPDATE docPages SET generated = 1 WHERE slug = ?", (slug,))


def delete_doc_page(slug: str) -> None:
    with _conn() as conn:
        conn.execute("DELETE FROM docPages WHERE slug = ?", (slug,))


def delete_doc_versions(slug: str) -> None:
    with _conn() as conn:
        conn.execute("DELETE FROM docPageVersions WHERE slug = ?", (slug,))
