from app.core.config import Settings


def test_data_dir_defaults_to_localappdata(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.delenv("POS_DATA_DIR", raising=False)

    config = Settings(pos_data_dir=None)

    assert config.data_dir == tmp_path / "POSApp" / "data"
    assert config.data_dir.is_dir()
    assert config.database_url.startswith("sqlite:///")


def test_pos_data_dir_override_points_to_shared_folder(tmp_path):
    target = tmp_path / "shared" / "posdata"
    config = Settings(pos_data_dir=str(target))

    assert config.data_dir == target
    assert target.is_dir()
    assert str(target / "pos.db") in config.database_url


def test_pos_data_dir_read_from_environment(tmp_path, monkeypatch):
    target = tmp_path / "from-env"
    monkeypatch.setenv("POS_DATA_DIR", str(target))

    config = Settings(_env_file=None)

    assert config.pos_data_dir == str(target)
    assert config.data_dir == target
    assert target.is_dir()
