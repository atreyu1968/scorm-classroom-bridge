from pathlib import Path
from scorm_manifest import parse_manifest


def test_sample_manifest():
    root = Path(__file__).resolve().parents[1]
    info = parse_manifest(root / 'sample_scorm' / 'imsmanifest.xml')
    assert info.version == '1.2'
    assert info.entrypoint == 'index.html'
    assert 'SCORM Bridge' in info.title
