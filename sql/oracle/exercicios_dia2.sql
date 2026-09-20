-- =====================================================================
-- EXERCÍCIOS DIA 2 — Reescrita de queries do LH Nautical em Oracle
-- =====================================================================
--
-- OBJETIVO
--   Reproduzir em sintaxe Oracle as análises originalmente escritas em
--   PostgreSQL no desafio LH Nautical, para sentir na prática as
--   divergências entre os dois dialetos.
--
-- STATUS: EXECUTADAS EM 2026-09-20
--   As queries foram executadas após a carga das 24 tabelas do LH Nautical.
--   Os resultados conferiram com o gabarito de referência abaixo.
--
--   A validação foi concluída no Dia 4. Qualquer divergência futura deve
--   ser investigada como possível alteração no dataset ou na tradução.
--
-- GABARITO DE REFERÊNCIA (resultados do desafio original)
--   - orders: 48.998 linhas, datas de 2020-01-01 a 2026-12-31
--   - total: min 32,62 / max 127.262,02 / média 28.704,99 / sem nulos
--   - salesperson_id: 24.131 nulos, todos no canal ecommerce
--   - top 10 clientes: todos com diversidade 14; maior ticket médio
--     é o cliente 22, com 41.839,94
--   - pior dia da semana no canal pos: quinta-feira, 157.154,32
-- =====================================================================


-- =====================================================================
-- 1. Contagem de linhas e range de datas — orders
-- =====================================================================
--
-- NOTA: created_at é DATE no Oracle, portanto MIN/MAX trazem data COM
-- hora. Aqui isso é desejável: ajuda a distinguir erro de digitação de
-- dado gerado por sistema (a data de 2026 encontrada no desafio).
-- Para obter apenas o range de dias, envolver em TRUNC().

SELECT
    COUNT(*)        AS total_rows,
    MIN(created_at) AS min_created_at,
    MAX(created_at) AS max_created_at
FROM orders;


-- =====================================================================
-- 2. Estatísticas da coluna total
-- =====================================================================
--
-- COUNT(*) conta linhas; COUNT(coluna) ignora nulos. A diferença entre
-- os dois é a contagem de nulos — mais barato que um CASE e idêntico
-- em Oracle e PostgreSQL.

SELECT
    MIN(total)                 AS min_total,
    MAX(total)                 AS max_total,
    ROUND(AVG(total), 2)       AS avg_total,
    COUNT(*) - COUNT(total)    AS nulos
FROM orders;


-- =====================================================================
-- 3. Nulos de salesperson_id por canal
-- =====================================================================
--
-- ATENÇÃO: COUNT(*) FILTER (WHERE ...) NÃO EXISTE NO ORACLE.
-- O padrão portável é COUNT(CASE WHEN ... THEN 1 END) — o COUNT já
-- ignora nulos, dispensando o ELSE 0 exigido pelo SUM.
--
-- Ambas as formas abaixo estão corretas; a segunda é mais idiomática.

SELECT
    channel,
    COUNT(*)                                             AS total_pedidos,
    COUNT(CASE WHEN salesperson_id IS NULL THEN 1 END)   AS pedidos_sem_vendedor,
    SUM(CASE WHEN salesperson_id IS NULL THEN 1 ELSE 0 END) AS pedidos_sem_vendedor_alt
FROM orders
GROUP BY channel;


-- =====================================================================
-- 4. Top 10 clientes por ticket médio, com diversidade de categorias
-- =====================================================================
--
-- DIFERENÇAS EM RELAÇÃO À VERSÃO POSTGRESQL:
--
--   LIMIT 10  →  FETCH FIRST 10 ROWS ONLY  (vem DEPOIS do ORDER BY)
--
--   WITH e COUNT(DISTINCT ...) funcionam igual nos dois bancos.
--
-- DIVISÃO — ponto de atenção na migração:
--   No Oracle só existe NUMBER, então NÃO há divisão inteira:
--   7/2 = 3,5 sempre.
--   No PostgreSQL, integer / integer TRUNCA para 3, silenciosamente.
--   Ou seja: esta query funciona no Oracle e pode passar a truncar
--   depois de migrada, se os tipos de destino forem inteiros.
--   É uma das causas de totais não baterem entre origem e destino.
--
-- FETCH FIRST ... ROWS ONLY corta exatamente em 10, mesmo havendo
-- empate na décima posição. Para trazer todos os empatados existe
-- FETCH FIRST 10 ROWS WITH TIES.

WITH receita_cliente AS (
    SELECT
        customer_id,
        SUM(total) AS faturamento_total,
        COUNT(id)  AS frequencia
    FROM orders
    GROUP BY customer_id
),
diversidade_cliente AS (
    SELECT
        o.customer_id,
        COUNT(DISTINCT p.category_id) AS diversidade_categorias
    FROM orders o
    JOIN order_items      oi ON oi.order_id          = o.id
    JOIN product_variants pv ON pv.id                = oi.product_variant_id
    JOIN products         p  ON p.id                 = pv.product_id
    GROUP BY o.customer_id
)
SELECT
    r.customer_id,
    r.faturamento_total,
    r.frequencia,
    r.faturamento_total / r.frequencia AS ticket_medio,
    d.diversidade_categorias
