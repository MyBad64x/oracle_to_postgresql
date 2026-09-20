"""Gera um inventario somente-leitura de um schema Oracle em Markdown.

O script diagnostica o schema, mas nao altera tabelas, constraints, indices,
comentarios ou estatisticas. Essa separacao e intencional: inventario informa;
qualquer correcao deve ser revisada e aplicada por um DBA.
"""

import argparse
import logging
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path


logger = logging.getLogger(__name__)
IDENTIFIER_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_$#]*$")


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
			os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def parse_args():
	project_dir = Path(__file__).resolve().parents[2]
	parser = argparse.ArgumentParser(description=__doc__)
	parser.add_argument("--env-file", type=Path, default=project_dir / ".env")
	parser.add_argument("--owner", help="Schema a inventariar; padrao: usuario da conexao")
	parser.add_argument("--output-dir", type=Path, default=project_dir / "docs")
	parser.add_argument(
		"--stale-days",
		type=int,
		default=30,
		help="Considera estatistica antiga depois deste numero de dias",
	)
	return parser.parse_args()


def require_identifier(value, label):
	value = value.strip().upper()
	if not IDENTIFIER_RE.fullmatch(value):
		raise ValueError(f"{label} invalido: {value}")
	return value


def rows_as_dicts(cursor, sql, binds):
	"""Executa uma consulta e transforma cada linha em um dicionario."""
	cursor.execute(sql, binds)
	columns = [description[0].lower() for description in cursor.description]
	return [dict(zip(columns, row)) for row in cursor.fetchall()]


