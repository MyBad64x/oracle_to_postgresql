import os
import csv
import logging
import math
from decimal import Decimal, InvalidOperation
from datetime import datetime

# Limitacao conhecida: a inferencia carrega o CSV e sua transposicao inteira
# em memoria. Para tabelas de producao muito grandes, usar streaming ou amostragem.
logger = logging.getLogger(__name__)
rename_mappings = []

ORACLE_RESERVED_WORDS = {
    "number", "date", "level", "size", "order", "group", "user", "comment",
    "access", "session", "mode", "start", "check", "value",
}

# Tenta converter a string para inteiro
# Se sucesso o valor é compatível com INTEGER
def is_int(value):
    try:
        int(value)
        return True
    except ValueError:
        return False

###################################################

# Tenta converter a string para float
# Números decimais e inteiros passam por aqui
def is_float(value):
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False

###################################################

# Tenta converter string para data/hora
# Se algum formato bater então TIMESTAMP
def is_datetime(value):
    formats = ["%Y-%m-%d %H:%M:%S", "%Y-%m-%d"]
    for fmt in formats:
        try:
            datetime.strptime(value, fmt)
            return True
        except ValueError:
            continue
    return False

###################################################

# Descobrindo o que é boolean e o que não é
def is_boolean(values, column_name=""):
    known_text_booleans = {"true", "false", "t", "f"}
    known_numeric_booleans = {"0", "1"}
    unique_values = {str(v).strip().lower() for v in values if v != ""}
    if not unique_values:
        return False
    if unique_values.issubset(known_text_booleans):
        return True

    normalized_name = column_name.strip().lower()
    name_tokens = set(normalized_name.replace("-", "_").split("_"))
    suggests_boolean = (
        normalized_name.startswith(("is_", "has_"))
        or "flag" in name_tokens
        or normalized_name in {"active", "enabled"}
    )
    return suggests_boolean and unique_values.issubset(known_numeric_booleans)

###################################################

def is_document_column(column_name):
    """Identifica texto que pode parecer numérico, mas não deve ser calculado."""
    normalized_name = column_name.strip().lower()
    document_tokens = {"cpf", "cnpj", "phone", "cep", "code", "number"}
    document_id_exceptions = {
        "tax_id", "document_id", "national_id", "barcode_ean", "nfe_access_key",
    }
    name_tokens = set(normalized_name.replace("-", "_").split("_"))

    # Sufixo _id representa chave, que continua sendo inferida como número.
    if normalized_name in document_id_exceptions:
        return True
    if normalized_name == "id" or normalized_name.endswith("_id"):
        return False
    return bool(name_tokens & document_tokens)


def varchar2_length(values):
    """Calcula o tamanho Oracle usando faixas legíveis de crescimento."""
    max_length = max((len(str(value)) for value in values), default=1)
    for size in (2, 5, 10, 20, 50, 100, 200, 500, 1000, 4000):
        if max_length <= size:
            return size
    return None


def varchar2_type(values):
    """Escolhe VARCHAR2 com semântica de caracteres ou CLOB para textos longos."""
    length = varchar2_length(values)
    if length is None:
        return "CLOB"
    return f"VARCHAR2({length} CHAR)"


def number_precision(values):
    """Calcula NUMBER(p,s) preservando a maior escala encontrada."""
    decimals = [Decimal(str(value).strip()) for value in values]
    scale = max(max(0, -decimal.as_tuple().exponent) for decimal in decimals)
    integer_digits = max(
        max(1, len(decimal.as_tuple().digits) + max(decimal.as_tuple().exponent, 0) - scale)
        for decimal in decimals
    )
    precision = integer_digits + 4 + scale
    return f"NUMBER({precision}, {scale})" if scale else f"NUMBER({precision})"


def numeric_values_are_integral(values):
    decimals = [Decimal(str(value).strip()) for value in values]
    return all(decimal == decimal.to_integral_value() for decimal in decimals)


def singular_table_name(table_name):
    normalized_name = table_name.lower()
    if normalized_name.endswith("sses"):
        return normalized_name[:-2]
    if normalized_name.endswith("ies"):
        return normalized_name[:-3] + "y"
    if normalized_name.endswith("s"):
        return normalized_name[:-1]
    return normalized_name


