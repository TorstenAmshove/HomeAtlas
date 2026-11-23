"""Generated documentation: chapters, manual notes, whole-page override, versions.

Moved out of main.py unchanged; see main.py for the cross-cutting rules."""
from __future__ import annotations

from fastapi import APIRouter, Body, Depends, HTTPException

from .. import db, docs
from ..deps import current_user, require_admin

router = APIRouter()


# ---------------------------------------------------------------------------------------------
# Documentation
# ---------------------------------------------------------------------------------------------

@router.get("/api/docs")
async def list_docs(_: dict = Depends(current_user)) -> dict:
    return {"pages": [{k: v for k, v in p.items() if k != "bodyMd"} for p in db.list_doc_pages()]}


@router.get("/api/docs/{slug}")
async def get_doc(slug: str, _: dict = Depends(current_user)) -> dict:
    page = db.get_doc_page(slug)
    if page is None:
        raise HTTPException(status_code=404, detail="Kapitel nicht gefunden.")
    return {"page": page}


@router.put("/api/docs/{slug}")
async def edit_doc(slug: str, body: dict = Body(...), _: dict = Depends(require_admin)) -> dict:
    page = db.set_doc_page_body(slug, body.get("bodyMd", ""))
    if page is None:
        raise HTTPException(status_code=404, detail="Kapitel nicht gefunden.")
    return {"page": page}


@router.put("/api/docs/{slug}/manual")
async def edit_doc_manual(slug: str, body: dict = Body(...), _: dict = Depends(require_admin)) -> dict:
    """The household's own notes for a chapter. Kept apart from the generated body so a scan can
    keep refreshing the device tables while this text stays exactly as written."""
    if db.get_doc_page(slug) is None:
        raise HTTPException(status_code=404, detail="Kapitel nicht gefunden.")
    return {"page": db.set_doc_page_manual(slug, body.get("manualMd", ""))}


def _reject_if_generating() -> None:
    if docs.is_generating():
        raise HTTPException(status_code=409, detail="Die Dokumentation wird gerade erzeugt.")


@router.post("/api/docs/{slug}/reset")
async def reset_doc(slug: str, _: dict = Depends(require_admin)) -> dict:
    _reject_if_generating()
    db.reset_doc_page(slug)
    settings = db.get_settings()
    await docs.generate(settings, use_llm=settings.get("scanUseLlm", True), only_slug=slug)
    return {"page": db.get_doc_page(slug)}


@router.post("/api/docs/generate")
async def generate_docs(body: dict = Body(default={}), _: dict = Depends(require_admin)) -> dict:
    """Regenerates all chapters. The setting `scanUseLlm` is the master switch: `useLlm: false` in
    the request can turn the AI intros off, but `useLlm: true` does not force them on while the
    setting is off."""
    _reject_if_generating()
    settings = db.get_settings()
    use_llm = body.get("useLlm", settings.get("scanUseLlm", True))
    slugs = await docs.generate(settings, use_llm=use_llm)
    return {"generated": slugs}


@router.get("/api/docs/{slug}/versions")
async def list_doc_versions(slug: str, _: dict = Depends(current_user)) -> dict:
    return {"versions": db.list_doc_versions(slug)}


@router.get("/api/docs/{slug}/versions/{version_id}")
async def get_doc_version(slug: str, version_id: str, _: dict = Depends(current_user)) -> dict:
    version = db.get_doc_version(version_id)
    if version is None or version["slug"] != slug:
        raise HTTPException(status_code=404, detail="Version nicht gefunden.")
    return {"version": version}


@router.post("/api/docs/{slug}/versions/{version_id}/restore")
async def restore_doc_version(slug: str, version_id: str, _: dict = Depends(require_admin)) -> dict:
    version = db.get_doc_version(version_id)
    if version is None or version["slug"] != slug:
        raise HTTPException(status_code=404, detail="Version nicht gefunden.")
    page = db.restore_doc_version(version_id)
    return {"page": page}
