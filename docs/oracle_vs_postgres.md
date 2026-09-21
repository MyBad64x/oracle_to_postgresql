# Oracle × PostgreSQL — Caderno de campo
 
> Anotações acumuladas durante o projeto de treino `oracle_to_postgres`.
> Cada item traz o conceito, o impacto na migração e o que fazer a respeito.
 
---
 
## 1. Arquitetura e conexão
 
### CDB × PDB (multitenant, Oracle 12c+)
 
| Termo | O que é | No ambiente de treino |
|---|---|---|
| **CDB** (Container Database) | Container raiz: processos, memória, configuração | `FREE` |
| **PDB** (Pluggable Database) | O banco de verdade, onde ficam os dados | `FREEPDB1` |
 
Um CDB pode ter vários PDBs plugados. **Conectar no CDB por engano faz as tabelas "sumirem"** — elas estão no PDB.
 
Confirmar onde se está conectado:
 
```sql
SELECT SYS_CONTEXT('USERENV', 'CON_NAME') AS container FROM DUAL;
SELECT USER AS usuario FROM DUAL;
```
 
### SID × SERVICE_NAME
 
- **SID** — identificador da instância. Jeito antigo, aponta para a instância inteira (o CDB).
- **SERVICE_NAME** — jeito moderno, aponta para o serviço (o PDB).
**Regra: usar sempre SERVICE_NAME.** No DBeaver, o dropdown vem em SID por padrão — trocar manualmente.
 
Formato da string de conexão:
 
```
usuario/senha@host:porta/service_name
```
 
Exemplo (sqlplus dentro do container):
 
```bash
sqlplus lh_user/lh_pwd@localhost:1521/FREEPDB1
```
 
Porta padrão do Oracle: **1521** (equivalente à 5432 do PostgreSQL).
 
### Usuário = schema
 
No Oracle, **usuário e schema são a mesma coisa**. Criar um usuário cria um schema homônimo automaticamente. Não existe a separação do PostgreSQL (um banco → vários schemas → usuários à parte).
 
Consequência: `SELECT * FROM customers` procura em `MEU_USUARIO.CUSTOMERS`. Para acessar tabela de outro usuário é preciso qualificar (`OUTRO_USER.TABELA`) e ter permissão.
 
O Oracle guarda os nomes de objeto em **MAIÚSCULO** no dicionário de dados. Isso importa nas queries do dicionário: `WHERE table_name = 'ORDERS'`, não `'orders'`.
 
### Ambiente de treino
 
Imagem: `gvenzl/oracle-free:slim` (não exige conta na Oracle).
 
```yaml
services:
  oracle:
    image: gvenzl/oracle-free:slim
    container_name: oracle_lh
    ports:
      - "1521:1521"
    environment:
      ORACLE_PASSWORD: oracle_admin_pwd
      APP_USER: lh_user
      APP_USER_PASSWORD: lh_pwd
    volumes:
      - oracle_data:/opt/oracle/oradata
 
volumes:
  oracle_data:
```
 
Primeira subida leva de 2 a 5 minutos. Aguardar a linha `DATABASE IS READY TO USE!` nos logs.
 
**Erro `failed to connect to the docker API`** não tem relação com Oracle: é o daemon do Docker que não está rodando. Abrir o Docker Desktop e confirmar com `docker info`.
 
---
 
## 2. Ferramentas
 
### DBeaver — dois modos de execução
 
| Atalho | Comportamento |
|---|---|
| `Ctrl+Enter` | Executa **apenas a instrução onde está o cursor** |
| `Alt+X` | Executa **o script inteiro**, de cima a baixo |
 
DDL seguido de carga exige `Alt+X`. Rodar linha a linha deixa metade do schema criado sem explicação aparente.
 
Cada `SELECT` do script vira uma aba de resultado separada — conferir qual aba se está lendo antes de concluir qualquer coisa.
 
### A ferramenta pode mentir sobre o dado
 
O DBeaver recebe datas pelo driver JDBC como objeto e formata com config própria — **ignora o `NLS_DATE_FORMAT` do Oracle**. A mesma query mostra hora no DBeaver e esconde no sqlplus.
 
**Consequência para a migração: validar comparando valores brutos, nunca o que a tela exibe.**
 
### COMMIT não é automático
 
No Oracle, DML no sqlplus **não é comitado automaticamente**. Sem `COMMIT;`, o dado existe só na sessão que o inseriu.
 
Erro clássico de quem vem do PostgreSQL: inserir pelo terminal, não ver nada no DBeaver, achar que a carga falhou.
 
---
 
## 3. Datas — o bug mais silencioso da migração
 
### `DATE` no Oracle inclui hora
 
O tipo `DATE` do Oracle sempre armazena **data + hora até o segundo**. O que muda entre clientes é só a exibição, controlada por `NLS_DATE_FORMAT`.
 
```sql
ALTER SESSION SET NLS_DATE_FORMAT = 'YYYY-MM-DD HH24:MI:SS';
SELECT SYSDATE FROM DUAL;
```
 
**Mapeamento correto na migração: `DATE` (Oracle) → `TIMESTAMP` (PostgreSQL).** Converter para `DATE` do PostgreSQL descarta a hora silenciosamente.
 
