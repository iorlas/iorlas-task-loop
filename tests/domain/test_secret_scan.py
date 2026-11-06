"""A candidate diff that adds a credential is named before it is pushed (tl-7i9k.53, M-035)."""
import pytest

from taskloop.domain.matchers import secrets_added

KEY = "-----BEGIN " + "RSA PRIVATE KEY-----"
AWS = "AKIA" + "ABCDEFGHIJKLMNOP"
GH = "ghp_" + "a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8"


def added(*lines):
    return "diff --git a/f b/f\n--- a/f\n+++ b/f\n@@ -0,0 +1 @@\n" + "".join(f"+{x}\n" for x in lines)


@pytest.mark.parametrize(("line", "kind"), [(KEY, "private key"), (f"id = {AWS}", "AWS access key"), (f"t={GH}", "GitHub token"),
                                           ('API_KEY = "sk-live-0123456789abcdef0123456789"', "assigned secret")])
def test_an_added_credential_is_named(line, kind):
    assert secrets_added(added("ok", line)) == [kind]


def test_removed_lines_context_and_plain_text_are_not_secrets():
    diff = f"--- a/f\n+++ b/f\n@@ -1 +1 @@\n-{AWS}\n {KEY}\n+token = os.environ['API_KEY']\n+the key is in the vault\n"
    assert secrets_added(diff) == []
