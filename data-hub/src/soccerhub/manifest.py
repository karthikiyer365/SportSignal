import json
from dataclasses import asdict, dataclass


DATE_COLS = ("date", "datetime", "timestamp", "year")


@dataclass
class Manifest:
    path: str
    source: str
    dataset: str
    params: dict
    rows: int
    cols: int
    date_range: tuple | None
    fetched_at: str

    def to_json(self) -> str:
        return json.dumps(asdict(self), sort_keys=True)

    @classmethod
    def from_json(cls, s: str) -> "Manifest":
        d = json.loads(s)
        if d.get("date_range") is not None:
            d["date_range"] = tuple(d["date_range"])
        return cls(**d)


def infer_date_range(df) -> tuple | None:
    for col in DATE_COLS:
        if col in df.columns and len(df):
            series = df[col].dropna()
            if len(series):
                return (str(series.min()), str(series.max()))
    return None
