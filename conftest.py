# runs the examples of README.md (`pytest README.md`, see tasks.py):
# ```python blocks are executed, blocks starting with >>> are doctests
from sybil import Sybil
from sybil.parsers.markdown import PythonCodeBlockParser, SkipParser

# pytester runs the pytest plugin in its own pytest process (tests/test_pytest_plugin.py)
pytest_plugins = ["pytester"]

pytest_collect_file = Sybil(
    parsers=[PythonCodeBlockParser(), SkipParser()], patterns=["README.md"]
).pytest()
