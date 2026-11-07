"""The member plugin installs Case helpers without the root conftest."""
from tltestkit.case import Case


class TestCaseHelpers(Case):
    def test_cleanup_and_subtest(self):
        cleaned = []
        def check_cleanup():
            assert cleaned == ["second", "first"]

        self.addCleanup(check_cleanup)
        self.addCleanup(lambda: cleaned.append("first"))
        self.addCleanup(lambda: cleaned.append("second"))
        with self.subTest(value=1):
            assert self._testMethodName == "test_cleanup_and_subtest"
            assert self.id().endswith("TestCaseHelpers::test_cleanup_and_subtest")
