from sqlalchemy import Engine, text


def test_real_postgresql_connection_transaction_and_catalog(engine: Engine) -> None:
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT 1")) == 1
        connection.commit()

        transaction = connection.begin()
        connection.execute(text("CREATE TEMP TABLE backend_rollback_probe(id integer)"))
        transaction.rollback()

        assert connection.scalar(text("SELECT to_regclass('pg_temp.backend_rollback_probe') IS NULL")) is True
        assert connection.scalar(text("SELECT count(*) FROM information_schema.schemata WHERE schema_name IN ('core','capacity','production','planning','execution','portal','integration','audit')")) == 8
        assert connection.scalar(text("SELECT count(*) FROM information_schema.tables WHERE table_schema IN ('core','capacity','production','planning','execution','portal','integration','audit') AND table_type='BASE TABLE'")) == 87