### O bug do filtro por igualdade
 
```sql
-- Registro gravado com TO_DATE('2026-09-02','YYYY-MM-DD') → 2026-09-02 00:00:00
-- Registro gravado com SYSDATE                            → 2026-09-02 19:50:48
 
SELECT * FROM teste_data
WHERE momento = TO_DATE('2026-09-02', 'YYYY-MM-DD');
-- retorna APENAS o primeiro
```
 
Traduzindo para o mundo real: um relatório com `WHERE data_venda = '15/03/2024'` retorna **zero vendas**, porque toda venda tem hora. O gestor conclui que não se vendeu nada naquele dia. Esse erro sobrevive anos sem ninguém notar.
 
### As duas soluções
 
```sql
-- A) TRUNC — funciona, mas IMPEDE o uso de índice
SELECT * FROM teste_data
WHERE TRUNC(momento) = TO_DATE('2026-09-02', 'YYYY-MM-DD');
 
-- B) Faixa — funciona E usa índice  ← PREFERIR
SELECT * FROM teste_data
WHERE momento >= TO_DATE('2026-09-02', 'YYYY-MM-DD')
  AND momento <  TO_DATE('2026-09-03', 'YYYY-MM-DD');
```
 
Aplicar função na coluna (`TRUNC(momento)`) obriga o Oracle a calcular linha a linha antes de comparar, inviabilizando o índice. **Em base de 30 anos isso é varredura completa da tabela** — exatamente o tipo de query que sobrecarrega o ERP.
 
Detalhe: o limite superior usa `<`, não `<=`. Com `<=`, uma venda registrada exatamente à meia-noite do dia seguinte entraria por engano.
 
### `TO_DATE` exige máscara
 
Não existe conversão implícita confiável. Sempre `TO_DATE('2026-09-02', 'YYYY-MM-DD')`.
 
---
 
## 4. Tipos numéricos — a decisão que mais afeta a migração
 
### Só existe `NUMBER`
 
O Oracle não tem INTEGER, BIGINT e DECIMAL como tipos distintos. Tudo é `NUMBER`, variando por precisão e escala:
 
| Declaração | Significado |
|---|---|
| `NUMBER` | Qualquer número, até 38 dígitos significativos, escala variável |
| `NUMBER(10)` | Inteiro de até 10 dígitos |
| `NUMBER(10,2)` | 10 dígitos no total, 2 decimais |
 
### Arredondamento silencioso
 
`INSERT` de `1234.567` numa coluna `NUMBER(10,2)` grava **`1234.57`**. Sem erro, sem aviso.
 
Na migração, é onde os totais deixam de bater entre origem e destino.
 
### O problema do `NUMBER` sem precisão
 
Colunas declaradas apenas como `NUMBER` vêm com `data_precision` e `data_scale` **nulos** no dicionário. Convertidas cegamente, viram `NUMERIC` sem precisão no PostgreSQL.
 
`NUMERIC` no PostgreSQL é aritmética de precisão arbitrária **implementada em software** — muito mais lenta que `BIGINT` ou `DOUBLE PRECISION`, que usam instrução de CPU. Numa fato de vendas com dezenas de milhões de linhas, a diferença é grande.
 
Base de 30 anos tem muitas colunas assim, porque era comum declarar `NUMBER` e seguir em frente.
 
**A solução é investigativa, não técnica:** olhar o dado real antes de escolher o tipo de destino. Ver `sql/oracle/analise_coluna_numerica.sql`.
 
Cuidado ao decidir: `MAX(ABS())` mostra o maior valor **que existe hoje**. Se a coluna alimenta um ID sequencial que ainda cresce, escolher `INTEGER` porque hoje cabe é armadilha — subir para `BIGINT`.
 
---
 
## 5. Tipos de texto
 
| Tipo | Comportamento |
|---|---|
| `CHAR(n)` | **Preenche com espaços** até o tamanho declarado. `LENGTH('abc')` numa `CHAR(10)` retorna 10 |
| `VARCHAR2(n)` | Tamanho variável. `LENGTH('abc')` retorna 3 |
| `CLOB` | Texto longo → `TEXT` no PostgreSQL |
 
Base antiga usa `CHAR` para código de produto e status. O espaço à direita **quebra `JOIN` e `GROUP BY`** depois da migração: `'ATIVO     '` não é igual a `'ATIVO'`.
 
**Tratamento obrigatório na carga: `TRIM`.**
 
Sobre o nome: usar `VARCHAR2`. Existe um `VARCHAR` no Oracle, mas a própria documentação orienta não usá-lo, porque o comportamento pode mudar em versões futuras.
 
---
 
## 6. Sintaxe divergente
 
| Oracle | PostgreSQL | Observação |
|---|---|---|
| `NVL(a, b)` | `COALESCE(a, b)` | `COALESCE` também existe no Oracle; `NVL` é o que aparece em código legado |
| `NVL2(a, se_tem, se_nulo)` | `CASE WHEN` | Sem equivalente direto |
| `FROM DUAL` | (dispensável) | `FROM` é obrigatório no Oracle; `DUAL` é tabela de 1 linha/1 coluna |
| `SYSDATE` | `NOW()` / `CURRENT_TIMESTAMP` | |
| `\|\|` | `\|\|` | Igual nos dois |
| `FETCH FIRST n ROWS ONLY` | `LIMIT n` | Forma correta e moderna no Oracle (12c+) |
| `ROWNUM` | — | **Ver alerta abaixo** |
 
