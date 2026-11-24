"""ADR-0024: containers with a mounted docker.sock are flagged in the chapter, the list tool and nowhere else."""
import asyncio
import json

from app import db, docs, tools


def _add(temp_name, socket, key):
    return db.upsert_discovered_system({
        "discoveryKey": key, "kind": "container", "name": temp_name, "ip": "192.168.1.20", "status": "online",
        "discovered": 1, "discoverySource": "docker", "model": "img",
        "extra": {"docker": {"image": "img", "composeProject": "", "dockerSocket": socket}},
    })[0]


def test_chapter_and_tool_flag_only_socket_containers(temp_db):
    _add("portainer", True, "docker:portainer")
    _add("plain", False, "docker:plain")
    asyncio.run(docs.generate(db.get_settings(), use_llm=False))
    body = db.get_doc_page("container-und-vms")["bodyMd"]
    assert body.count("Container hat Vollzugriff auf Docker (entspricht Root auf dem Host)") == 2  # summary + detail
    assert "(entspricht Root auf dem Host): **portainer**." in body
    assert "Socket-Proxy" in body
    plain = body.split("### plain")[1].split("### portainer")[0]
    assert "Vollzugriff" not in plain
    result = json.loads(asyncio.run(tools.dispatch("list_containers", {})))
    flags = {c["name"]: c.get("dockerSocket") for c in result["containers"]}
    assert flags == {"portainer": True, "plain": False}


def test_no_notice_without_socket_containers(temp_db):
    _add("plain", False, "docker:plain")
    asyncio.run(docs.generate(db.get_settings(), use_llm=False))
    assert "Vollzugriff" not in db.get_doc_page("container-und-vms")["bodyMd"]
