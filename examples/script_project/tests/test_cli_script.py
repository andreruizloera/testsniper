import subprocess


def test_greet_prints_hello():
    # Imports nothing from pkg. The only link to pkg.cli is the
    # [project.scripts] line in pyproject.toml.
    out = subprocess.run(["greet"], capture_output=True, text=True, check=True).stdout
    assert out.strip() == "hello"
