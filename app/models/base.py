from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

JOBAI_SCHEMA = "jobai"


class Base(DeclarativeBase):
    """Declarative base mapped onto the existing ``jobai`` schema.

    Tables are owned by db/jobai_v1_schema.sql; never call ``create_all``/``drop_all``.
    """

    metadata = MetaData(schema=JOBAI_SCHEMA)
