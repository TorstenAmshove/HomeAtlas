"""AK6 for the Task-5 sources: marker strings must not survive into facts, docs or errors."""
from app import docker_probe, docs

MARKERS = ["MARKER-TOKEN", "MARKER-PASS"]


def test_docker_label_markers_never_reach_facts():
    labels = {"homeatlas.ddns.hosts": "a.example.net", "x.token": "MARKER-TOKEN", "x.pass": "MARKER-PASS"}
    blob = str(docker_probe.ddns_fact("qmcgaw/ddns-updater", labels, "192.0.2.20"))
    assert not any(m in blob for m in MARKERS)


def test_chapter_with_all_sources_has_no_marker(temp_db):
    temp_db.replace_exposure_facts("cloudflare", "a", [
        {"kind": "cf_dns", "key": "x/A", "data": {"host": "x.example.net", "type": "A", "target": "203.0.113.5",
                                                  "proxied": False, "provider": "h.example"}}])
    temp_db.replace_exposure_facts("docker_ddns", "docker", [
        {"kind": "ddns", "key": "c", "data": {"client": "c", "provider": "Cloudflare", "hosts": ["d.example.net"],
                                              "ipv4": True, "ipv6": False, "via": "192.0.2.20"}}])
    text = docs._exposure_section()
    assert "MARKER" not in text
    assert "Status unklar" in text  # both outside sources are off by default