### `ROWNUM` — armadilha em código legado
 
`ROWNUM` numera as linhas **conforme saem do filtro, ANTES do `ORDER BY`**.
 
```sql
-- ERRADO: pega uma linha qualquer e depois ordena
SELECT * FROM teste_data
WHERE ROWNUM <= 1
ORDER BY momento DESC;
 
-- CORRETO
SELECT * FROM teste_data
ORDER BY momento DESC
FETCH FIRST 1 ROWS ONLY;
```
 
Código de 30 anos está cheio de `ROWNUM` — e possivelmente cheio desse bug. Reconhecer o padrão é parte do trabalho de auditar os relatórios existentes.
 
---
 
## 7. Alerta operacional: scripts não idempotentes
 
Rodar o script de carga duas vezes **duplica os dados**. No treino, `TOTAL` deu 4 onde deveria dar 2.
 
Na migração real, uma reexecução acidental duplica milhões de linhas e o faturamento total dobra no relatório. É a justificativa direta para a carga incremental com controle de estado (Semana 2).
 
---
 
## 8. Lições do exercício de reescrita (Dia 2)
 
### Dia da semana depende da configuração da sessão
 
`TO_CHAR(data, 'D')` retorna o número do dia da semana conforme o **`NLS_TERRITORY` da sessão**. Em território brasileiro 1 = domingo; em outros, 1 = segunda.
 
A mesma query roda na máquina local e no servidor da empresa e devolve resultados **deslocados em um dia**. Quinta vira quarta e ninguém percebe, porque o resultado continua plausível.
 
**Solução determinística — ancorar numa data conhecida:**
 
```sql
MOD(TRUNC(data) - DATE '1970-01-04', 7)   -- 0 = domingo ... 6 = sábado
```
 
`1970-01-04` foi um domingo. Independe de qualquer configuração.
 
**Alternativa (mais legível):**
 
```sql
TO_CHAR(data, 'DY', 'NLS_DATE_LANGUAGE=ENGLISH')   -- SUN, MON, TUE...
```
 
> **Cuidado:** `'DY'` devolve **texto**. Aplicar `TO_NUMBER` nele dispara `ORA-01722: invalid number`. As duas soluções são alternativas, não complementares.
 
O literal `DATE '1970-01-04'` é sintaxe ANSI: funciona igual em Oracle e PostgreSQL e dispensa `TO_DATE` com máscara. Vale adotar como padrão.
 
### Divisão: o cuidado é INVERSO ao esperado
 
No Oracle só existe `NUMBER`, portanto **não há divisão inteira**: `7/2` é sempre `3,5`.
 
No PostgreSQL, `integer / integer` **trunca** para `3`, silenciosamente.
 
**Consequência:** uma query que calculava ticket médio corretamente no Oracle pode passar a truncar depois de migrada, se os tipos de destino forem inteiros. É uma das causas de totais não baterem entre origem e destino.
 
### Geração de séries de datas
 
`generate_series` não existe no Oracle. Dois caminhos:
 
```sql
-- Padrão clássico (aparece muito em código legado)
SELECT (b.min_date + LEVEL - 1) AS date_day
FROM date_bounds b
CONNECT BY LEVEL <= (b.max_date - b.min_date + 1);
```
 
Funciona **porque `date_bounds` retorna exatamente uma linha**. Com duas linhas, o Oracle gera o produto das hierarquias e o volume explode.
 
A alternativa é **CTE recursiva** (suportada desde o 11gR2), mais explícita e mais próxima do que se escreveria no PostgreSQL.
 
### Sem `FILTER` no Oracle
 
`COUNT(*) FILTER (WHERE ...)` do PostgreSQL não existe. O padrão portável:
 
```sql
COUNT(CASE WHEN condicao THEN 1 END)
```
 
O `COUNT` já ignora nulos, dispensando o `ELSE 0` que o `SUM` exigiria.
 
### `FETCH FIRST` e empates
 
`FETCH FIRST n ROWS ONLY` corta exatamente em *n*, mesmo havendo empate na última posição — o corte é arbitrário. Para trazer todos os empatados existe `FETCH FIRST n ROWS WITH TIES`.
 
### Contagem de nulos
 
```sql
COUNT(*) - COUNT(coluna) AS nulos
```
 
`COUNT(*)` conta linhas, `COUNT(coluna)` ignora nulos. Mais barato que um `CASE` e idêntico nos dois bancos.
 
---
 
## 9. Modelagem do schema (Dia 3)
 
### Tipo escolhido por evidência, nunca por hábito
 
Inspecionar o dado antes de escrever qualquer `CREATE TABLE`. Regras que saíram disso:
 
