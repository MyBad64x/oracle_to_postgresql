"""Gera DDL PostgreSQL para as chaves estrangeiras de um schema Oracle."""

import argparse
import logging
import os
import sys
from pathlib import Path


logger = logging.getLogger(__name__)


FK_SQL = """
SELECT c.table_name AS child_table,
       rc.table_name AS parent_table,
       c.constraint_name,
    c.delete_rule,
    c.status,
    c.validated,
       LISTAGG(cc.column_name, ', ') WITHIN GROUP (ORDER BY cc.position) AS child_columns,
       LISTAGG(rcc.column_name, ', ') WITHIN GROUP (ORDER BY rcc.position) AS parent_columns
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
 GROUP BY c.table_name, rc.table_name, c.constraint_name,
          c.delete_rule, c.status, c.validated
 ORDER BY c.table_name, c.constraint_name
"""


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


def validate_identifier(value, label):
    """Valida nomes do dicionario antes de gerar SQL sem aspas."""
    if not value or not value[0].isalpha() or not value.replace("_", "").isalnum():
        raise ValueError(f"{label} invalido: {value}")
    if len(value) > 63:
        raise ValueError(f"{label} excede o limite PostgreSQL de 63 caracteres: {value}")
    return value.lower()


def parse_args():
    project_dir = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, default=project_dir / ".env")
    parser.add_argument("--owner", help="Schema Oracle; padrao: usuario da conexao")
    parser.add_argument(
        "--table",
        action="append",
        dest="tables",
        help="Tabela no escopo da migracao; repetivel. Sem --table, inclui todas.",
    )
    parser.add_argument("--output", type=Path, help="Arquivo SQL; sem ele imprime no terminal")
    return parser.parse_args()


def fetch_foreign_keys(connection, owner):
    cursor = connection.cursor()
    try:
        cursor.execute(FK_SQL, {"owner": owner.upper()})
        columns = [description[0].lower() for description in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]
    finally:
        cursor.close()


def filter_scope(foreign_keys, tables):
    if not tables:
        return foreign_keys
    scope = {table.lower() for table in tables}
    return [
        foreign_key
        for foreign_key in foreign_keys
        if foreign_key["child_table"].lower() in scope
        and foreign_key["parent_table"].lower() in scope
    ]


def render_fk(foreign_key):
    child_table = validate_identifier(foreign_key["child_table"], "Tabela filha")
    parent_table = validate_identifier(foreign_key["parent_table"], "Tabela pai")
    constraint_name = validate_identifier(foreign_key["constraint_name"], "Constraint")
    child_columns = ", ".join(
        validate_identifier(column.strip(), "Coluna filha")
        for column in foreign_key["child_columns"].split(",")
    )
    parent_columns = ", ".join(
        validate_identifier(column.strip(), "Coluna pai")
        for column in foreign_key["parent_columns"].split(",")
    )
    delete_rule = foreign_key["delete_rule"]
    delete_suffixes = {
        "NO ACTION": "",
        "CASCADE": " ON DELETE CASCADE",
        "SET NULL": " ON DELETE SET NULL",
    }
    if delete_rule not in delete_suffixes:
        raise ValueError(
            f"DELETE_RULE desconhecido para {foreign_key['constraint_name']}: {delete_rule}"
        )
    suffix = delete_suffixes[delete_rule]
    statement = (
        f"ALTER TABLE {child_table} ADD CONSTRAINT {constraint_name} "
        f"FOREIGN KEY ({child_columns}) REFERENCES {parent_table} ({parent_columns}){suffix};"
    )
    if foreign_key["status"] == "DISABLED":
        return f"-- DESABILITADA NA ORIGEM: {statement}"
    if foreign_key["status"] != "ENABLED":
        raise ValueError(
            f"STATUS desconhecido para {foreign_key['constraint_name']}: {foreign_key['status']}"
        )
    if foreign_key["validated"] == "NOT VALIDATED":
        return f"{statement[:-1]} NOT VALID;"
    if foreign_key["validated"] != "VALIDATED":
        raise ValueError(
            f"VALIDATED desconhecido para {foreign_key['constraint_name']}: {foreign_key['validated']}"
        )
    return statement


def render_document(owner, foreign_keys, tables):
    scope_text = ", ".join(sorted(table.lower() for table in tables)) if tables else "todas as tabelas"
    disabled_count = sum(foreign_key["status"] == "DISABLED" for foreign_key in foreign_keys)
    not_valid_count = sum(
        foreign_key["status"] == "ENABLED" and foreign_key["validated"] == "NOT VALIDATED"
        for foreign_key in foreign_keys
    )
    normal_count = len(foreign_keys) - disabled_count - not_valid_count
    header = (
        "-- DDL PostgreSQL gerado a partir das FKs do Oracle\n"
        f"-- Owner Oracle: {owner.upper()}\n"
        f"-- Escopo: {scope_text}\n"
        f"-- FKs normais: {normal_count}\n"
        f"-- FKs NOT VALID: {not_valid_count}\n"
        f"-- FKs desabilitadas na origem: {disabled_count}\n\n"
    )
    return header + "\n".join(render_fk(foreign_key) for foreign_key in foreign_keys) + "\n"


def main():
    args = parse_args()
    project_dir = Path(__file__).resolve().parents[2]
    load_dotenv(args.env_file)
    missing = [name for name in ("ORACLE_USER", "ORACLE_PASSWORD", "ORACLE_DSN") if not os.getenv(name)]
    if missing:
        raise RuntimeError(f"Variaveis ausentes no ambiente/.env: {', '.join(missing)}")

    try:
        import oracledb
    except ImportError as error:
        raise RuntimeError("Instale o driver com: python -m pip install oracledb") from error

    owner = (args.owner or os.environ["ORACLE_USER"]).upper()
    validate_identifier(owner, "Owner")
    tables = [validate_identifier(table, "Tabela") for table in (args.tables or [])]
    connection = oracledb.connect(
        user=os.environ["ORACLE_USER"],
        password=os.environ["ORACLE_PASSWORD"],
        dsn=os.environ["ORACLE_DSN"],
    )
    try:
        foreign_keys = filter_scope(fetch_foreign_keys(connection, owner), tables)
    finally:
        connection.close()

    document = render_document(owner, foreign_keys, tables)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(document, encoding="utf-8")
        print(args.output)
    else:
        print(document, end="")
    logger.info("%d FK(s) gerada(s)", len(foreign_keys))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    try:
        main()
    except (RuntimeError, ValueError, OSError) as error:
        logger.error("%s", error)
        sys.exit(1)