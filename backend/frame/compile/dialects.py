from __future__ import annotations

from abc import ABC, abstractmethod

from frame.semantic.model import Source


class Dialect(ABC):
    name: str

    @staticmethod
    def quote(ident: str) -> str:
        """Quote an identifier we invented — an output alias.

        Aliases are preserved exactly as written, because the client keys its
        columns on them (`"exception.count"`).
        """
        return '"' + ident.replace('"', '""') + '"'

    def column(self, ident: str) -> str:
        """Quote a physical column that already exists in the warehouse.

        Separate from `quote` because the two have opposite requirements: an
        alias must survive verbatim, while a physical column has to match
        however the warehouse actually stored the name.
        """
        return self.quote(ident)

    @abstractmethod
    def placeholder(self, name: str) -> str: ...

    @abstractmethod
    def relation(self, source: Source) -> str: ...

    def stddev(self, expr: str) -> str:
        return f"STDDEV_SAMP({expr})"


class DuckDBDialect(Dialect):
    """Local development and the server-side cube tier."""

    name = "duckdb"

    def placeholder(self, name: str) -> str:
        return f"${name}"

    def relation(self, source: Source) -> str:
        return source.local or source.relation


class SnowflakeDialect(Dialect):
    name = "snowflake"

    def placeholder(self, name: str) -> str:
        # snowflake-connector-python default paramstyle is pyformat.
        return f"%({name})s"

    def relation(self, source: Source) -> str:
        return source.relation

    def column(self, ident: str) -> str:
        """Snowflake folds unquoted identifiers to upper case at creation.

        A column created as `exception_id` is stored as `EXCEPTION_ID`, so
        emitting the lower-case `"exception_id"` fails to resolve — the single
        most common way a query that works locally dies on Snowflake. Model a
        genuinely case-sensitive column by quoting it in the YAML, and it is
        passed through untouched.
        """
        if ident.startswith('"') and ident.endswith('"'):
            return ident
        return self.quote(ident.upper())


_DIALECTS: dict[str, Dialect] = {
    "duckdb": DuckDBDialect(),
    "snowflake": SnowflakeDialect(),
}


def get_dialect(name: str) -> Dialect:
    try:
        return _DIALECTS[name]
    except KeyError:
        raise KeyError(f"unknown dialect {name!r}; have {sorted(_DIALECTS)}") from None
