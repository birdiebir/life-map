import pytest

from lifemap.data import DataError, load_trips, load_visits


def test_loads_basic_row(places, write_csv):
    p = write_csv(["1,CITY-1,2019-02-02,2019-02-05,4,false,T1,範例回憶,,manual,高,true"])
    [v] = load_visits(p, places)
    assert v.place_id == "CITY-1" and v.level == 4 and v.together is False and v.confirmed is True
    assert v.memory == "範例回憶"


def test_excel_bom_and_crlf(places, write_csv):
    p = write_csv(["1,C-JPN,2019,,3,1,,,,manual,,yes"], encoding="utf-8-sig", newline="\r\n")
    [v] = load_visits(p, places)
    assert v.visit_id == "1" and v.together is True and v.confirmed is True


@pytest.mark.parametrize("date", ["", "2019", "2019-02", "2019-02-02"])
def test_partial_dates_accepted(places, write_csv, date):
    p = write_csv([f"1,C-JPN,{date},,3,false,,,,manual,,true"])
    assert load_visits(p, places)[0].date_start == date


def test_all_errors_reported_with_row_numbers(places, write_csv):
    p = write_csv([
        "1,C-NOPE,2019,,3,false,,,,manual,,true",
        "2,C-JPN,2019/02/02,,3,false,,,,manual,,true",
        "3,C-JPN,2019,,7,false,,,,manual,,true",
        "4,C-JPN,2019,,x,false,,,,manual,,true",
        "5,C-JPN,2019,,3,maybe,,,,manual,,true",
    ])
    with pytest.raises(DataError) as e:
        load_visits(p, places)
    msg = str(e.value)
    for row in ("第 2 列", "第 3 列", "第 4 列", "第 5 列", "第 6 列"):
        assert row in msg
    assert "C-NOPE" in msg


def test_duplicate_visit_id_rejected(places, write_csv):
    p = write_csv(["1,C-JPN,,,3,false,,,,manual,,true", "1,C-AUS,,,3,false,,,,manual,,true"])
    with pytest.raises(DataError, match="visit_id 重複"):
        load_visits(p, places)


def test_load_trips(write_csv):
    p = write_csv(["T1,範例家族旅遊,2019-02-02,2019-02-05,家人甲、家人乙,家族旅遊,"],
                  name="trips.csv", header="trip_id,name,date_start,date_end,companions,kind,kb_link\n")
    trips = load_trips(p)
    assert trips["T1"].name == "範例家族旅遊"
