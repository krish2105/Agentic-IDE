from __future__ import annotations

from sani_core.diffs import apply_hunks, compute_diff

BASE = "".join(f"line {i}\n" for i in range(1, 31))


def _edit(**changes: str) -> str:
    lines = BASE.splitlines(keepends=True)
    for index, text in changes.items():
        lines[int(index)] = text + "\n"
    return "".join(lines)


def test_a_new_file_is_one_all_additions_hunk():
    diff = compute_diff("new.py", "", "a\nb\n")
    assert diff.is_new_file is True
    assert len(diff.hunks) == 1
    assert all(line.startswith("+") for line in diff.hunks[0].lines)


def test_distant_edits_become_separate_hunks():
    diff = compute_diff("f.py", BASE, _edit(**{"0": "TOP", "29": "BOTTOM"}))
    assert len(diff.hunks) == 2
    assert diff.hunks[0].id == "h0"
    assert diff.hunks[1].id == "h1"
    assert diff.hunks[0].header.startswith("@@ -1,")


def test_adjacent_edits_collapse_into_one_hunk():
    diff = compute_diff("f.py", BASE, _edit(**{"10": "A", "11": "B"}))
    assert len(diff.hunks) == 1


def test_applying_every_hunk_reproduces_the_new_file():
    new = _edit(**{"0": "TOP", "29": "BOTTOM"})
    diff = compute_diff("f.py", BASE, new)
    assert apply_hunks(BASE, new, [h.id for h in diff.hunks]) == new


def test_applying_no_hunks_leaves_the_original_untouched():
    new = _edit(**{"0": "TOP", "29": "BOTTOM"})
    assert apply_hunks(BASE, new, []) == BASE


def test_none_means_accept_everything():
    new = _edit(**{"0": "TOP"})
    assert apply_hunks(BASE, new, None) == new


def test_selecting_one_hunk_applies_only_that_change():
    new = _edit(**{"0": "TOP", "29": "BOTTOM"})
    result = apply_hunks(BASE, new, ["h0"])

    assert result.startswith("TOP\n")
    assert result.endswith("line 30\n")
    assert "BOTTOM" not in result
    # Everything between the two hunks survives intact.
    assert "line 15\n" in result
    assert len(result.splitlines()) == len(BASE.splitlines())


def test_selecting_the_later_hunk_only():
    new = _edit(**{"0": "TOP", "29": "BOTTOM"})
    result = apply_hunks(BASE, new, ["h1"])
    assert result.startswith("line 1\n")
    assert result.endswith("BOTTOM\n")


def test_deletions_and_insertions_apply_per_hunk():
    lines = BASE.splitlines(keepends=True)
    new = "".join(lines[:2] + ["inserted\n"] + lines[2:14] + lines[15:])
    diff = compute_diff("f.py", BASE, new)
    assert len(diff.hunks) == 2

    only_insert = apply_hunks(BASE, new, ["h0"])
    assert "inserted\n" in only_insert
    assert "line 15\n" in only_insert, "the deletion hunk was not selected"

    only_delete = apply_hunks(BASE, new, ["h1"])
    assert "inserted\n" not in only_delete
    assert "line 15\n" not in only_delete


def test_unified_text_carries_standard_headers():
    diff = compute_diff("pkg/f.py", BASE, _edit(**{"0": "TOP"}))
    assert "--- a/pkg/f.py" in diff.unified
    assert "+++ b/pkg/f.py" in diff.unified
    assert "-line 1" in diff.unified
    assert "+TOP" in diff.unified


def test_a_delete_is_marked_and_shows_the_removed_content():
    diff = compute_diff("gone.txt", "bye\n", "", is_delete=True)
    assert diff.is_delete is True
    assert diff.is_new_file is False
    assert diff.hunks[0].lines == ["-bye\n"]


def test_identical_content_produces_no_hunks():
    diff = compute_diff("f.py", BASE, BASE)
    assert diff.hunks == []
    assert diff.unified == ""
