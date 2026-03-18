from gdansk import LightningCSS


def test_lightningcss_exposes_expected_id():
    assert LightningCSS().id == "lightningcss"
