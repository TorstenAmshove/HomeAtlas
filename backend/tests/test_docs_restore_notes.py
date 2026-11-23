from app import db


def _setup():
    db.upsert_doc_page("notfall", "t", "T", "alt\n", "i", 1)
    db.set_doc_page_body("notfall", "neu")
    return db.list_doc_versions("notfall")


def test_restore_keeps_current_notes(temp_db):
    db.set_doc_page_manual("notfall", "Notiz alt")
    versions = _setup()
    old = next(v for v in versions if v["reason"] == "vor manueller Bearbeitung")
    db.set_doc_page_manual("notfall", "Notiz aktuell")
    page = db.restore_doc_version(old["id"])
    assert page["bodyMd"] == "alt\n" and page["generated"] == 0
    assert page["manualMd"] == "Notiz aktuell"
    snap = next(v for v in db.list_doc_versions("notfall") if v["reason"] == "vor Wiederherstellung")
    full = db.get_doc_version(snap["id"])
    assert full["bodyMd"] == "neu" and full["manualMd"] == "Notiz aktuell"


def test_restore_version_without_notes_keeps_notes(temp_db):
    versions = _setup()
    old = versions[-1]
    db.set_doc_page_manual("notfall", "spaeter")
    page = db.restore_doc_version(old["id"])
    assert page["manualMd"] == "spaeter"
