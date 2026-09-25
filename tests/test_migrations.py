from alembic import command
from alembic.config import Config
from sqlalchemy import inspect


def test_migrations_match_models_and_are_reversible(application):
    config = Config("alembic.ini")
    command.check(config)
    command.downgrade(config, "base")
    assert inspect(application.state.engine).get_table_names() == ["alembic_version"]
    command.upgrade(config, "head")
    assert "telemetry" in inspect(application.state.engine).get_table_names()


def test_postgres_migration_sql_compiles(monkeypatch, capsys):
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://test:test@localhost/test")
    command.upgrade(Config("alembic.ini"), "head", sql=True)
    sql = capsys.readouterr().out
    assert "TIMESTAMP WITH TIME ZONE" in sql
    assert "CREATE TABLE telemetry" in sql