def query_inventory(cursor, owner, stale_days):
	"""Coleta metadados do owner sem executar COUNT(*) nas tabelas.

	NUM_ROWS e LAST_ANALYZED sao estatisticas coletadas pelo Oracle, nao uma
	contagem em tempo real. Por isso o relatorio marca quando a informacao esta
	nula ou mais antiga que ``stale_days``.
	"""
	inventory = {}
	# ALL_* permite consultar outro owner quando o usuario possui privilegio.
	# USER_SEGMENTS e o fallback para ambientes em que ALL_SEGMENTS e restrito.
	tables_sql = """
		SELECT t.table_name,
			   t.num_rows,
			   ROUND(NVL(s.bytes, 0) / 1024 / 1024, 2) AS mb,
			   (SELECT COUNT(*)
				  FROM all_tab_columns c
				 WHERE c.owner = t.owner
				   AND c.table_name = t.table_name) AS colunas,
			   t.last_analyzed,
			   CASE
				   WHEN t.last_analyzed IS NULL THEN 'NUNCA_ANALISADA'
				   WHEN t.last_analyzed < SYSDATE - :stale_days THEN 'DESATUALIZADA'
				   ELSE 'ATUAL'
			   END AS status_estatistica
		  FROM all_tables t
		  LEFT JOIN all_segments s
			ON s.owner = t.owner
		   AND s.segment_name = t.table_name
		   AND s.segment_type = 'TABLE'
		 WHERE t.owner = :owner
		 ORDER BY t.num_rows DESC NULLS LAST, t.table_name
		"""
	try:
		inventory["tables"] = rows_as_dicts(
			cursor,
			tables_sql,
			{"owner": owner, "stale_days": stale_days},
		)
	except Exception as error:
		if "ORA-00942" not in str(error):
			raise
		logger.warning(
			"ALL_SEGMENTS indisponivel; tentando USER_SEGMENTS para o schema atual"
		)
		inventory["tables"] = rows_as_dicts(
			cursor,
			"""
			SELECT t.table_name,
				   t.num_rows,
				   ROUND(NVL(s.bytes, 0) / 1024 / 1024, 2) AS mb,
				   (SELECT COUNT(*)
					  FROM all_tab_columns c
					 WHERE c.owner = t.owner
					   AND c.table_name = t.table_name) AS colunas,
				   t.last_analyzed,
				   CASE
					   WHEN t.last_analyzed IS NULL THEN 'NUNCA_ANALISADA'
					   WHEN t.last_analyzed < SYSDATE - :stale_days THEN 'DESATUALIZADA'
					   ELSE 'ATUAL'
				   END AS status_estatistica
							FROM all_tables t
							LEFT JOIN user_segments s
								ON s.segment_name = t.table_name
							 AND s.segment_type = 'TABLE'
			 WHERE t.owner = :owner
			 ORDER BY t.num_rows DESC NULLS LAST, t.table_name
			""",
			{"owner": owner, "stale_days": stale_days},
		)
	inventory["columns"] = rows_as_dicts(
		cursor,
		"""
		SELECT c.table_name,
			   c.column_name,
			   c.data_type,
			   c.data_length,
			   c.data_precision,
			   c.data_scale,
			   c.nullable,
			   CASE
				   WHEN c.data_type = 'NUMBER' AND c.data_precision IS NULL
				   THEN 'NUMBER_SEM_PRECISAO'
				   ELSE NULL
			   END AS diagnostico,
			   cc.comments
		  FROM all_tab_columns c
		  LEFT JOIN all_col_comments cc
			ON cc.owner = c.owner
		   AND cc.table_name = c.table_name
		   AND cc.column_name = c.column_name
		 WHERE c.owner = :owner
		 ORDER BY c.table_name, c.column_id
		""",
		{"owner": owner},
	)
	inventory["foreign_keys"] = rows_as_dicts(
		cursor,
		"""
		SELECT c.table_name AS tabela_filha,
			   cc.column_name AS coluna_fk,
			   rc.table_name AS tabela_pai,
			   rcc.column_name AS coluna_pai,
			   c.constraint_name,
			   cc.position
		  FROM all_constraints c
		  JOIN all_cons_columns cc
			ON cc.owner = c.owner
		   AND cc.constraint_name = c.constraint_name
		   AND cc.table_name = c.table_name
		  JOIN all_constraints rc
			ON rc.owner = c.r_owner
		   AND rc.constraint_name = c.r_constraint_name
		  JOIN all_cons_columns rcc
			ON rcc.owner = rc.owner
		   AND rcc.constraint_name = rc.constraint_name
		   AND rcc.table_name = rc.table_name
		   AND rcc.position = cc.position
		 WHERE c.owner = :owner
		   AND c.constraint_type = 'R'
		 ORDER BY c.table_name, c.constraint_name, cc.position
		""",
		{"owner": owner},
	)
	inventory["missing_fk_indexes"] = rows_as_dicts(
		cursor,
		"""
		SELECT c.table_name, c.constraint_name,
			   LISTAGG(cc.column_name, ', ') WITHIN GROUP (ORDER BY cc.position) AS columns
		  FROM all_constraints c
		  JOIN all_cons_columns cc
			ON cc.owner = c.owner
		   AND cc.constraint_name = c.constraint_name
		   AND cc.table_name = c.table_name
		 WHERE c.owner = :owner
		   AND c.constraint_type = 'R'
		   AND NOT EXISTS (
			   SELECT 1
				 FROM all_indexes i
				 JOIN all_ind_columns ic
				   ON ic.index_owner = i.owner
				  AND ic.index_name = i.index_name
				WHERE i.table_owner = c.owner
				  AND i.table_name = c.table_name
				  AND ic.column_position = cc.position
				  AND ic.column_name = cc.column_name
				  AND NOT EXISTS (
					  SELECT 1
						FROM all_ind_columns earlier
					   WHERE earlier.index_owner = ic.index_owner
						 AND earlier.index_name = ic.index_name
						 AND earlier.column_position < ic.column_position
						 AND earlier.column_position = cc.position
				  )
		   )
		 GROUP BY c.table_name, c.constraint_name
		 ORDER BY c.table_name, c.constraint_name
		""",
		{"owner": owner},
	)
	inventory["tables_without_pk"] = rows_as_dicts(
		cursor,
		"""
		SELECT t.table_name
		  FROM all_tables t
		 WHERE t.owner = :owner
		   AND NOT EXISTS (
			   SELECT 1
				 FROM all_constraints c
				WHERE c.owner = t.owner
				  AND c.table_name = t.table_name
				  AND c.constraint_type = 'P'
		   )
		 ORDER BY t.table_name
		""",
		{"owner": owner},
	)
	inventory["stale_tables"] = [
		row for row in inventory["tables"] if row["status_estatistica"] != "ATUAL"
	]
	inventory["uncommented_columns"] = [
		row for row in inventory["columns"] if row["comments"] is None
	]
	inventory["nullable_columns"] = [
		row for row in inventory["columns"] if row["nullable"] == "Y"
	]
	return inventory


