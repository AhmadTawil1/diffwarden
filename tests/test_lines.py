from app.lines import commentable_lines


def test_single_hunk_numbers_added_and_context_lines():
    patch = (
        "@@ -10,3 +10,4 @@ def f():\n"
        " a = 1\n"
        "+b = 2\n"
        " c = 3\n"
        " d = 4"
    )
    assert commentable_lines(patch) == {10: 0, 11: 0, 12: 0, 13: 0}


def test_second_hunk_starts_at_its_own_line_with_index_1():
    patch = (
        "@@ -1,2 +1,3 @@\n"
        " a\n"
        "+b\n"
        " c\n"
        "@@ -50,2 +51,2 @@\n"
        " x\n"
        "+y"
    )
    assert commentable_lines(patch) == {1: 0, 2: 0, 3: 0, 51: 1, 52: 1}


def test_deleted_lines_are_skipped_and_do_not_advance_the_counter():
    patch = (
        "@@ -5,3 +5,2 @@\n"
        " keep\n"
        "-gone\n"
        "+new"
    )
    assert commentable_lines(patch) == {5: 0, 6: 0}


def test_no_newline_marker_is_ignored():
    patch = (
        "@@ -1,1 +1,1 @@\n"
        "-old\n"
        "\\ No newline at end of file\n"
        "+new\n"
        "\\ No newline at end of file"
    )
    assert commentable_lines(patch) == {1: 0}
