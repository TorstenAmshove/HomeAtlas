import asyncio

from app import db, docs


def _add(name, project, key, kind="container"):
    extra = {"docker": {"composeProject": project, "image": "img"}} if kind == "container" else {}
    return db.upsert_discovered_system({
        "discoveryKey": key, "kind": kind, "name": name, "ip": "192.168.1.20", "status": "online",
        "discovered": 1, "discoverySource": "docker", "extra": extra,
    })[0]


def test_container_chapter_groups_by_stack(temp_db):
    _add("postgres · immich", "immich", "docker:immich:postgres")
    _add("postgres · pape|r", "pape|r", "docker:paper:postgres")
    _add("loose", "", "docker:loose")
    _add("Gast", "", "vm:1", kind="vm")
    asyncio.run(docs.generate(db.get_settings(), use_llm=False))
    body = db.get_doc_page("container-und-vms")["bodyMd"]
    assert "### Stack: immich" in body
    assert "### Stack: pape\\|r" in body
    assert "#### postgres · immich" in body
    assert body.index("### Ohne Compose-Projekt") > body.index("### Stack: immich")
    assert "#### loose" in body and "#### Gast" in body


def test_no_projects_stays_flat(temp_db):
    _add("loose", "", "docker:loose")
    asyncio.run(docs.generate(db.get_settings(), use_llm=False))
    body = db.get_doc_page("container-und-vms")["bodyMd"]
    assert "### loose" in body and "Stack:" not in body
