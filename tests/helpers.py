import os

HERE = os.path.dirname(os.path.abspath(__file__))
FIXTURES = os.path.join(HERE, "fixtures")
ROOT = os.path.dirname(HERE)
EXAMPLES = os.path.join(ROOT, "examples")


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()
