"""Doctor describes product flags without harness routing configuration."""
from taskloop.app.doctor import ops


def test_product_lines():
    assert ops.product_lines(True, False) == [
        "writer_exec: on (delegate routing settings own the writer pin and exec grant)",
        "reviewer_other_family: off",
    ]
    assert ops.product_lines(False, True)[1] == "reviewer_other_family: on"