- **Documento, telefone, CEP, código:** sempre texto. Zero à esquerda, hífen, ponto, ou nenhuma conta que faça sentido → `VARCHAR2`. (No desafio original, `tax_id`, `cpf` e `phone` inferidos como `INTEGER` estouraram a carga.)
- **Monetário:** `NUMBER(p,s)` com precisão explícita e **folga**. Maior valor conhecido 127.262,02 → `NUMBER(12,2)` absorve décadas de crescimento.
- **`VARCHAR2`:** folga não custa nada — só ocupa o que usa. Quando o domínio é conhecido e fixo (`'PF'`, `'PJ'`), apertar documenta a intenção.
- **`CHAR`:** nunca em schema novo. Na base legada, é ponto de `TRIM` obrigatório.
### Booleano
 
O Oracle 23ai suporta `BOOLEAN` em SQL, mas **base legada não tem**: o padrão é `NUMBER(1)` com 0/1 ou `CHAR(1)` com `Y`/`N`. No treino, `NUMBER(1)` + `CHECK (col IN (0,1))`, para ensaiar o cenário real — inclusive a conversão `TRUE`/`FALSE` → `1`/`0` na carga.
 
### `DATE` × `TIMESTAMP` no treino
 
Usar `DATE`, por fidelidade ao que a base de 30 anos terá. Diferença prática:
 
- `DATE - DATE` devolve **número de dias**, direto
- `TIMESTAMP - TIMESTAMP` devolve um **`INTERVAL`**, mais trabalhoso
No PostgreSQL, os dois viram `TIMESTAMP`.
 
### `NOT NULL` baseado em contagem real
 
Antes de declarar `NOT NULL`, contar vazios em todas as colunas. `NOT NULL` que a carga viola **derruba a carga inteira**.
 
- Evidência define o **piso**: se tem nulo, é nullable, ponto.
- `NOT NULL` em coluna **sem nulo hoje** exige confirmação da regra de negócio. Zero nulos agora não garante zero nulos amanhã.
- Na base real, o inverso também acontece: coluna obrigatória pela regra de negócio com nulos, carregados antes da constraint existir.
**Método:** quando um resultado de validação contradiz dado que você já viu com os próprios olhos, o suspeito é a validação, não o dado. (A primeira checagem reportou 0 vazios em `trade_name`; a amostra mostrava vazio na segunda linha.)
 
### String vazia é `NULL` no Oracle — no PostgreSQL não
 
```sql
SELECT CASE WHEN '' IS NULL THEN 'string vazia É nula'
            ELSE 'string vazia NÃO é nula' END
FROM DUAL;   -- Oracle: É nula
```
 
| | Oracle | PostgreSQL |
|---|---|---|
| `'' IS NULL` | verdadeiro | falso |
| `NOT NULL` aceita `''`? | não (vazio é nulo) | **sim** |
| `WHERE campo = ''` | nunca retorna nada | retorna as strings vazias |
 
Consequências na migração:
 
- A mesma constraint `NOT NULL` fica **mais permissiva no destino** — um `INSERT` rejeitado na origem passa no PostgreSQL.
- Se a carga converter nulos em `''`, surgem dois valores distintos onde havia um, e todo `COUNT` com filtro de nulo muda.
Tratamento: converter `''` para `NULL` explicitamente na carga; considerar `CHECK (campo <> '')` onde importar.
 
### `CHECK` com domínio confirmado no dado
 
Domínio incompleto derruba a carga na primeira linha fora dele. Confirmar antes com contagem de valores distintos (`Counter` em Python ou `GROUP BY` em SQL). No treino, `orders.status` tinha `draft`, que não estava no chute inicial.
 
Na base real, espere valores que ninguém sabe explicar, de sistemas descontinuados há anos.
 
### Palavras reservadas e aspas
 
Aspas duplas (`"number"`) tornam o identificador **case-sensitive para sempre**: toda referência futura precisa de aspas — em query, script Python, ferramenta de BI — e o dicionário guarda minúsculo, escapando de buscas com `UPPER()`.
 
Quando o schema é seu, **renomear** (`number` → `address_number`). Quando o schema já existe (a empresa), reconhecer e tratar.
 
### Ordem de criação e FKs
 
FK só pode ser criada depois da tabela referenciada. Duas estratégias:
 
- **Ordenar topologicamente** — exige mapear o grafo de dependências
- **Criar todas as tabelas sem FK e adicionar as FKs em bloco com `ALTER TABLE`** — ordem deixa de importar; é o que ferramentas de migração fazem
A segunda também permite **carregar com FKs ausentes e aplicar depois**, o que acelera muito a carga em massa.
 
### FK sem índice = lock da tabela filha inteira
 
No PostgreSQL, índice em coluna de FK é questão de performance de `JOIN`. **No Oracle é mais sério:** `DELETE` ou `UPDATE` da chave na tabela pai, sem índice na FK da filha, faz o Oracle travar **a tabela filha inteira** — não só as linhas afetadas.
 
Causa clássica de "o sistema congela no fechamento do mês" em base antiga. Procurar FK sem índice é das primeiras verificações ao diagnosticar lentidão (query na seção 11).
 
### Constraints automáticas
 
- **PK sempre gera índice único automático.** Confunde quem conta índices manuais numa base legada.
- **Todo `NOT NULL` vira uma check constraint interna** com nome gerado (`SYS_C008717`), cuja condição é `"ID" IS NOT NULL`.
O número do `SYS_C` é sequencial por banco: **a mesma constraint tem nome diferente em cada ambiente**. Script que referencia `SYS_C008717` funciona em dev e falha em produção. Por isso nomear constraints explicitamente (`CHK_`, `PK_`, `FK_`).
 
