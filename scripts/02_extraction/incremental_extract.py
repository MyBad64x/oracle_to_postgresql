"""Executa cargas full e incrementais de uma tabela Oracle por data de alteracao.

O marcador e salvo em JSON somente depois que a extracao termina. A janela
incremental possui sobreposicao para proteger contra transacoes longas; por
isso o destino precisa ser idempotente, normalmente via MERGE/upsert.
"""

import argparse
import json
import logging
import os
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

from extract_table import (
    CsvSink,
    ParquetSink,
    load_dotenv,
    validate_identifier,
)


logger = logging.getLogger(__name__)


def parse_args():
    project_dir = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, default=project_dir / ".env")
    parser.add_argument("--table", required=True)
    parser.add_argument("--updated-column", default="updated_at")
    parser.add_argument("--mode", choices=("full", "incremental"), required=True)
    parser.add_argument("--state-file", type=Path, default=project_dir / "data" / "extracted" / "incremental_state.json")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--format", choices=("csv", "parquet"), default="parquet")
    parser.add_argument("--batch-size", type=int, default=5000)
    parser.add_argument("--arraysize", type=int, default=5000)
    parser.add_argument(
        "--overlap-minutes",
        type=int,
        default=5,
        help="Minutos subtraidos do marcador no modo incremental",
    )
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


def read_state(path):
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as state_file:
        state = json.load(state_file)
    if not isinstance(state, dict):
        raise ValueError(f"Estado incremental invalido: {path}")
    return state


def write_state(path, state):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, delete=False
        ) as state_file:
            json.dump(state, state_file, indent=2, ensure_ascii=False)
            state_file.write("\n")
            temporary_path = Path(state_file.name)
        temporary_path.replace(path)
        temporary_path = None
    finally:
        if temporary_path and temporary_path.exists():
            temporary_path.unlink()


def parse_marker(state, table_name):
    value = state.get(table_name, {}).get("last_value")
    if value is None:
        return None
    try:
        return datetime.fromisoformat(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"Marcador invalido para {table_name}: {value}") from error


def count_future_rows(cursor, table_name, updated_column):
    cursor.execute(
        f"SELECT COUNT(*) FROM {table_name} WHERE {updated_column} > SYSDATE"
    )
    return cursor.fetchone()[0]


def extract_window(connection, table_name, updated_column, lower_bound, batch_size, arraysize, sink):
    where = f"{updated_column} <= SYSDATE"
    binds = {}
    if lower_bound is not None:
        where += f" AND {updated_column} > :lower_bound"
        binds["lower_bound"] = lower_bound

    cursor = connection.cursor()
    cursor.arraysize = arraysize
    total_rows = 0
    marker = lower_bound
    try:
        cursor.execute(
            f"SELECT * FROM {table_name} WHERE {where} ORDER BY {updated_column}",
            binds,
        )
        descriptions = cursor.description
        column_names = [description[0].lower() for description in descriptions]
        updated_index = column_names.index(updated_column.lower())
        rows = cursor.fetchmany(batch_size)
        while rows:
            sink.write(column_names, descriptions, rows)
            total_rows += len(rows)
            batch_max = max(
                (row[updated_index] for row in rows if row[updated_index] is not None),
                default=None,
            )
            if batch_max is not None and (marker is None or batch_max > marker):
                marker = batch_max
            logger.info("%s: %d linhas extraidas", table_name, total_rows)
            rows = cursor.fetchmany(batch_size)
    finally:
        cursor.close()
    return total_rows, marker


def main():
    args = parse_args()
    if args.batch_size < 1 or args.arraysize < 1 or args.overlap_minutes < 0:
        raise ValueError("batch-size e arraysize devem ser positivos; overlap nao pode ser negativo")

    table_name = validate_identifier(args.table, "Tabela")
    updated_column = validate_identifier(args.updated_column, "Coluna de controle")
    state = read_state(args.state_file)
    previous_marker = parse_marker(state, table_name)
    if args.mode == "incremental" and previous_marker is None:
        raise ValueError(
            f"Nao existe marcador para {table_name}; execute primeiro com --mode full"
        )
    lower_bound = (
        previous_marker - timedelta(minutes=args.overlap_minutes)
        if args.mode == "incremental"
        else None
    )

    oracledb = load_oracledb(args.env_file)
    connection = oracledb.connect(
        user=os.environ["ORACLE_USER"],
        password=os.environ["ORACLE_PASSWORD"],
        dsn=os.environ["ORACLE_DSN"],
    )
    sink = None
    try:
        cursor = connection.cursor()
        future_rows = count_future_rows(cursor, table_name, updated_column)
        logger.warning(
            "%s: %d registro(s) com %s > SYSDATE ficaram fora da janela",
            table_name,
            future_rows,
            updated_column,
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        sink = CsvSink(args.output) if args.format == "csv" else ParquetSink(args.output)
        total_rows, new_marker = extract_window(
            connection,
            table_name,
            updated_column,
            lower_bound,
            args.batch_size,
            args.arraysize,
            sink,
        )
    finally:
        if sink is not None:
            sink.close()
        connection.close()

    if new_marker is None:
        new_marker = previous_marker
    execution_time = datetime.now().astimezone()
    state[table_name] = {
        "last_value": new_marker.isoformat(sep=" ") if new_marker else None,
        "executed_at": execution_time.isoformat(),
        "mode": args.mode,
        "rows_extracted": total_rows,
        "future_rows_excluded": future_rows,
        "overlap_minutes": args.overlap_minutes,
    }
    write_state(args.state_file, state)
    logger.info(
        "Carga %s concluida: %d linhas; marcador=%s; estado=%s",
        args.mode,
        total_rows,
        new_marker,
        args.state_file,
    )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        main()
    except (RuntimeError, ValueError, OSError, json.JSONDecodeError) as error:
        logger.error("%s", error)
        sys.exit(1)