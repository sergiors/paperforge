from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from ..models import Pdf

pubsub_statements = (
    """
    CREATE OR REPLACE FUNCTION set_pdfs_updated_at()
    RETURNS TRIGGER
    LANGUAGE plpgsql
    AS $$
    BEGIN
        NEW.updated_at = NOW();
        RETURN NEW;
    END;
    $$;
    """,
    """
    CREATE OR REPLACE FUNCTION notify_pdf_change()
    RETURNS TRIGGER
    LANGUAGE plpgsql
    AS $$
    DECLARE
        payload JSON;
    BEGIN
        payload = json_build_object(
            'id', NEW.id,
            'status', NEW.status,
            'data', NEW.data,
            'created_at', NEW.created_at,
            'updated_at', NEW.updated_at
        );

        PERFORM pg_notify('pdf-status', payload::text);
        RETURN NEW;
    END;
    $$;
    """,
    'DROP TRIGGER IF EXISTS pdfs_set_updated_at ON pdfs;',
    """
    CREATE TRIGGER pdfs_set_updated_at
    BEFORE UPDATE ON pdfs
    FOR EACH ROW
    EXECUTE FUNCTION set_pdfs_updated_at();
    """,
    'DROP TRIGGER IF EXISTS pdfs_notify_change ON pdfs;',
    """
    CREATE TRIGGER pdfs_notify_change
    AFTER INSERT OR UPDATE ON pdfs
    FOR EACH ROW
    EXECUTE FUNCTION notify_pdf_change();
    """,
)


async def setup(engine: AsyncEngine) -> None:
    async with engine.begin() as connection:
        await connection.execute(
            text('SELECT pg_advisory_lock(:key)'),
            {'key': 1},
        )
        try:
            await connection.run_sync(_create_tables)

            for statement in pubsub_statements:
                await connection.exec_driver_sql(statement)
        finally:
            await connection.execute(
                text('SELECT pg_advisory_unlock(:key)'),
                {'key': 1},
            )


def _create_tables(sync_connection) -> None:
    Pdf.metadata.create_all(sync_connection)