```sql
SELECT constraint_name, search_condition
FROM user_constraints
WHERE table_name = 'CUSTOMERS' AND constraint_type = 'C';
```
 
`search_condition` guarda o texto literal que foi escrito — maiúsculo e minúsculo misturados. Buscar com `UPPER()`.
 
**Armadilha:** em versões antigas, `search_condition` é do tipo `LONG`, que **não aceita `WHERE`, `LIKE` nem funções de string**. A partir do 12c existe `search_condition_vc`.
 
### Conferir o criado contra o pretendido
 
Script que roda sem erro não é script que fez o que se queria. Contar PKs, FKs, checks e índices após a execução e comparar com a intenção. (No treino, faltava 1 FK — a de `products`, tabela ainda inexistente.)
 
---
 
## 10. Gerador de DDL e carga (Dia 4)
 
### Caminho relativo depende de onde o script é chamado
 
`Path("data/raw")` resolve a partir do **diretório atual do terminal**, não do arquivo. Script agendado roda num diretório que você não controla — e quebra às 3 da manhã.
 
```python
raw_dir = Path(__file__).resolve().parents[2] / "data" / "raw"
```
 
### Encoding na leitura
 
Se der `UnicodeDecodeError` com `utf-8`, tentar `latin-1` — **e registrar**, porque é exatamente o problema da base legada brasileira.
 
### Gerador = esqueleto; decisão = arquivo humano
 
| Arquivo | Origem | Pode regenerar? |
|---|---|---|
| `02_generated_schema.sql` | gerador (tabelas + tipos) | sim — cabeçalho "ARQUIVO GERADO, NÃO EDITAR" |
| `03_constraints_and_indexes.sql` | escrito à mão | nunca sobrescrito |
 
Espelha o que o ora2pg faz: entrega tabelas convertidas e **nenhuma decisão tomada**.
 
### O que a inferência automática não resolve
 
- **Folga:** dimensiona pelo passado. `NUMBER(8,2)` cabe no maior valor atual e quebra na primeira venda acima de um milhão. Mitigação mínima: somar dígitos inteiros de folga.
- **Escala falsa:** `3.000` tem três casas decimais mas é o inteiro 3. Regra: se todos os valores têm parte decimal zerada, tratar como inteiro.
- **Conceito × dado:** a regra da escala falsa transformou alíquotas (`12.00`, `17.00`) em inteiros. Correto para o dado atual, errado para o conceito — ICMS admite fração. **Regra automática troca um tipo de erro por outro, nunca elimina erro.**
- **Coluna 100% vazia:** nenhuma inferência possível. Exige decisão humana (e é sinal de campo abandonado).
- **Data guardada como número** (`20240315`) passa em `is_int` e vira `NUMBER`. Sinal: nome com `data`/`date` e valores entre 19000101 e 20991231.
- **`_id` nem sempre é chave:** `tax_id` termina em `_id` e é documento. Lista explícita de exceções.
- **Nome composto** (`barcode_ean`, `nfe_access_key`) escapa de tokenização por `_`. Identificadores longos: texto. Chave de NFe tem 44 dígitos — não cabe em `NUMBER(19)`.
- **Palavra reservada:** renomear e **persistir o mapeamento** (`column_renames.csv`). O CSV continua com o header original; a carga precisa saber que `number` vai para `address_number`.
### `VARCHAR2` e o limite de bytes
 
O limite de 4000 é em **bytes** por padrão. Em UTF-8, acento ocupa 2. Declarar `VARCHAR2(n CHAR)` ou usar `CLOB` acima de certo tamanho.
 
### Carga em massa: dados antes das constraints
 
1. Schema nu (tabelas e tipos)
2. **Carga dos dados**
3. Constraints e índices
Mais rápido (sem validação linha a linha nem manutenção de índice) e, se uma constraint falhar, a violação é investigável por SQL com a tabela cheia. É o procedimento padrão, não otimização de treino.
 
### `executemany` em lotes
 
147.320 linhas de `order_items` em **2 segundos**. Com `execute()` em loop, minutos. É o equivalente do `COPY` do PostgreSQL.
 
### Transformação guiada pelo tipo de destino
 
Converter para data só em coluna `DATE`; `TRUE`/`FALSE` só em `NUMBER(1)`. Transformar "tudo que parece data" corrompe códigos e textos livres.
 
### Validação da carga
 
Carga sem erro não é carga correta. Três camadas:
 
1. **Contagem de linhas** por tabela contra a origem
2. **Regras aritméticas do negócio**, descobertas no próprio dado:
```sql
   SELECT COUNT(*) FROM order_items WHERE line_total <> unit_price * quantity;  -- 0
   SELECT COUNT(*) FROM orders WHERE total <> subtotal - discount_amount;      -- 0
```
3. **Gabarito:** resultados já conhecidos (ticket médio do cliente 22 = 41.839,94; pior dia no `pos` = quinta-feira) reproduzidos no destino
---
 
