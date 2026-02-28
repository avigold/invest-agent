from app.db.models import (
    Artefact,
    Country,
    CountryRiskRegister,
    CountryScore,
    CountrySeries,
    CountrySeriesPoint,
    DataSource,
    DecisionPacket,
)


def test_data_source_tablename():
    assert DataSource.__tablename__ == "data_sources"


def test_artefact_tablename():
    assert Artefact.__tablename__ == "artefacts"


def test_country_tablename():
    assert Country.__tablename__ == "countries"


def test_country_series_tablename():
    assert CountrySeries.__tablename__ == "country_series"


def test_country_series_point_tablename():
    assert CountrySeriesPoint.__tablename__ == "country_series_points"


def test_country_score_tablename():
    assert CountryScore.__tablename__ == "country_scores"


def test_risk_register_tablename():
    assert CountryRiskRegister.__tablename__ == "country_risk_register"


def test_decision_packet_tablename():
    assert DecisionPacket.__tablename__ == "decision_packets"


def test_data_source_columns():
    cols = {c.name for c in DataSource.__table__.columns}
    assert cols == {"id", "name", "base_url", "requires_auth", "created_at"}


def test_artefact_columns():
    cols = {c.name for c in Artefact.__table__.columns}
    expected = {
        "id", "data_source_id", "source_url", "fetch_params", "fetched_at",
        "time_window_start", "time_window_end", "content_hash", "storage_uri",
        "size_bytes", "created_at",
    }
    assert cols == expected


def test_country_columns():
    cols = {c.name for c in Country.__table__.columns}
    assert cols == {"id", "iso2", "iso3", "name", "equity_index_symbol", "config_version", "created_at"}


def test_country_series_columns():
    cols = {c.name for c in CountrySeries.__table__.columns}
    assert cols == {"id", "country_id", "series_name", "source", "indicator_code", "unit", "frequency", "created_at"}


def test_country_series_point_columns():
    cols = {c.name for c in CountrySeriesPoint.__table__.columns}
    assert cols == {"id", "series_id", "artefact_id", "date", "value", "created_at"}


def test_country_score_columns():
    cols = {c.name for c in CountryScore.__table__.columns}
    expected = {
        "id", "country_id", "as_of", "calc_version",
        "macro_score", "market_score", "stability_score", "overall_score",
        "component_data", "point_ids", "created_at",
    }
    assert cols == expected


def test_risk_register_columns():
    cols = {c.name for c in CountryRiskRegister.__table__.columns}
    expected = {
        "id", "country_id", "risk_type", "severity", "description",
        "detected_at", "resolved_at", "artefact_id", "created_at",
    }
    assert cols == expected


def test_decision_packet_columns():
    cols = {c.name for c in DecisionPacket.__table__.columns}
    expected = {
        "id", "packet_type", "entity_id", "as_of", "summary_version",
        "content", "score_ids", "created_at",
    }
    assert cols == expected