def oracle_column_name(table_name, column_name):
    normalized_name = column_name.strip().lower()
    if normalized_name not in ORACLE_RESERVED_WORDS:
        return column_name
    renamed = f"{singular_table_name(table_name)}_{normalized_name}"
    logger.warning(
        "Coluna '%s.%s' renomeada para '%s' por ser palavra reservada Oracle",
        table_name,
        column_name,
        renamed,
    )
    rename_mappings.append(
        {
            "table_name": table_name,
            "source_column": column_name,
            "oracle_column": renamed,
        }
    )
    return renamed


# Remove valores vazios antes de testar e retorna um tipo Oracle.
def infer_oracle_type(column_name, values):
    not_empty_values = [v for v in values if v != ""]
    # Se não sobrou nenhum valor real, sem evidência de tipo:
    # assume-se VARCHAR2(1) como opção mais segura.
    if not not_empty_values:
        logger.warning("Coluna '%s' está totalmente vazia; usando VARCHAR2(1)", column_name)
        return "VARCHAR2(1 CHAR)"
    if is_document_column(column_name):
        return varchar2_type(not_empty_values)
    if is_boolean(not_empty_values, column_name):
        return "NUMBER(1)"
    if all(is_int(v) for v in not_empty_values):
        max_digits = max(len(str(abs(int(v)))) for v in not_empty_values)
        return "NUMBER(10)" if max_digits <= 10 else "NUMBER(19)"
    if all(is_float(v) for v in not_empty_values):
        try:
            if numeric_values_are_integral(not_empty_values):
                max_digits = max(
                    len(str(abs(int(Decimal(str(value).strip())))))
                    for value in not_empty_values
                )
                return "NUMBER(10)" if max_digits <= 10 else "NUMBER(19)"
            return number_precision(not_empty_values)
        except (InvalidOperation, ValueError):
            return varchar2_type(not_empty_values)
    if all(is_datetime(v) for v in not_empty_values):
        return "DATE"
    return varchar2_type(not_empty_values)


# Alias temporário para manter os exercícios anteriores funcionando.
def infer_type(values):
    return infer_oracle_type("", values)


def generate_create_table(csv_path):
    with open(csv_path, "r", newline="", encoding="utf-8") as file:
        reader = csv.reader(file)
        header = next(reader)
        rows = list(reader)

    columns = [list(column) for column in zip(*rows)] if rows else [[] for _ in header]
    table_name = os.path.splitext(os.path.basename(csv_path))[0]
    column_definitions = [
        f"    {oracle_column_name(table_name, name)} {infer_oracle_type(name, values)}"
        for name, values in zip(header, columns)
    ]
    separator = ",\n"
    body = separator.join(column_definitions)
    return f"CREATE TABLE {table_name} (\n{body}\n);"


def main():
    script_folder = os.path.dirname(os.path.abspath(__file__))
    data_folder = os.path.abspath(os.path.join(script_folder, "..", "..", "data", "raw"))
    output_path = os.path.abspath(
        os.path.join(script_folder, "..", "..", "sql", "oracle", "02_generated_schema.sql")
    )
    mapping_path = os.path.abspath(
        os.path.join(script_folder, "..", "..", "sql", "oracle", "column_renames.csv")
    )
    rename_mappings.clear()
    csv_files = sorted(file for file in os.listdir(data_folder) if file.endswith(".csv"))
    sql_statements = [generate_create_table(os.path.join(data_folder, file)) for file in csv_files]

    with open(output_path, "w", encoding="utf-8") as output_file:
        output_file.write(
            "-- ARQUIVO GERADO - NAO EDITAR A MAO.\n"
            "-- Regenere este arquivo executando generate_oracle_ddl.py.\n"
            "-- Constraints, indices e regras de negocio ficam em 03_constraints_and_indexes.sql.\n\n"
            + "\n\n".join(sql_statements)
            + "\n"
        )

    with open(mapping_path, "w", newline="", encoding="utf-8") as mapping_file:
        writer = csv.DictWriter(
            mapping_file,
            fieldnames=["table_name", "source_column", "oracle_column"],
        )
        writer.writeheader()
        writer.writerows(rename_mappings)

    print(f"DDL gerado para {len(csv_files)} tabelas: {output_path}")
    print(f"Mapeamento de colunas renomeadas: {mapping_path}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")
    main()