def format_value(value):
	if value is None:
		return ""
	if isinstance(value, datetime):
		return value.strftime("%Y-%m-%d %H:%M:%S")
	return str(value).replace("|", "\\|").replace("\n", " ")


def markdown_table(headers, rows):
	"""Renderiza uma lista de dicionarios como tabela Markdown."""
	lines = [
		"| " + " | ".join(headers) + " |",
		"| " + " | ".join("---" for _ in headers) + " |",
	]
	lines.extend(
		"| " + " | ".join(format_value(row.get(key)) for key in keys) + " |"
		for keys, row in rows
	)
	return "\n".join(lines) if rows else "_Nenhum registro._"


def build_report(owner, inventory, generated_at):
	tables = inventory["tables"]
	columns = inventory["columns"]
	foreign_keys = inventory["foreign_keys"]
	number_without_precision = [
		row for row in columns if row["diagnostico"] == "NUMBER_SEM_PRECISAO"
	]
	return f"""# Inventário Oracle: {owner}

Gerado em: `{generated_at}`  
Parâmetro de estatística antiga: `{inventory['stale_days']} dias`

## Resumo

- Tabelas: **{len(tables)}**
- Colunas: **{len(columns)}**
- Chaves estrangeiras: **{len(foreign_keys)}**
- Tabelas sem chave primária: **{len(inventory['tables_without_pk'])}**
- FKs sem índice adequado: **{len(inventory['missing_fk_indexes'])}**
- Tabelas com estatística nula ou antiga: **{len(inventory['stale_tables'])}**
- Colunas sem comentário: **{len(inventory['uncommented_columns'])}**
- Colunas nullable: **{len(inventory['nullable_columns'])}**
- Colunas `NUMBER` sem precisão: **{len(number_without_precision)}**

## Como ler este relatório

- **Owner** é o schema Oracle inventariado. O script usa as views `ALL_*` para
	permitir outro owner quando o usuário possui privilégio; sem esse privilégio,
	algumas informações podem exigir acesso de DBA.
- **NUM_ROWS** é a estimativa de linhas registrada nas estatísticas do Oracle,
	não uma contagem feita pelo script. **LAST_ANALYZED** informa quando essa
	estimativa foi coletada. Estatística nula ou antiga pode levar o otimizador a
	escolher um plano de execução ruim.
- **MB** é o espaço ocupado pelo segmento da tabela. O tamanho não inclui
	necessariamente índices, LOBs ou outros segmentos associados.
- **PK** (chave primária) identifica unicamente cada linha. **FK** (chave
	estrangeira) liga uma tabela filha a uma tabela pai e revela parte do modelo
	de negócio.
- **Índice de FK** é importante para reduzir bloqueios na tabela pai durante
	`UPDATE` ou `DELETE`. O diagnóstico sinaliza relações sem índice adequado;
	ele não cria índices automaticamente.
- **Nullable** indica que a coluna aceita `NULL`. Isso pode ser uma decisão de
	negócio ou uma pendência de modelagem; o inventário não transforma `NULL`
	em `NOT NULL`.
- **NUMBER sem precisão** significa que o Oracle não limita explicitamente a
	precisão da coluna. Em uma migração, essa informação exige decisão de tipo,
	escala e faixa de valores.
- **Coluna sem comentário** existe tecnicamente, mas não possui documentação
	no dicionário Oracle. O diagnóstico é uma oportunidade de documentação.

## Alertas de modelagem observados

- **Compatibilidade de identificadores:** Oracle 11g e anteriores limita nomes
	a 30 caracteres; versões mais novas aceitam mais. Constraints como
	`FK_VARIANT_ATTRIBUTE_VALUES_ATTRIBUTES` ultrapassam esse limite e precisam
	de uma convenção curta antes de migrar para uma versão antiga.
- **Quantidade com tipos diferentes:** `QUANTITY` aparece como inteiro em
	algumas tabelas e decimal em outras. A padronização deve ser decidida na
	modelagem dimensional, especialmente para estoque, devoluções e recebimentos.
- **NOT NULL parcial:** colunas nullable podem representar campos opcionais,
	mas também débitos conhecidos de integridade. O relatório deve ser lido junto
	com as decisões registradas no script de constraints.
- **Comentários ausentes:** adicionar comentários de negócio em colunas como
	`ORDERS.SALESPERSON_ID` torna o schema mais compreensível para quem chegar
	depois, sem alterar o dado armazenado.

## Resumo por tabela

{markdown_table(
	['Tabela', 'Linhas', 'MB', 'Colunas', 'Última análise', 'Status'],
	[
		(['table_name', 'num_rows', 'mb', 'colunas', 'last_analyzed', 'status_estatistica'], row)
		for row in tables
	],
)}

## Colunas

{markdown_table(
	['Tabela', 'Coluna', 'Tipo', 'Precisão', 'Escala', 'Nulo?', 'Diagnóstico', 'Comentário'],
	[
		(['table_name', 'column_name', 'data_type', 'data_precision', 'data_scale', 'nullable', 'diagnostico', 'comments'], row)
		for row in columns
	],
)}

## Grafo de relacionamentos

{markdown_table(
	['Tabela filha', 'Coluna FK', 'Tabela pai', 'Coluna pai', 'Constraint'],
	[
		(['tabela_filha', 'coluna_fk', 'tabela_pai', 'coluna_pai', 'constraint_name'], row)
		for row in foreign_keys
	],
)}

## Diagnósticos

### FKs sem índice adequado

{markdown_table(
	['Tabela', 'Constraint', 'Colunas'],
	[(['table_name', 'constraint_name', 'columns'], row) for row in inventory['missing_fk_indexes']],
)}

### Tabelas sem chave primária

{markdown_table(
	['Tabela'],
	[(['table_name'], row) for row in inventory['tables_without_pk']],
)}

### Estatísticas nulas ou antigas

{markdown_table(
	['Tabela', 'Última análise', 'Status'],
	[(['table_name', 'last_analyzed', 'status_estatistica'], row) for row in inventory['stale_tables']],
)}

### Colunas sem comentário

{markdown_table(
	['Tabela', 'Coluna', 'Tipo'],
	[(['table_name', 'column_name', 'data_type'], row) for row in inventory['uncommented_columns']],
)}
"""