## 11. Dicionário de dados e inventário (Dia 5)
 
### As views que importam
 
| View | O que entrega |
|---|---|
| `ALL_TABLES` | Tabelas, `NUM_ROWS`, `LAST_ANALYZED` |
| `ALL_TAB_COLUMNS` | Colunas, tipo, precisão, nulabilidade |
| `ALL_CONSTRAINTS` / `ALL_CONS_COLUMNS` | PK, FK, CHECK e suas colunas |
| `ALL_INDEXES` / `ALL_IND_COLUMNS` | Índices e suas colunas |
| `ALL_SEGMENTS` | Tamanho real em bytes |
| `ALL_TAB_COMMENTS` / `ALL_COL_COMMENTS` | Documentação, quando existe |
 
`USER_` = só o próprio schema; `ALL_` = o que o usuário pode ver; `DBA_` = tudo (exige privilégio). Na empresa, provavelmente `USER_` e `ALL_`.
 
### `NUM_ROWS` é estatística, não contagem
 
`NUM_ROWS` é calculado pelo otimizador e pode estar desatualizado há anos. No treino, as 24 tabelas recém-carregadas tinham `NUM_ROWS` e `LAST_ANALYZED` **nulos**.
 
```sql
BEGIN
    DBMS_STATS.GATHER_SCHEMA_STATS(USER);
END;
/
```
 
- **Nunca planejar extração só com `NUM_ROWS`** sem verificar `LAST_ANALYZED`.
- Estatística ausente ou velha também **degrada o plano de execução** — o otimizador chuta. Causa provável de "o sistema ficou lento do nada".
- Coletar estatística em produção consome recurso: é conversa com o DBA, não algo para rodar por conta própria.
- `COUNT(*)` em tabela de 40 milhões de linhas numa base de produção faz de você o problema que veio resolver.
### Ler o inventário como retrato do negócio
 
- **Poucas tabelas concentram o volume.** No treino, 5 de 24 tinham 95% dos dados. Elas definem a estratégia de extração.
- **A pirâmide de volumes revela o modelo:** 6 locais → 15 funcionários → 500 produtos → 2.000 clientes → 48.998 pedidos → 147.320 itens.
- **Proporção colunas/linhas:** larga e pequena = cadastro (dimensão); estreita e alta = transação (fato).
- **Número de tabelas filhas indica centralidade:** `PRODUCT_VARIANTS` referenciada por 6 FKs não pode ser alterada sem afetar meio sistema.
- **Hierarquia auto-referenciada** (`categories.parent_category_id`) exige `CONNECT BY` ou CTE recursiva; sem limite de profundidade, é fonte clássica de query infinita.
### Reconstruir o grafo sem documentação
 
`r_constraint_name` liga a FK à PK referenciada:
 
```sql
SELECT c.table_name AS filha, cc.column_name AS coluna_fk,
       rc.table_name AS pai, rcc.column_name AS coluna_pai
FROM user_constraints c
JOIN user_cons_columns cc  ON cc.constraint_name  = c.constraint_name
JOIN user_constraints  rc  ON rc.constraint_name  = c.r_constraint_name
JOIN user_cons_columns rcc ON rcc.constraint_name = rc.constraint_name
                          AND rcc.position        = cc.position
WHERE c.constraint_type = 'R';
```
 
### Encontrar FK sem índice
 
```sql
SELECT c.table_name, c.constraint_name, cc.column_name
FROM user_constraints c
JOIN user_cons_columns cc ON cc.constraint_name = c.constraint_name
WHERE c.constraint_type = 'R'
  AND NOT EXISTS (
      SELECT 1 FROM user_ind_columns ic
      WHERE ic.table_name = cc.table_name
        AND ic.column_name = cc.column_name
        AND ic.column_position = 1
  );
```
 
O índice precisa ter a coluna da FK **na primeira posição**. Índice com a coluna na segunda posição não evita o lock. No treino voltou vazio; numa base legada, cada linha é candidata a travamento.
 
### Script de inventário (`oracle_inventory.py`)
 
Princípios que valem para qualquer ferramenta rodada em base alheia:
 
- **Somente leitura.** Diagnostica e reporta; nenhum `ALTER`, nenhuma coleta de estatística. Ação sem permissão numa base que não é sua é como se perde acesso.
- **`ALL_*` com filtro de `owner`**, para inventariar schema de outro usuário.
- **Degradar em vez de morrer:** sem privilégio em `ALL_SEGMENTS` (`ORA-00942`), cair para `USER_SEGMENTS`.
- **Sem `COUNT(*)`:** usar `NUM_ROWS` e sinalizar quando `LAST_ANALYZED` for nulo ou antigo.
- **Relatório autoexplicativo** (seção "Como ler"), para enviar ao gestor ou ao DBA sem acompanhar explicando.
### Achados que o inventário revelou
 
