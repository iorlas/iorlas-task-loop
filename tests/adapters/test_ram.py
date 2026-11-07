"""macOS memory probes count reclaimable pages and fail open on unknown output."""


from taskloop.adapters import ram
from tltestkit.case import Case


class Ram(Case):
    def test_reclaimable_pages_respect_the_reported_page_size(self):
        text = ('Mach Virtual Memory Statistics: (page size of 16384 bytes)\n'
                'Pages free: 65536.\nPages inactive: 32768.\nPages speculative: 32768.\nPages wired down: 999999.\n')
        assert ram.available_mb(text) == 2048

    def test_unknown_or_damaged_reading_does_not_report_zero_memory(self):
        for text in ("", "wrong output", "header (page size of 4096 bytes)\nPages free: broken.",
                     "header (page size of 4096 bytes)\nPages active: 123."):
            with self.subTest(text=text):
                assert ram.available_mb(text) is None
