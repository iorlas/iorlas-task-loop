"""Shared review switch policy."""
from tlkernel import workswitch as switch
from tltestkit.case import Case


class Switch(Case):
    def test_the_label_turns_it_off_and_nothing_turns_it_on(self):
        assert switch.mode("on", ["review-off"]) == "off"
        assert switch.mode("sampled", []) == "sampled"

    def test_sampled_reviews_every_nth_stage_and_the_last(self):
        got = [switch.reviews("sampled", stage=i, last=i == 4, every=3) for i in range(5)]
        assert got == [False, False, True, False, True]
        assert switch.reviews("off", stage=2, last=True, every=3)
        assert not switch.reviews("off", stage=0, last=False, every=3)
        assert switch.reviews("on", stage=0, last=False, every=3)

    def test_every_mode_requires_the_final_review(self):
        for mode in ("on", "off", "sampled"):
            with self.subTest(mode=mode):
                assert switch.reviews(mode, stage=0, last=True, every=5)