- **Limite de identificador varia por versão:** **30 caracteres até o 12.1**, 128 a partir do 12.2. `FK_VARIANT_ATTRIBUTE_VALUES_ATTRIBUTES` tem 38 e falharia com `ORA-00972` numa versão antiga. Verificar a versão antes de definir convenção de nomes; projetar para caber em 30.
- **Inferência por tabela isolada gera inconsistência entre tabelas:** "quantidade" com cinco definições (`NUMBER(10,0)`, `NUMBER(10,3)`, `NUMBER(9,3)`...). Padronizar é trabalho da modelagem dimensional.
- **Schema tecnicamente impecável e 100% indocumentado:** 212 de 212 colunas sem comentário.
```sql
COMMENT ON COLUMN orders.salesperson_id IS
    'Vendedor responsavel. Nulo em pedidos de ecommerce (sem vendedor humano).';
```
 
Propor documentação de colunas é entrega barata e muito visível.
 
---
 
## Perguntas para levar à empresa (Semana 1)
 
- Existe réplica ou standby do Oracle disponível para leitura?
- Qual a janela de menor movimento do ERP?
- Os relatórios que sobrecarregam hoje rodam direto no banco, dentro do ERP, ou por ferramenta externa?
- Quais tabelas de vendas são realmente usadas?
- Quem é a pessoa mais antiga da casa que conhece o sistema?
- Que nível de acesso terei no Oracle — `USER_`, `ALL_` ou `DBA_`?
- Com que frequência as estatísticas do otimizador são coletadas?
- Uma coluna sem nulos hoje é obrigatória pela regra de negócio, ou só ainda não recebeu nulo?
- Existem colunas `CHAR` em chaves ou campos usados em `JOIN`?

## 12. Extração com `oracledb`
 
### Modo thin × thick
 
`oracledb` roda em **thin** por padrão (Python puro, sem Oracle Client). Wallet, alguns tipos legados e certas configurações de rede exigem **thick**. Se a conexão falhar por motivo estranho na empresa, conferir o modo primeiro:
 
```python
oracledb.is_thin_mode()
```
 
### `arraysize` controla velocidade; `fetchmany` controla memória
 
Medido em `order_items` (147.320 linhas, `localhost`):
 
| Estratégia | arraysize | Tempo | Pico de memória |
|---|---|---|---|
| fetchall | 100 | 3,31 s | 41 MB |
| fetchall | 5000 | 1,21 s | 41 MB |
| fetchmany | 100 | 2,65 s | 1,4 MB |
| fetchmany | 5000 | 0,95 s | 1,6 MB |
 
- `arraysize` = linhas por viagem de rede. De 100 para 5000: **63% mais rápido**, em `localhost`. Em rede corporativa, com latência real, o ganho é maior.
- `arraysize` **não muda a memória do `fetchall`** — todas as linhas terminam numa lista só.
- `fetchmany` mantém memória constante em qualquer volume. Extrapolando: 40 milhões de linhas num `fetchall` seriam ~11 GB.
**Usar os dois juntos:** `arraysize` alto + `fetchmany`.
 
### Cursor único × paginação
 
| | Cursor único | Paginado |
|---|---|---|
| Consistência | Snapshot único garantido | Cada página é um snapshot diferente |
| Cursor aberto | Durante toda a extração | Só durante uma página |
| Risco | `ORA-01555 snapshot too old` em extração longa | Linha duplicada ou perdida se houver alteração entre páginas |
 
Escolha depende da janela: extração em horário de baixo movimento → cursor único. Durante o expediente → paginado.
 
### Paginação exige coluna única
 
`WHERE coluna > :ultimo_valor` com coluna **não única** perde linhas em silêncio: todas as que compartilham o valor da última linha da página são puladas. Timestamps repetidos são regra em sistema que grava em lote.
 
Solução com desempate por chave:
 
```sql
WHERE (col > :ultimo) OR (col = :ultimo AND pk > :ultima_pk)
ORDER BY col, pk
```
 
### Parquet com schema explícito
 
Inferir schema do primeiro lote quebra quando uma coluna vem toda nula no início (tipo `null`) e com valores depois. Derivar o schema de `cursor.description`.
 
Mapear `NUMBER` com escala para `decimal128`, nunca `double` — senão o erro de ponto flutuante volta depois de todo o cuidado com precisão no Oracle.
 
---
 
## 13. Carga incremental
 
### Três estratégias, em ordem de preferência
 
1. **Coluna de controle** (`UPDATED_AT`, ID sequencial) — simples e eficiente, quando confiável
2. **Trigger de auditoria ou tabela de log** — quando existe
3. **Comparação completa** — último recurso, caro
### Validar a coluna de controle antes de confiar nela
 
```sql
-- nulos
SELECT COUNT(*) FROM t WHERE updated_at IS NULL;
-- ordem temporal violada
SELECT COUNT(*) FROM t WHERE updated_at < created_at;
-- datas no futuro
SELECT COUNT(*) FROM t WHERE updated_at > SYSDATE;
```
 
No treino, `customers` tinha **264 registros criados no passado com `updated_at` no futuro**.
 
### Data futura estoura o marcador
 
Se o marcador avança para uma data futura, **nenhuma alteração real volta a ser capturada** até aquela data chegar. A carga para em silêncio.
 
Proteção: teto na janela e log do que ficou de fora.
 
```sql
WHERE updated_at > :ultimo_valor
  AND updated_at <= SYSDATE
```
 
### Transação longa perde registros
 
Uma transação iniciada antes da extração e commitada depois grava `updated_at` anterior ao marcador — e nunca é capturada.
 
