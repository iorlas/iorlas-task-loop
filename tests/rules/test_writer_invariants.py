"""Store ownership depends on AST write operations, not the number or spelling of text mentions."""
import ast

from support.case import Case

from rules.writer_invariants import writer_problems, writer_tree_problems


class WriterInvariants(Case):
    def problems(self, module, text):
        return writer_problems(module, ast.parse(text))

    def test_a_second_module_cannot_write_the_pin_store_even_through_aliases(self):
        for code in (
            "from taskloop.contracts.stores import PinStore\nPinStore(cfg).write(pin)",
            "from taskloop.contracts.stores import PinStore as S\ns = S(cfg)\ns.write(pin)",
            "from taskloop.contracts import stores as s\nx = s.PinStore(cfg)\nf = x.delete\nf()",
        ):
            assert self.problems("taskloop.app.loop.versions", code), code
            assert self.problems("taskloop.app.release.pins", code) == []

    def test_reading_a_store_is_allowed_and_comments_do_not_write(self):
        assert self.problems("taskloop.app.loop.versions",
            "from taskloop.contracts.stores import PinStore\nPinStore(cfg).get()\n# PinStore(cfg).write(pin)\n"
            "doc = 'PinStore(cfg).delete()'") == []

    def test_a_local_writer_factory_retains_the_store_identity(self):
        assert self.problems("taskloop.app.loop.versions",
            "from taskloop.contracts.stores import PinStore\ndef factory():\n return PinStore(cfg)\n"
            "factory().write(pin)")

    def test_writer_rules_do_not_leak_variable_bindings_between_functions(self):
        assert self.problems("taskloop.app.loop.versions",
            "from taskloop.contracts.stores import PinStore\ndef reader():\n s = PinStore(cfg)\n return s.get()\n"
            "def unrelated(s):\n s.write('text')") == []

    def test_only_plan_and_raw_answer_destinations_are_allowed_to_write_json(self):
        assert self.problems("taskloop.app.run.engine",
            "import json\n(self.run_dir / PLAN_FILE).write_text(json.dumps(plancheck.to_wire(self.plan_data)))") == []
        assert self.problems("taskloop.app.run.engine", "import json\np.write_text(json.dumps(state))")
        assert self.problems("taskloop.app.other", "import os as o\no.replace(a, b)")

    def test_events_path_has_one_owner_and_is_found_with_whitespace(self):
        code = "cfg . events ( )"
        assert self.problems("taskloop.app.loop.files", code)
        assert self.problems("taskloop.app.track.trail", code) == []

    def test_multiple_legitimate_writes_do_not_spend_a_count_budget(self):
        code = "from taskloop.contracts.stores import PinStore\n" + "PinStore(cfg).write(pin)\n" * 3
        assert self.problems("taskloop.app.release.pins", code) == []

    def test_generic_json_store_cannot_bypass_the_pin_owner(self):
        assert self.problems("taskloop.app.loop.versions",
            "from taskloop.contracts.stores import JsonStore\ns = JsonStore(cfg.pin(), Pin)\ns.write(pin)")
        assert self.problems("taskloop.app.loop.versions",
            "from taskloop.contracts.stores import JsonlStore\ns = JsonlStore(cfg.pin(), decode)\ns.append(pin)")

    def test_store_attributes_keep_their_identity_across_class_methods(self):
        assert self.problems("taskloop.app.loop.versions",
            "from taskloop.contracts.stores import PinStore\nclass C:\n"
            " def __init__(self):\n  self.store = PinStore(cfg)\n def act(self):\n  self.store.write(pin)")

    def test_json_payload_aliases_cannot_hide_a_state_write(self):
        assert self.problems("taskloop.app.run.engine",
            "import json as j\nraw = j.dumps(state)\np.write_text(raw)")

    def test_new_store_types_need_an_explicit_writer(self):
        assert self.problems("taskloop.app.loop.versions",
            "from taskloop.contracts.stores import FutureStore\ns = FutureStore(cfg)\ns.write(value)")

    def test_importing_a_writer_factory_does_not_grant_ownership(self):
        trees = {
            "taskloop.app.release.pins": ast.parse("from taskloop.contracts.stores import PinStore\n"
                                                  "def pin_store(cfg):\n return PinStore(cfg)"),
            "taskloop.app.loop.versions": ast.parse("from taskloop.app.release.pins import pin_store as factory\n"
                                                   "factory(cfg).write(pin)"),
        }
        assert writer_tree_problems(trees)
