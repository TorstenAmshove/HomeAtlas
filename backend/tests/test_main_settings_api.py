"""Controller-network selection is stored through the generic settings merge."""
from app import db


def test_controller_network_selection_roundtrip(temp_db):
    temp_db.update_settings({"scanControllerNetworkIds": ["a"], "scanControllerNetworksSeen": ["a", "b"]})
    temp_db.update_settings({"homeName": "X"})
    settings = db.get_settings()
    assert settings["scanControllerNetworkIds"] == ["a"]
    assert settings["scanControllerNetworksSeen"] == ["a", "b"]
    assert db.DEFAULT_SETTINGS["scanControllerNetworkIds"] == []