def main():
	args = parse_args()
	if args.stale_days < 0:
		raise ValueError("--stale-days precisa ser maior ou igual a zero")

	project_dir = Path(__file__).resolve().parents[2]
	load_dotenv(args.env_file)
	missing = [name for name in ("ORACLE_USER", "ORACLE_PASSWORD", "ORACLE_DSN") if not os.getenv(name)]
	if missing:
		raise RuntimeError(f"Variaveis ausentes no ambiente/.env: {', '.join(missing)}")

	try:
		import oracledb
	except ImportError as error:
		raise RuntimeError("Instale o driver com: python -m pip install oracledb") from error

	connection = oracledb.connect(
		user=os.environ["ORACLE_USER"],
		password=os.environ["ORACLE_PASSWORD"],
		dsn=os.environ["ORACLE_DSN"],
	)
	try:
		cursor = connection.cursor()
		owner = require_identifier(args.owner or os.environ["ORACLE_USER"], "Owner")
		inventory = query_inventory(cursor, owner, args.stale_days)
		inventory["stale_days"] = args.stale_days
	finally:
		connection.close()

	generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
	args.output_dir.mkdir(parents=True, exist_ok=True)
	output_path = args.output_dir / f"inventario_{owner.lower()}_{datetime.now().strftime('%Y%m%d')}.md"
	output_path.write_text(build_report(owner, inventory, generated_at), encoding="utf-8")
	logger.info("Inventario salvo em %s", output_path)
	print(output_path)


if __name__ == "__main__":
	logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
	try:
		main()
	except (RuntimeError, ValueError, OSError) as error:
		logger.error("%s", error)
		sys.exit(1)