FROM receita_cliente r
JOIN diversidade_cliente d ON d.customer_id = r.customer_id
WHERE d.diversidade_categorias >= 13
ORDER BY ticket_medio DESC, r.customer_id ASC
FETCH FIRST 10 ROWS ONLY;


-- =====================================================================
-- 5. Média de vendas por dia da semana — canal pos
-- =====================================================================
--
-- GERAÇÃO DE DATAS: generate_series NÃO EXISTE NO ORACLE.
--
--   O padrão usado aqui (CONNECT BY LEVEL) é clássico e aparece muito
--   em código legado. Ele funciona porque date_bounds retorna
--   EXATAMENTE UMA LINHA — se retornasse duas, o Oracle geraria o
--   produto das hierarquias e o volume explodiria.
--
--   Alternativa mais explícita e mais próxima do PostgreSQL: CTE
--   recursiva (suportada desde o 11gR2). Vale reescrever como exercício
--   antes da Semana 3, quando a dimensão de calendário for construída
--   de verdade.
--
-- DIA DA SEMANA — A ARMADILHA PRINCIPAL DESTA QUERY:
--
--   TO_CHAR(data, 'D') retorna o número do dia da semana conforme o
--   NLS_TERRITORY DA SESSÃO. Em território brasileiro 1 = domingo; em
--   outros, 1 = segunda.
--
--   A mesma query roda na máquina local e no servidor da empresa e
--   devolve resultados DESLOCADOS EM UM DIA. Quinta vira quarta e
--   ninguém percebe, porque o resultado continua plausível.
--
--   No desafio, a conclusão foi que quinta-feira é o pior dia. Com o
--   territory errado, esse número vai para a diretoria com o dia trocado.
--
--   SOLUÇÃO ADOTADA: ancorar numa data conhecida.
--   1970-01-04 foi um domingo. MOD(data - âncora, 7) devolve
--   0 = domingo ... 6 = sábado, independente de qualquer configuração.
--
--   O literal DATE '1970-01-04' é sintaxe ANSI: funciona igual em Oracle
--   e PostgreSQL e dispensa TO_DATE com máscara.
--
--   ALTERNATIVA (mais legível, também determinística):
--     TO_CHAR(d.date_day, 'DY', 'NLS_DATE_LANGUAGE=ENGLISH')
--   Retorna sempre SUN, MON, TUE... e o CASE mapeia os textos.
--   ATENÇÃO: 'DY' devolve TEXTO. Aplicar TO_NUMBER nele dispara
--   ORA-01722 (invalid number).

WITH date_bounds AS (
    SELECT
        TRUNC(MIN(created_at)) AS min_date,
        TRUNC(MAX(created_at)) AS max_date
    FROM orders
),
date_dimension AS (
    SELECT (b.min_date + LEVEL - 1) AS date_day
    FROM date_bounds b
    CONNECT BY LEVEL <= (b.max_date - b.min_date + 1)
),
daily_pos_sales AS (
    SELECT
        TRUNC(created_at) AS date_day,
        SUM(total)        AS daily_total
    FROM orders
    WHERE channel = 'pos'
    GROUP BY TRUNC(created_at)
),
calendar_with_sales AS (
    SELECT
        d.date_day,
        COALESCE(s.daily_total, 0) AS daily_total,
        -- 0 = domingo ... 6 = sábado, independente de NLS_TERRITORY
        MOD(TRUNC(d.date_day) - DATE '1970-01-04', 7) AS day_of_week_num
    FROM date_dimension d
    LEFT JOIN daily_pos_sales s ON s.date_day = d.date_day
)
SELECT
    CASE day_of_week_num
        WHEN 0 THEN 'Domingo'
        WHEN 1 THEN 'Segunda-feira'
        WHEN 2 THEN 'Terça-feira'
        WHEN 3 THEN 'Quarta-feira'
        WHEN 4 THEN 'Quinta-feira'
        WHEN 5 THEN 'Sexta-feira'
        WHEN 6 THEN 'Sábado'
    END                        AS dia_semana,
    ROUND(AVG(daily_total), 2) AS media_vendas,
    day_of_week_num
FROM calendar_with_sales
GROUP BY day_of_week_num
ORDER BY media_vendas ASC;


-- =====================================================================
-- REFERÊNCIA: versão PostgreSQL original (NÃO RODA NO ORACLE)
-- =====================================================================
--
-- Mantida apenas para comparação lado a lado. O LIMIT no final é o
-- ponto de divergência.
--
-- WITH receita_cliente AS (...),
--      diversidade_cliente AS (...)
-- SELECT ...
-- FROM receita_cliente r
-- JOIN diversidade_cliente d ON d.customer_id = r.customer_id
-- WHERE d.diversidade_categorias >= 13
-- ORDER BY ticket_medio DESC, r.customer_id ASC
-- LIMIT 10;