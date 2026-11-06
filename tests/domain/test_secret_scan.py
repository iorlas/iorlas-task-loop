"""A candidate diff that adds a credential is named before it is pushed (tl-7i9k.53, M-035)."""
from unittest import mock

import pytest

from taskloop.app.run import plumbing
from taskloop.domain.matchers import redact, secrets_added

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


SK = 'API_KEY = "sk-live-0123456789abcdef0123456789"'


def test_redact_hides_a_credential_wherever_it_sits_and_leaves_the_rest():
    text = f"check failed\n{KEY}\nMIIEvQIBADANBg\n-----END RSA PRIVATE KEY-----\nuse {AWS} and {GH}\n{SK}\nfine line"
    out = redact(text)
    for secret in (AWS, GH, "sk-live-0123456789abcdef0123456789", "MIIEvQIBADANBg"):
        assert secret not in out
    assert out.startswith("check failed\n") and out.endswith("fine line")
    assert redact("plain text, no secrets") == "plain text, no secrets"


def test_the_one_comment_poster_redacts_before_the_log_and_the_bead():
    me = mock.Mock(dry=False, bead="t-1")
    me.step_id.return_value = "s1"
    plumbing.Plumbing.comment(me, f"worker said {AWS}")
    assert AWS not in me.store.add_comment.call_args.args[1]
    assert AWS not in me.log.emit.call_args.args[0].text
