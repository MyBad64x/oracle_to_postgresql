"""Mede estrategias de leitura Oracle sem materializar lotes desnecessarios."""

import argparse
import logging
import os
import sys
import time
import tracemalloc
from pathlib import Path


logger = logging.getLogger(__name__)


def load_dotenv(path):
	"""Carrega variaveis simples do arquivo .env sem sobrescrever o ambiente."""
	if not path.exists():
		return
	with path.open(encoding="utf-8") as env_file:
		for raw_line in env_file:
			line = raw_line.strip()
			if not line or line.startswith("#") or "=" not in line:
				continue
			key, value = line.split("=", 1)
			os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def parse_args():
	project_dir = Path(__file__).resolve().parents[2]
	parser = argparse.ArgumentParser(description=__doc__)
	parser.add_argument("--env-file", type=Path, default=project_dir / ".env")
	parser.add_argument("--table", default="order_items")
	parser.add_argument("--batch-size", type=int, default=5000)
	parser.add_argument(
		"--arraysizes",
		type=int,
		nargs="+",
		default=[100, 1000, 5000],
		help="Valores de cursor.arraysize a comparar",
	)
	return parser.parse_args()


def validate_identifier(value):
	"""Evita interpolar nomes de tabela arbitrarios no SQL."""
	if not value.replace("_", "").isalnum() or not value[0].isalpha():
		raise ValueError(f"Nome de tabela invalido: {value}")
	return value.upper()


def measure_fetchall(connection, table_name, arraysize):
	"""Busca todas as linhas e mantem a lista, mostrando o custo de materializacao."""
	cursor = connection.cursor()
	cursor.arraysize = arraysize
	tracemalloc.start()
	started_at = time.perf_counter()
	cursor.execute(f"SELECT * FROM {table_name}")
	rows = cursor.fetchall()
	elapsed = time.perf_counter() - started_at
	_, peak_bytes = tracemalloc.get_traced_memory()
	tracemalloc.stop()
	cursor.close()
	row_count = len(rows)
	del rows
	return {
		"estrategia": "fetchall",
		"arraysize": arraysize,
		"batch_size": None,
		"linhas": row_count,
		"segundos": elapsed,
		"pico_mb": peak_bytes / 1024 / 1024,
	}


def measure_fetchmany(connection, table_name, arraysize, batch_size):
	"""Processa lotes e descarta cada lote antes de buscar o proximo."""
	cursor = connection.cursor()
	cursor.arraysize = arraysize
	tracemalloc.start()
	started_at = time.perf_counter()
	cursor.execute(f"SELECT * FROM {table_name}")
	row_count = 0
	while True:
		batch = cursor.fetchmany(batch_size)
		if not batch:
			break
		row_count += len(batch)
		del batch
	elapsed = time.perf_counter() - started_at
	_, peak_bytes = tracemalloc.get_traced_memory()
	tracemalloc.stop()
	cursor.close()
	return {
		"estrategia": "fetchmany",
		"arraysize": arraysize,
		"batch_size": batch_size,
		"linhas": row_count,
		"segundos": elapsed,
		"pico_mb": peak_bytes / 1024 / 1024,
	}


def run_experiment(connection, table_name, batch_size, arraysizes):
	results = []
	for arraysize in arraysizes:
		results.append(measure_fetchall(connection, table_name, arraysize))
		results.append(measure_fetchmany(connection, table_name, arraysize, batch_size))
	return results


def print_results(results, table_name, batch_size, version, thin_mode):
	print(f"oracledb: {version}")
	print(f"modo thin: {thin_mode}")
	print(f"tabela: {table_name}")
	print(f"batch fetchmany: {batch_size}")
	print()
	print("estrategia | arraysize | linhas | segundos | pico_memoria_mb")
	print("--- | ---: | ---: | ---: | ---:")
	for result in results:
		print(
			f"{result['estrategia']} | {result['arraysize']} | {result['linhas']} | "
			f"{result['segundos']:.4f} | {result['pico_mb']:.2f}"
		)


def main():
	args = parse_args()
	if args.batch_size < 1 or any(arraysize < 1 for arraysize in args.arraysizes):
		raise ValueError("batch-size e arraysizes precisam ser maiores que zero")
	load_dotenv(args.env_file)
	missing = [name for name in ("ORACLE_USER", "ORACLE_PASSWORD", "ORACLE_DSN") if not os.getenv(name)]
	if missing:
		raise RuntimeError(f"Variaveis ausentes no ambiente/.env: {', '.join(missing)}")

	try:
		import oracledb
	except ImportError as error:
		raise RuntimeError("Instale o driver com: python -m pip install oracledb") from error

	version = oracledb.__version__
	thin_mode = oracledb.is_thin_mode()
	table_name = validate_identifier(args.table)
	connection = oracledb.connect(
		user=os.environ["ORACLE_USER"],
		password=os.environ["ORACLE_PASSWORD"],
		dsn=os.environ["ORACLE_DSN"],
	)
	try:
		results = run_experiment(connection, table_name, args.batch_size, args.arraysizes)
	finally:
		connection.close()

	print_results(results, table_name, args.batch_size, version, thin_mode)


if __name__ == "__main__":
	try:
		main()
	except (RuntimeError, ValueError, OSError) as error:
		logger.error("%s", error)
		sys.exit(1)
