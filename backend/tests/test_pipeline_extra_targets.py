from app import pipeline


def test_extra_targets(temp_db):
    temp_db.create_system({"kind": "server", "name": "manuell", "ip": "10.1.1.1"})
    temp_db.create_system({"kind": "server", "name": "innen", "ip": "192.168.1.5"})
    temp_db.create_system({"kind": "server", "name": "dup", "ip": "10.2.2.2"})
    temp_db.create_system({"kind": "server", "name": "kaputt", "ip": "kein-ip"})
    temp_db.create_system({"kind": "server", "name": "gefunden", "ip": "10.3.3.3", "discovered": 1})
    targets = pipeline._extra_targets({"scanExtraTargets": ["10.2.2.2"]}, ["192.168.1.0/24"])
    assert sorted(targets) == ["10.1.1.1", "10.2.2.2"]
