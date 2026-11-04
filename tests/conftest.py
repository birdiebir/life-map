import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lifemap.reference import Place  # noqa: E402

HEADER = "visit_id,place_id,date_start,date_end,level,together,trip_id,memory,photo,source,confidence,confirmed\n"


@pytest.fixture
def places():
    ps = [
        Place("C-TWN", "country", "Taiwan", "台灣", continent="AS"),
        Place("C-JPN", "country", "Japan", "日本", continent="AS"),
        Place("C-AUS", "country", "Australia", "澳洲", continent="OC"),
        Place("C-XKX", "country", "Kosovo", "科索沃", continent="EU"),
        Place("CITY-1", "city", "Naha", "那霸", parent="C-JPN", lat=26.2, lon=127.7),
        Place("CITY-2", "city", "Sydney", "雪梨", parent="C-AUS", lat=-33.9, lon=151.2),
        Place("TW-63000", "tw_county", "Taipei City", "臺北市", parent="C-TWN"),
        Place("TW-63000030", "tw_town", "Da'an District", "大安區", parent="TW-63000"),
        Place("TW-63000010", "tw_town", "Songshan District", "松山區", parent="TW-63000"),
        Place("TW-10015", "tw_county", "Hualien County", "花蓮縣", parent="C-TWN"),
    ]
    return {p.id: p for p in ps}


@pytest.fixture
def write_csv(tmp_path):
    def _write(rows: list[str], name="visits.csv", encoding="utf-8", newline="\n", header=HEADER):
        p = tmp_path / name
        text = header + "".join(r + "\n" for r in rows)
        p.write_bytes(text.replace("\n", newline).encode(encoding))
        return p
    return _write
