def test_import_forge():
    import forge
    assert isinstance(forge.__version__, str)
