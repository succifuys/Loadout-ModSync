import os
import subprocess
import pytest
from dntsne.common import SyncError,safe_join,fingerprint,descriptor_fingerprint


@pytest.mark.skipif(os.name!='nt',reason='Windows junction test')
def test_real_windows_junction_rejected(tmp_path):
    root=tmp_path/'mods'
    outside=tmp_path/'outside'
    root.mkdir()
    outside.mkdir()
    (outside/'secret').write_bytes(b'foreign')
    junction=root/'Example'
    result=subprocess.run(['cmd','/c','mklink','/J',str(junction),str(outside)],capture_output=True)
    if result.returncode:
        pytest.skip('Windows junction creation unavailable')
    with pytest.raises(SyncError,match='junction'):
        safe_join(root,'Example/secret')
    assert (outside/'secret').read_bytes()==b'foreign'


def test_descriptor_matches_path_when_creation_and_write_times_differ(tmp_path):
    file=tmp_path/'different-times.bin'
    file.write_bytes(b'fixture')
    initial=file.stat().st_mtime_ns
    os.utime(file,ns=(initial,initial+10_000_000_000))
    with file.open('rb') as stream:
        assert fingerprint(file)==descriptor_fingerprint(stream)
