import dinkdata.events


def test_imports():
    assert dinkdata.events.__doc__


def test_fixture_events_are_ordered_and_carry_conf(events_json):
    for rally in events_json["rallies"]:
        times = [event["t"] for event in rally["events"]]
        assert times == sorted(times)
        assert all(0 <= event["conf"] <= 1 for event in rally["events"])
        assert rally["start_frame"] <= times[0] and times[-1] <= rally["end_frame"]
