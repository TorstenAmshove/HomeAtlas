"""#253: docs/specs/trace_specs.py rejects every `> OFFEN:` note that does not link an issue (`→ #N`).
Runs on a temporary spec tree, never on the real repository."""
import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "docs" / "specs" / "trace_specs.py"
_spec = importlib.util.spec_from_file_location("trace_specs", SCRIPT)
trace_specs = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(trace_specs)


def _tree(tmp_path, files):
    for name, text in files.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return trace_specs.unlinked_open_notes(tmp_path)


def test_note_without_link_is_reported_with_file_and_line(tmp_path):
    assert _tree(tmp_path, {"capabilities/a/spec.md": "# A\n\nText\n\n> OFFEN: Unklar.\n"}) == [
        "capabilities/a/spec.md:5"]


def test_linked_notes_pass(tmp_path):
    files = {"capabilities/a/spec.md": "> OFFEN: Eins. → #251\n\n- > OFFEN: Zwei → #7\n",
             "contracts/data-model.md": "übernehmen. > OFFEN: Datenübernahme gewünscht? → #252\n"}
    assert _tree(tmp_path, files) == []


def test_several_notes_in_one_file_and_mid_line(tmp_path):
    text = "> OFFEN: ok → #1\n\n> OFFEN: fehlt\n\nSatz davor. > OFFEN: auch fehlt\n"
    assert _tree(tmp_path, {"x.md": text}) == ["x.md:3", "x.md:5"]


def test_multiline_note_link_in_last_line(tmp_path):
    text = "- > OFFEN: Erste Zeile\n  zweite Zeile → #12\n\n- > OFFEN: ohne\n  Fortsetzung\n## Nächstes → #3\n"
    assert _tree(tmp_path, {"x.md": text}) == ["x.md:4"]


def test_headings_prose_template_and_non_issue_arrow_are_not_notes(tmp_path):
    files = {"capabilities/_template.md": "- > OFFEN: Unklarheiten, Widersprüche.\n",
             "README.md": "## OFFEN\n\n**OFFEN**: Unklarheit, die vor dem Bau zu klären ist.\n"
                          "Jeder `> OFFEN:`-Hinweis verlinkt sein Issue.\n",
             "capabilities/b/spec.md": "## OFFEN\n\n## Danach\n"}
    assert _tree(tmp_path, files) == []
    assert _tree(tmp_path, {"c.md": "> OFFEN: x → kein Issue, ADR-0009\n"}) == ["c.md:1"]


def test_real_specs_have_no_unlinked_note():
    assert trace_specs.unlinked_open_notes() == []