Proteção: **janela com sobreposição** (reextrair a partir de `marcador - margem`).
 
Consequência obrigatória: **o destino precisa ser idempotente** (`MERGE` / upsert). Carga incremental sem idempotência duplica dados.
 
### Marcador e estado
 
- O marcador só pode **avançar**, nunca retroceder: comparar com o valor acumulado, não com o máximo do lote.
- Estado salvo **só depois** de extração bem-sucedida, com escrita atômica (arquivo temporário + `replace`).
---
 
## 14. Encoding e dados sujos
 
### Charset é a primeira verificação numa base legada
 
```sql
SELECT parameter, value FROM nls_database_parameters
WHERE parameter IN ('NLS_CHARACTERSET', 'NLS_NCHAR_CHARACTERSET');
```
 
Base de 30 anos costuma estar em `WE8MSWIN1252` ou `WE8ISO8859P1`. Em `AL32UTF8`, `VARCHAR2(10)` guarda 10 **bytes** por padrão, e cada acento ocupa 2 → `ORA-12899`. Por isso `VARCHAR2(n CHAR)`.
 
### Acento quebrado: suspeitar de quem lê, não do dado
 
O CSV extraído estava correto em UTF-8; o `Get-Content` do PowerShell é que interpretou com outro encoding e mostrou `JosÃ©`.
 
A cadeia tem vários pontos onde o charset pode divergir: banco → `NLS_LANG` do cliente → encoding do arquivo → quem abre o arquivo → carga no PostgreSQL.
 
### Camadas
 
- **Raw:** fidelidade absoluta. Tudo como veio, sem `TRIM`, sem conversão. Permite reprocessar sem voltar ao Oracle.
- **Staging:** limpeza com rastro. Coluna raw ao lado da coluna limpa **só quando a transformação pode falhar ou perder informação**.
- **Rejeitados:** por **célula**, não por linha. Um pedido de R$ 50 mil não some por causa de uma data inválida num campo secundário. Rejeitar a linha inteira só quando o problema está na chave ou num campo sem o qual a linha perde sentido.
`status_validacao` com domínio fechado e `CHECK`.
 
### `-` no campo de valor vira nulo, não zero
 
Zero inventa um fato financeiro que a origem não afirmou — e entra na média, puxando para baixo. Nulo é ignorado por `AVG`. Conversão para zero só com regra de negócio formal.
 
---
 
## 15. ora2pg
 
### Ambiente (lições de configuração)
 
- Imagem Docker `georgmoser/ora2pg`, na mesma rede do container Oracle; host pelo `container_name`, nunca `localhost`
- **CRLF em arquivo lido por ferramenta Unix** gera erro que não menciona quebra de linha ("você precisa definir X", e X está definido). Diagnóstico: `cat -A` mostra `^M$`. Prevenção: `.gitattributes` com `eol=lf`
- Bind mount do Docker resolve caminho relativo ao diretório atual — mesmo erro do `inspect_csv.py`
- PowerShell continua linha com crase (`` ` ``), bash com `\`
- Definir `PG_VERSION` (padrão é 11)
- Conexão sem DBA: ativar `USER_GRANTS 1`
### O que funcionou bem
 
- `SHOW_REPORT --estimate_cost`: classificação (A-1 no treino) e estimativa em dias-homem. É o documento que justifica cronograma
- Tipos: `DATE` → `timestamp(0)` (hora preservada), `NUMBER(10)` → `bigint`, `NUMBER(p,s)` → `decimal(p,s)`
- `NUMBER(1)` com `CHECK IN (0,1)` preservado como `smallint`, não convertido a `boolean`
### O que falhou
 
- **Exportou 24 de 37 FKs**, sem erro nem aviso, num schema classificado como "migração automática"
- O conjunto de FKs exportadas **muda conforme as tabelas incluídas**
- Excluir tabela com `-e` **não exclui as FKs que apontam para ela** — o DDL falharia ao aplicar
- Causa raiz não determinada; suspeita não verificada: Oracle 23.26 muito recente para o ora2pg 25.0
- Tabela de teste esquecida (`dirty_data`) foi exportada junto
### Decisão
 
ora2pg para avaliação de esforço e rascunho de tabelas. **FKs geradas a partir do dicionário de dados** (`ALL_CONSTRAINTS`).
 
### Regra
 
**Toda migração termina com contagem de objetos na origem contra o destino** — tabelas, colunas, PKs, FKs, índices, checks. Cada diferença precisa de explicação.
 
---
 
## Perguntas para levar à empresa (acréscimos da Semana 2)
 
- Qual a versão do Oracle? (Limite de 30 caracteres em identificador até o 11g; compatibilidade com ora2pg)
- Qual o charset do banco?
- Qual a versão do PostgreSQL de destino? Já foi decidida?
- As colunas de data de alteração são mantidas por trigger ou pela aplicação? Existe `UPDATE` direto no banco?
- Existe janela de baixo movimento em que uma extração com cursor longo seja aceitável?
- Quais tabelas são de produção e quais são entulho (`_BACKUP`, `_OLD`, testes)?
- Um valor ausente em campo financeiro significa zero, não informado ou não aplicável?