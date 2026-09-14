@pytest.mark.parametrize("mime", [
    "text/markdown", "application/json", "image/png", "image/jpeg",
    "image/webp", "audio/wav", "video/mp4",
])
def test_preview_mime_allowlist_contains_exact_v1_types(mime):
    from forge.services.catalogo import PREVIEW_MIME
    assert mime in PREVIEW_MIME
