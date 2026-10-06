import numpy as np
import pandas as pd
import pytest

from soccerhub.pipelines import statcast as sc


@pytest.fixture(autouse=True)
def _cache_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("SOCCERHUB_CACHE", str(tmp_path))


def _pitches(n, **kw):
    base = {c: [np.nan] * n for c in sc.COLS}
    base.update(game_pk=[1] * n, at_bat_number=[1] * n, pitch_number=list(range(n)), pitcher=[10] * n,
                player_name=["Ace"] * n, p_throws=["R"] * n, pitch_type=["FF"] * n, description=["ball"] * n,
                delta_run_exp=[0.05] * n, spin_axis=[200.0] * n, pfx_x=[-0.5] * n, pfx_z=[1.2] * n)
    base.update({k: v if isinstance(v, list) else [v] * n for k, v in kw.items()})
    return pd.DataFrame(base)


def test_normalise_hand_mirrors_lefties_only():
    df = pd.DataFrame({"p_throws": ["R", "L"], "pfx_x": [-0.5, 0.5], "release_pos_x": [-2.0, 2.0],
                       "vx0": [5.0, -5.0], "ax": [-10.0, 10.0], "spin_axis": [200.0, 160.0]})
    out = sc.normalise_hand(df)
    assert out.pfx_x.tolist() == [-0.5, -0.5]
    assert out.release_pos_x.tolist() == [-2.0, -2.0]
    assert out.vx0.tolist() == [5.0, 5.0] and out.ax.tolist() == [-10.0, -10.0]
    assert out.spin_axis.tolist() == [200.0, 200.0]


def test_load_season_keeps_regular_season_and_dedupes(monkeypatch):
    raw = _pitches(3).assign(game_type=["R", "R", "S"], pitch_number=[1, 1, 2])

    class M:
        path = "x"

    monkeypatch.setattr(sc, "fetch_month", lambda y, m, f: M())
    monkeypatch.setattr(sc.pd, "read_parquet", lambda p: raw if p == "x" else None)
    out = sc.load_season(2025)
    # 9 identical months -> one regular-season pitch survives; spring training dropped
    assert len(out) == 1 and "game_type" not in out.columns


def test_arsenal_cut_sign_usage_and_axis():
    ff = _pitches(60, description=["swinging_strike"] * 20 + ["foul"] * 20 + ["ball"] * 20,
                  spin_axis=[350.0] * 30 + [10.0] * 30)
    sl = _pitches(30, pitch_type="SL", delta_run_exp=-0.02, description="swinging_strike")
    cu = _pitches(5, pitch_type="CU")  # under MIN_PITCHES -> dropped
    out = sc.arsenal(pd.concat([ff, sl, cu], ignore_index=True), 2025).set_index("pitch_type")

    assert set(out.index) == {"FF", "SL"}
    assert out.loc["FF", "rv_per_100"] == pytest.approx(-5.0)  # batter gained runs -> bad for pitcher
    assert out.loc["SL", "rv_per_100"] == pytest.approx(2.0)
    assert out.loc["FF", "usage_pct"] == pytest.approx(60 / 95)  # usage counts the cut CU too
    assert out.loc["FF", "whiff_pct"] == pytest.approx(0.5)
    assert np.isnan(out.loc["SL", "whiff_pct"])  # 30 pitches < MIN_PITCHES_RV: too noisy to show
    assert out.loc["FF", "spin_axis"] == pytest.approx(0.0, abs=1e-6) or out.loc["FF", "spin_axis"] == pytest.approx(360.0)
    assert out.loc["FF", "hb_arm_in"] == pytest.approx(6.0)


def test_upload_season_one_file_per_month(monkeypatch):
    sent = []

    class Bucket:
        def upload(self, path, body, opts):
            sent.append(path)

    class Client:
        storage = type("S", (), {"from_": lambda self, name: Bucket()})()

    monkeypatch.setenv("SUPABASE_URL", "http://x")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "k")
    monkeypatch.setattr("supabase.create_client", lambda url, key: Client())
    df = _pitches(3, game_date=list(pd.to_datetime(["2025-04-01", "2025-04-02", "2025-05-01"])))
    assert sc.upload_season(df, 2025) > 0
    assert sent == ["pitches/2025/04.parquet", "pitches/2025/05.parquet"]
