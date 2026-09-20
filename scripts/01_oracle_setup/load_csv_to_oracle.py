"""Carrega o dataset CSV gerado no Oracle."""

import argparse
import csv
import logging
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path


logger = logging.getLogger(__name__)
IDENTIFIER_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_$#]*$")
DATE_FORMATS = ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d")
CREATE_TABLE_RE = re.compile(
    r"CREATE TABLE (?P<table>[A-Za-z][A-Za-z0-9_$#]*) \((?P<body>.*?)\);",
    re.IGNORECASE | re.DOTALL,
)
COLUMN_TYPE_RE = re.compile(
    r"^\s+(?P<column>[A-Za-z][A-Za-z0-9_$#]*)\s+(?P<type>[A-Za-z0-9]+(?:\([^)]*\))?)\s*,?\s*$",
    re.IGNORECASE,
)

# As tabelas pai sao carregadas primeiro para que uma execucao parcial continue
# sendo util quando as constraints forem ativadas antes de todo o dataset.
LOAD_ORDER = [
    "attributes",
    "brands",
    "categories",
    "customers",
    "locations",
    "suppliers",
    "employees",
    "products",
    "product_variants",
    "addresses",
    "orders",
    "order_items",
    "payments",
    "fiscal_invoices",
    "product_suppliers",
    "purchase_orders",
    "purchase_order_items",
    "goods_receipts",
    "goods_receipt_items",
    "returns",
    "return_items",
    "stock_levels",
    "stock_movements",
    "variant_attribute_values",
]


def load_dotenv(path):
    """Carrega entradas simples KEY=VALUE sem sobrescrever o ambiente."""
    if not path.exists():
        return

    with path.open(encoding="utf-8") as env_file:
        for raw_line in env_file:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            value = value.strip().strip('"').strip("'")
            os.environ.setdefault(key.strip(), value)


def read_rename_mappings(path):
    """Retorna mapeamentos de colunas de origem para Oracle por tabela."""
    mappings = {}
    with path.open(newline="", encoding="utf-8") as mapping_file:
        reader = csv.DictReader(mapping_file)
        required = {"table_name", "source_column", "oracle_column"}
        if not required.issubset(reader.fieldnames or set()):
            raise ValueError(
                f"{path} precisa conter as colunas: {', '.join(sorted(required))}"
            )

        for row in reader:
            table = row["table_name"].strip()
            source = row["source_column"].strip()
            oracle = row["oracle_column"].strip()
            if not all(IDENTIFIER_RE.fullmatch(value) for value in (table, source, oracle)):
                raise ValueError(f"Mapeamento invalido em {path}: {row}")
            mappings.setdefault(table, {})[source] = oracle
    return mappings


def read_schema_types(path):
    """Le os tipos das colunas no schema Oracle gerado."""
    schema_types = {}
    content = path.read_text(encoding="utf-8")
    for table_match in CREATE_TABLE_RE.finditer(content):
        table_types = {}
        for line in table_match.group("body").splitlines():
            column_match = COLUMN_TYPE_RE.match(line)
            if column_match:
                table_types[column_match.group("column")] = column_match.group("type").upper()
        schema_types[table_match.group("table")] = table_types
    return schema_types


def transform_value(value, column_type):
    """Converte um valor conforme o tipo Oracle da coluna de destino."""
    if value == "":
        return None

    normalized = value.strip().lower()
    if column_type == "NUMBER(1)" and normalized == "true":
        return 1
    if column_type == "NUMBER(1)" and normalized == "false":
        return 0

    if column_type == "DATE":
        for date_format in DATE_FORMATS:
            try:
                return datetime.strptime(value, date_format)
            except ValueError:
                continue
    return value


def transformed_rows(csv_path, source_header, oracle_header, column_types, batch_size):
    with csv_path.open(newline="", encoding="utf-8") as csv_file:
        reader = csv.DictReader(csv_file)
        if reader.fieldnames != source_header:
            raise ValueError(
                f"Header mudou durante a leitura de {csv_path}: {reader.fieldnames}"
            )

        batch = []
        for row in reader:
            batch.append(
                tuple(
                    transform_value(row[source_column], column_types[target_column])
                    for source_column, target_column in zip(source_header, oracle_header)
                )
            )
            if len(batch) >= batch_size:
                yield batch
                batch = []
        if batch:
            yield batch


