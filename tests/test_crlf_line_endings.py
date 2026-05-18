"""Reading ENDF files with Windows (CRLF) line endings.

An ENDF file edited or generated on Windows can carry CRLF (``\\r\\n``)
line terminators instead of the usual LF. The ordinary parser and the
multi-material tape interface must read such a file identically to its
LF form -- in particular the byte-exact :class:`TapeIndex` must record
section spans that still address genuine bytes.

The committed test fixtures are LF (pinned via ``.gitattributes`` so a
Windows checkout cannot rewrite them). These tests are therefore
self-contained: they synthesize both an LF and a CRLF copy from the
same content at run time and assert the two read back equal.
"""

import pytest
from pathlib import Path

from endf_parserpy import (
    EndfParserFactory,
    EndfFile,
    parse_tape_file,
    compare_objects,
)
from endf_parserpy.tape import TapeIndex


TESTDATA = Path(__file__).parent / "testdata"
CU = TESTDATA / "n_2925_29-Cu-63.endf"  # MAT 2925, single material


@pytest.fixture(params=["python", "cpp"])
def parser(request):
    try:
        return EndfParserFactory.create(select=request.param)
    except Exception:
        pytest.skip(f"{request.param} backend unavailable")


@pytest.fixture
def cu_lf_crlf(tmp_path):
    """An LF copy and a CRLF copy of the Cu-63 fixture, identical content.

    Both are built from the fixture normalized to LF, so the test does
    not depend on the line terminator the fixture happened to be checked
    out with.
    """
    base = CU.read_bytes().replace(b"\r\n", b"\n")
    lf = tmp_path / "cu_lf.endf"
    crlf = tmp_path / "cu_crlf.endf"
    lf.write_bytes(base)
    crlf.write_bytes(base.replace(b"\n", b"\r\n"))
    assert b"\r\n" in crlf.read_bytes() and b"\r\n" not in lf.read_bytes()
    return lf, crlf


def test_parsefile_reads_crlf(parser, cu_lf_crlf):
    """The single-material parser reads a CRLF file like its LF form."""
    lf_path, crlf_path = cu_lf_crlf
    assert compare_objects(
        parser.parsefile(lf_path),
        parser.parsefile(crlf_path),
        fail_on_diff=False,
    )


def test_tape_index_from_file_handles_crlf(cu_lf_crlf):
    """TapeIndex.from_file indexes a CRLF file; spans address real bytes."""
    lf_path, crlf_path = cu_lf_crlf
    lf_idx = TapeIndex.from_file(lf_path)
    crlf_idx = TapeIndex.from_file(crlf_path)
    assert len(lf_idx) == len(crlf_idx) == 1
    assert crlf_idx[0].mat == lf_idx[0].mat == 2925
    # the same sections are found regardless of the line terminator
    assert set(crlf_idx[0].sections) == set(lf_idx[0].sections)
    # every recorded CRLF span lies within the (larger) CRLF file
    crlf_size = crlf_path.stat().st_size
    for entry in crlf_idx[0].sections.values():
        assert 0 <= entry.offset < entry.offset + entry.length <= crlf_size


def test_endf_file_reads_crlf(parser, cu_lf_crlf):
    """EndfFile opens a CRLF tape and reads sections identically to LF."""
    lf_path, crlf_path = cu_lf_crlf
    with EndfFile(lf_path, parser=parser) as lf, EndfFile(
        crlf_path, parser=parser
    ) as crlf:
        assert len(lf) == len(crlf) == 1
        assert crlf["#0/1/451/AWR"] == lf["#0/1/451/AWR"]
        assert compare_objects(
            lf[0][3, 1].detach(),
            crlf[0][3, 1].detach(),
            fail_on_diff=False,
        )


def test_parse_tape_file_reads_crlf(parser, cu_lf_crlf):
    """parse_tape_file reads a CRLF tape like its LF form."""
    lf_path, crlf_path = cu_lf_crlf
    lf_mats = parse_tape_file(lf_path, parser=parser, on_error="raise")
    crlf_mats = parse_tape_file(crlf_path, parser=parser, on_error="raise")
    assert len(lf_mats) == len(crlf_mats) == 1
    assert compare_objects(lf_mats[0], crlf_mats[0], fail_on_diff=False)
