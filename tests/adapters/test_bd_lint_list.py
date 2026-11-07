"""bd's lint error as a list (one section per line, each with its reason): every missing section is named, none with the reason."""


from taskloop.adapters import bd
from tlkernel.bdcreate import with_sections
from tltestkit.case import Case

LIST = """Error: missing required sections for task:
  - ## Acceptance Criteria (Define criteria to verify completion)
  - ## Touches (Required by lint.sections.task config)
"""


class LintList(Case):
    def test_every_section_of_a_listed_lint_error_is_named_without_its_reason(self):
        err = bd.error_of(LIST, "")
        assert (err.kind, err.missing_sections) == ("lint", ["Acceptance Criteria", "Touches"])

    def test_one_retry_adds_all_of_them(self):
        body = with_sections("why", bd.error_of(LIST, "").missing_sections, "tl-1")
        assert "## Acceptance Criteria\n" in body
        assert "## Touches\n" in body
