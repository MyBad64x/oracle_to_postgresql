-- =====================================================================
-- ANÁLISE DE COLUNA NUMÉRICA — decisão de tipo para migração
-- =====================================================================
--
-- OBJETIVO
--   Colunas declaradas apenas como NUMBER no Oracle (sem precisão nem
--   escala) não dizem nada sobre o dado que guardam. Convertidas
--   cegamente, viram NUMERIC genérico no PostgreSQL — que é aritmética
--   de precisão arbitrária em software, muito mais lenta que BIGINT ou
--   DOUBLE PRECISION.
--
--   Esta query olha o CONTEÚDO REAL da coluna para decidir o tipo de
--   destino com base em evidência, não em suposição.
--
-- COMO USAR
--   Substituir <COLUNA> e <TABELA> abaixo. Rodar uma vez por coluna
--   numérica relevante antes de escrever o DDL do PostgreSQL.
--
-- ATENÇÃO
--   MAX(ABS()) mostra o maior valor QUE EXISTE HOJE. Se a coluna
--   alimenta um ID sequencial que ainda cresce, não escolher INTEGER só
--   porque hoje cabe — subir para BIGINT.
-- =====================================================================

SELECT
    MIN(<COLUNA>)                          AS minimo,
    MAX(<COLUNA>)                          AS maximo,
    COUNT(*)                               AS total_linhas,
    COUNT(<COLUNA>)                        AS nao_nulos,
    COUNT(CASE WHEN <COLUNA> <> TRUNC(<COLUNA>) THEN 1 END) AS com_decimais,
    MAX(LENGTH(TO_CHAR(TRUNC(ABS(<COLUNA>))))) AS digitos_inteiros,
    CASE
        WHEN COUNT(CASE WHEN <COLUNA> <> TRUNC(<COLUNA>) THEN 1 END) = 0
             AND MAX(ABS(<COLUNA>)) < 2147483647 THEN 'INTEGER'
        WHEN COUNT(CASE WHEN <COLUNA> <> TRUNC(<COLUNA>) THEN 1 END) = 0
             THEN 'BIGINT'
        ELSE 'NUMERIC (definir escala)'
    END                                    AS tipo_postgres_sugerido
FROM <TABELA>;


-- =====================================================================
-- COMO LER O RESULTADO
-- =====================================================================
--
--   com_decimais = 0        → é inteiro; escolher INTEGER ou BIGINT
--   com_decimais > 0        → precisa de tipo decimal
--   maximo < 2.147.483.647  → cabe em INTEGER (cuidado com crescimento)
--   maximo maior            → exige BIGINT
--   total_linhas <> nao_nulos → há nulos; a coluna NÃO pode ser NOT NULL
--
-- Para valores monetários, preferir sempre NUMERIC com precisão e escala
-- explícitas (ex.: NUMERIC(14,2)). Nunca usar ponto flutuante para
-- dinheiro.


-- =====================================================================
-- APOIO: metadados declarados da tabela
-- =====================================================================
--
-- Mostra o que foi DECLARADO no schema. Comparar com o resultado acima:
-- data_precision e data_scale nulos = NUMBER sem precisão = investigar.
--
-- Lembrete: o Oracle guarda nomes de objeto em MAIÚSCULO.

SELECT
    column_name,
    data_type,
    data_precision,
    data_scale,
    nullable
FROM user_tab_columns
WHERE table_name = '<TABELA_EM_MAIUSCULO>'
ORDER BY column_id;