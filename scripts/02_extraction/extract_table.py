"""Extrai uma tabela Oracle para CSV ou Parquet usando lotes e paginação opcional.

Sem ``--page-column``, um cursor permanece aberto durante toda a extração e o
Oracle preserva um snapshot consistente, mas uma execução muito longa aumenta
o risco de ORA-01555 (snapshot too old). Com paginação, cada faixa usa um
SELECT novo: o cursor fica curto e reduz a pressão sobre UNDO, porém inserções
ou atualizações entre páginas podem ser observadas de forma diferente. A
paginação exige uma chave única ou uma coluna de desempate única para não
perder linhas silenciosamente.
"""

import argparse
import csv
import logging
import os
import sys
from datetime import datetime
from decimal import Decimal
from pathlib import Path


logger = logging.getLogger(__name__)


def load_dotenv(path):
    """Carrega variaveis simples do .env sem sobrescrever o ambiente."""
    if not path.exists():
        return
    with path.open(encoding="utf-8") as env_file:
        for raw_line in env_file:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def validate_identifier(value, label):
    """Valida nomes interpolados no SQL, que nao podem ser binds Oracle."""
    if not value or not value[0].isalpha() or not value.replace("_", "").isalnum():
        raise ValueError(f"{label} invalido: {value}")
    return value.upper()


