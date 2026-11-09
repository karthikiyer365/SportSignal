def test_top_level_exports():
    import soccerhub

    for name in (
        "fetch_fbref_season",
        "fetch_statsbomb_events",
        "fetch_transfermarkt_values",
        "Manifest",
        "SoccerhubError",
    ):
        assert hasattr(soccerhub, name), name