def load_table(connection, csv_path, rename_mapping, schema_types, batch_size):
    table_name = csv_path.stem
    if not IDENTIFIER_RE.fullmatch(table_name):
        raise ValueError(f"Nome de tabela invalido: {table_name}")

    with csv_path.open(newline="", encoding="utf-8") as csv_file:
        source_header = next(csv.reader(csv_file), None)
    if not source_header:
        raise ValueError(f"CSV sem header: {csv_path}")

    oracle_header = [rename_mapping.get(column, column) for column in source_header]
    if not all(IDENTIFIER_RE.fullmatch(column) for column in oracle_header):
        raise ValueError(f"Nome de coluna invalido em {csv_path}: {oracle_header}")
    if len(set(oracle_header)) != len(oracle_header):
        raise ValueError(f"Colunas duplicadas apos renomeacao em {csv_path}: {oracle_header}")
    column_types = schema_types.get(table_name, {})
    missing_types = set(oracle_header) - set(column_types)
    if missing_types:
        raise ValueError(
            f"Colunas ausentes no schema gerado para {table_name}: {sorted(missing_types)}"
        )

    placeholders = ", ".join(f":{index}" for index in range(1, len(oracle_header) + 1))
    statement = (
        f"INSERT INTO {table_name} ({', '.join(oracle_header)}) "
        f"VALUES ({placeholders})"
    )

    rows_loaded = 0
    started_at = time.perf_counter()
    cursor = connection.cursor()
    try:
        for batch in transformed_rows(
            csv_path, source_header, oracle_header, column_types, batch_size
        ):
            cursor.executemany(statement, batch)
            rows_loaded += len(batch)
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        cursor.close()

    elapsed = time.perf_counter() - started_at
    logger.info("%s: %d linhas carregadas em %.2fs", table_name, rows_loaded, elapsed)
    return rows_loaded


def ordered_csv_paths(data_dir):
    csv_paths = {path.stem: path for path in data_dir.glob("*.csv")}
    ordered_names = [name for name in LOAD_ORDER if name in csv_paths]
    ordered_names.extend(sorted(set(csv_paths) - set(ordered_names)))
    return [csv_paths[name] for name in ordered_names]


def parse_args():
    project_dir = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, default=project_dir / ".env")
    parser.add_argument("--data-dir", type=Path, default=project_dir / "data" / "raw")
    parser.add_argument(
        "--mapping-file",
        type=Path,
        default=project_dir / "sql" / "oracle" / "column_renames.csv",
    )
    parser.add_argument(
        "--schema-file",
        type=Path,
        default=project_dir / "sql" / "oracle" / "02_generated_schema.sql",
    )
    parser.add_argument("--batch-size", type=int, default=5000)
    parser.add_argument("--table", action="append", help="Carrega somente esta tabela; repetivel")
    return parser.parse_args()


def main():
    args = parse_args()
    if args.batch_size < 1:
        raise ValueError("--batch-size precisa ser maior que zero")

    load_dotenv(args.env_file)
    missing = [name for name in ("ORACLE_USER", "ORACLE_PASSWORD", "ORACLE_DSN") if not os.getenv(name)]
    if missing:
        raise RuntimeError(f"Variaveis ausentes no ambiente/.env: {', '.join(missing)}")

    try:
        import oracledb
    except ImportError as error:
        raise RuntimeError("Instale o driver com: python -m pip install oracledb") from error

    mappings = read_rename_mappings(args.mapping_file)
    schema_types = read_schema_types(args.schema_file)
    paths = ordered_csv_paths(args.data_dir)
    if args.table:
        requested = set(args.table)
        paths = [path for path in paths if path.stem in requested]
        missing_tables = requested - {path.stem for path in paths}
        if missing_tables:
            raise FileNotFoundError(f"Tabelas sem CSV: {', '.join(sorted(missing_tables))}")

    logger.info("Iniciando carga de %d tabelas", len(paths))
    connection = oracledb.connect(
        user=os.environ["ORACLE_USER"],
        password=os.environ["ORACLE_PASSWORD"],
        dsn=os.environ["ORACLE_DSN"],
    )
    loaded_tables = []
    current_table = None
    try:
        for csv_path in paths:
            current_table = csv_path.stem
            load_table(
                connection,
                csv_path,
                mappings.get(current_table, {}),
                schema_types,
                args.batch_size,
            )
            loaded_tables.append(current_table)
    except Exception:
        logger.exception(
            "Falha ao carregar a tabela '%s'. Tabelas concluidas nesta execucao: %d (%s)",
            current_table,
            len(loaded_tables),
            ", ".join(loaded_tables) if loaded_tables else "nenhuma",
        )
        raise
    finally:
        connection.close()
    logger.info("Carga concluida")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        main()
    except (FileNotFoundError, RuntimeError, ValueError) as error:
        logger.error("%s", error)
        sys.exit(1)