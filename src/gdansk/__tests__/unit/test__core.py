from gdansk import _core


def test_hello_from_bin() -> None:
    assert _core.hello_from_bin() == "Hello from gdansk!"