def parse_args():
    project_dir = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, default=project_dir / ".env")
    parser.add_argument("--table", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--format", choices=("csv", "parquet"), default="parquet")
    parser.add_argument("--batch-size", type=int, default=5000)
    parser.add_argument("--arraysize", type=int, default=5000)
    parser.add_argument(
        "--page-column",
        help="Coluna crescente; sem ela usa cursor unico e snapshot consistente",
    )
    parser.add_argument(
        "--page-key",
        help="Chave UNIQUE para desempatar page-column nao unica, como created_at + id",
    )
    parser.add_argument(
        "--page-type",
        choices=("number", "date"),
        default="number",
        help="Tipo da coluna de paginação",
    )
    parser.add_argument("--page-size", type=int, default=50000)
    return parser.parse_args()


def load_oracledb(env_file):
    load_dotenv(env_file)
    missing = [name for name in ("ORACLE_USER", "ORACLE_PASSWORD", "ORACLE_DSN") if not os.getenv(name)]
    if missing:
        raise RuntimeError(f"Variaveis ausentes no ambiente/.env: {', '.join(missing)}")
    try:
        import oracledb
    except ImportError as error:
        raise RuntimeError("Instale o driver com: python -m pip install oracledb") from error
    return oracledb


def validate_pagination_columns(connection, table_name, page_column, page_key):
    """Exige coluna unica ou chave unica para evitar perda silenciosa de linhas."""
    if page_column is None:
        return
    cursor = connection.cursor()
    try:
        cursor.execute(
            """
            SELECT column_name
              FROM user_tab_columns
             WHERE table_name = :table_name
               AND column_name IN (:page_column, :page_key)
            """,
            {"table_name": table_name, "page_column": page_column, "page_key": page_key or page_column},
        )
        columns = {row[0] for row in cursor.fetchall()}
        required = {page_column} | ({page_key} if page_key else set())
        if not required.issubset(columns):
            raise ValueError(f"Coluna(s) de paginação inexistente(s): {sorted(required - columns)}")

        unique_column = page_key or page_column
        cursor.execute(
            """
            SELECT COUNT(*)
              FROM user_indexes i
              JOIN user_ind_columns ic ON ic.index_name = i.index_name
             WHERE i.table_name = :table_name
               AND i.uniqueness = 'UNIQUE'
               AND ic.column_name = :column_name
               AND ic.column_position = 1
               AND NOT EXISTS (
                   SELECT 1
                     FROM user_ind_columns extra
                    WHERE extra.index_name = ic.index_name
                      AND extra.column_position = 2
               )
            """,
            {"table_name": table_name, "column_name": unique_column},
        )
        if cursor.fetchone()[0] == 0:
            if page_key:
                raise ValueError(
                    f"--page-key {page_key} precisa ter indice UNIQUE de uma coluna"
                )
            raise ValueError(
                f"--page-column {page_column} nao e unica; informe --page-key com uma chave UNIQUE"
            )
    finally:
        cursor.close()


def format_csv_value(value):
    if isinstance(value, datetime):
        return value.isoformat(sep=" ")
    return value


def build_query(
    table_name,
    page_column=None,
    page_key=None,
    last_value=None,
    last_key_value=None,
    page_size=None,
):
    if page_column is None:
        return f"SELECT * FROM {table_name}", {}
    if last_value is None:
        where = ""
        binds = {}
    elif page_key is None:
        where = f" WHERE {page_column} > :last_value"
        binds = {"last_value": last_value}
    else:
        where = (
            f" WHERE ({page_column} > :last_value)"
            f" OR ({page_column} = :last_value AND {page_key} > :last_key_value)"
        )
        binds = {"last_value": last_value, "last_key_value": last_key_value}
    order_by = f"{page_column}, {page_key}" if page_key else page_column
    query = f"SELECT * FROM {table_name}{where} ORDER BY {order_by}"
    if page_size is not None:
        query += f" FETCH FIRST {page_size} ROWS ONLY"
    return query, binds


def iter_batches(
    connection,
    table_name,
    arraysize,
    batch_size,
    page_column,
    page_key,
    page_type,
    page_size,
):
    """Produz lotes e fecha cada cursor de pagina antes de abrir a proxima."""
    last_value = None
    last_key_value = None
    while True:
        query, binds = build_query(
            table_name,
            page_column,
            page_key,
            last_value,
            last_key_value,
            page_size if page_column else None,
        )
        cursor = connection.cursor()
        cursor.arraysize = arraysize
        page_last_value = None
        page_index = None
        try:
            cursor.execute(query, binds)
            descriptions = cursor.description
            column_names = [description[0].lower() for description in descriptions]
            if page_column is not None:
                page_index = column_names.index(page_column.lower())
            page_key_index = column_names.index(page_key.lower()) if page_key else None
            rows = cursor.fetchmany(batch_size)
            while rows:
                if page_index is not None:
                    page_last_value = rows[-1][page_index]
                if page_key_index is not None:
                    page_last_key_value = rows[-1][page_key_index]
                else:
                    page_last_key_value = None
                yield column_names, descriptions, rows
                rows = cursor.fetchmany(batch_size)
        finally:
            cursor.close()

        if page_column is None or page_last_value is None:
            return
        last_value = page_last_value
        if page_key is not None:
            last_key_value = page_last_key_value
        if page_type == "date" and not isinstance(last_value, datetime):
            raise ValueError(f"A coluna {page_column} nao retornou DATE Oracle")


class CsvSink:
    def __init__(self, output_path):
        self.file = output_path.open("w", newline="", encoding="utf-8")
        self.writer = None

    def write(self, column_names, descriptions, rows):
        if self.writer is None:
            self.writer = csv.writer(self.file)
            self.writer.writerow(column_names)
        self.writer.writerows(tuple(format_csv_value(value) for value in row) for row in rows)

    def close(self):
        self.file.close()


class ParquetSink:
    def __init__(self, output_path):
        try:
            import pyarrow as pa
            import pyarrow.parquet as parquet
        except ImportError as error:
            raise RuntimeError(
                "Parquet exige pyarrow; instale com: python -m pip install pyarrow"
            ) from error
        self.pa = pa
        self.parquet = parquet
        self.output_path = output_path
        self.writer = None

    def arrow_type(self, description, values):
        type_name = getattr(description[1], "name", str(description[1])).upper()
        precision = (description[4] if len(description) > 4 else None) or 38
        scale = (description[5] if len(description) > 5 else None) or 0
        if "NUMBER" in type_name:
            if scale == 0 and precision <= 18:
                return self.pa.int64()
            return self.pa.decimal128(min(max(precision, 1), 38), max(scale, 0))
        if "DATE" in type_name or "TIMESTAMP" in type_name:
            return self.pa.timestamp("us")
        if "BINARY_FLOAT" in type_name:
            return self.pa.float32()
        if "BINARY_DOUBLE" in type_name:
            return self.pa.float64()
        if "CHAR" in type_name or "CLOB" in type_name or "VARCHAR" in type_name:
            return self.pa.string()
        return self.pa.array(values).type

    def normalize_values(self, description, values, arrow_type):
        type_name = getattr(description[1], "name", str(description[1])).upper()
        if self.pa.types.is_int64(arrow_type):
            return [None if value is None else int(value) for value in values]
        if self.pa.types.is_decimal(arrow_type):
            return [None if value is None else Decimal(str(value)) for value in values]
        if self.pa.types.is_string(arrow_type):
            return [None if value is None else str(value) for value in values]
        if "DATE" in type_name or "TIMESTAMP" in type_name:
            return values
        return values

    def write(self, column_names, descriptions, rows):
        arrays = []
        for index in range(len(column_names)):
            values = [row[index] for row in rows]
            arrow_type = self.arrow_type(descriptions[index], values)
            values = self.normalize_values(descriptions[index], values, arrow_type)
            arrays.append(self.pa.array(values, type=arrow_type))
        table = self.pa.Table.from_arrays(arrays, names=column_names)
        if self.writer is None:
            self.writer = self.parquet.ParquetWriter(self.output_path, table.schema, compression="snappy")
        self.writer.write_table(table)

    def close(self):
        if self.writer is not None:
            self.writer.close()


def extract_table(connection, args):
    table_name = validate_identifier(args.table, "Tabela")
    page_column = validate_identifier(args.page_column, "Coluna de paginação") if args.page_column else None
    sink = CsvSink(args.output) if args.format == "csv" else ParquetSink(args.output)
    total_rows = 0
    batches = 0
    try:
        for column_names, descriptions, rows in iter_batches(
            connection,
            table_name,
            args.arraysize,
            args.batch_size,
            page_column,
            args.page_key,
            args.page_type,
            args.page_size,
        ):
            sink.write(column_names, descriptions, rows)
            total_rows += len(rows)
            batches += 1
            logger.info("%s: %d linhas extraidas", table_name, total_rows)
    finally:
        sink.close()
    return total_rows, batches


def main():
    args = parse_args()
    if args.batch_size < 1 or args.arraysize < 1 or args.page_size < 1:
        raise ValueError("batch-size, arraysize e page-size precisam ser maiores que zero")
    if args.page_column is None and args.page_type != "number":
        raise ValueError("--page-type so pode ser usado com --page-column")
    if args.page_key and not args.page_column:
        raise ValueError("--page-key exige --page-column")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    oracledb = load_oracledb(args.env_file)
    connection = oracledb.connect(
        user=os.environ["ORACLE_USER"],
        password=os.environ["ORACLE_PASSWORD"],
        dsn=os.environ["ORACLE_DSN"],
    )
    try:
        table_name = validate_identifier(args.table, "Tabela")
        page_column = validate_identifier(args.page_column, "Coluna de paginação") if args.page_column else None
        page_key = validate_identifier(args.page_key, "Chave de paginação") if args.page_key else None
        validate_pagination_columns(connection, table_name, page_column, page_key)
        total_rows, batches = extract_table(connection, args)
    finally:
        connection.close()
    logger.info("Concluido: %d linhas em %d lote(s), arquivo %s", total_rows, batches, args.output)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        main()
    except (RuntimeError, ValueError, OSError) as error:
        logger.error("%s", error)
        sys.exit(1)