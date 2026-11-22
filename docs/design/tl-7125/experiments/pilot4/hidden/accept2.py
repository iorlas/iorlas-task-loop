import os, re, sys, unittest

sys.path.insert(0, os.path.join(os.getcwd(), "src"))


class Accept(unittest.TestCase):
    def tool(self):
        import aa.tools as tools
        self.assertIn("slug", tools.REGISTRY,
                      "the 'slug' tool is not in aa.tools.REGISTRY after `import aa.tools`: see how the existing tools are registered and loaded (docs/tools.md)")
        return tools.REGISTRY["slug"], tools.ToolError

    def test_registered_function_slugs(self):
        slug, _ = self.tool()
        for text, want in [("Hello World", "hello-world"), ("  A  b--c!! ", "a-b-c"), ("C3PO_rocks", "c3po-rocks"),
                           ("Zażółć gęślą 2", "za-g-l-2"), ("x", "x"), ("--a--", "a"), ("Ünï 1", "n-1")]:
            self.assertEqual(slug(text), want, f"slug({text!r})")

    def test_empty_result_error(self):
        slug, ToolError = self.tool()
        for text in ["", "   ", "!!!", "żółć"]:
            with self.assertRaises(ToolError, msg=f"slug({text!r}) must raise the repo's ToolError, not another exception type") as c:
                slug(text)
            self.assertRegex(str(c.exception), r"^slug: \S", "ToolError message format is '<tool name>: <reason>'")

    def test_module_location_and_import(self):
        self.tool()
        import aa.tools.slug as module
        self.assertIs(module.slug if hasattr(module, "slug") else None, self.tool()[0], "src/aa/tools/slug.py must define the registered function `slug`")

    def test_docs_table(self):
        import aa.tools as tools
        text = open("docs/tools.md").read()
        rows = set(re.findall(r"^\| (\w+) \|", text, re.M)) - {"name"}
        self.assertEqual(rows, set(tools.REGISTRY), "docs/tools.md table rows must list exactly the registered tools")


    def test_changelog(self):
        text = open("CHANGELOG.md").read()
        section = text.split("## Unreleased", 1)[-1]
        self.assertRegex(section, r"(?m)^- tool `slug`: [a-z][^\n]*[^.\n]$",
                         "CHANGELOG.md has no well-formed release note for tool 'slug' under '## Unreleased' (see CONTRIBUTING.md)")


unittest.main(argv=["accept", "-q"])
