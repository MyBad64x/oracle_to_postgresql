# Dia 10: desenho da camada staging

## Resultado da reextração

A tabela `dirty_data` foi extraída novamente sem conversão, `TRIM` ou
normalização:

- [CSV raw](../data/extracted/dirty_data_repeat.csv)
- [Parquet raw](../data/extracted/dirty_data_repeat.parquet)

Os dois arquivos têm 5 linhas. Os acentos foram preservados como UTF-8:
`José da Conceição` e `João`.

No CSV, `NULL` do Oracle aparece como campo vazio porque o formato não
distingue visualmente `NULL` de string vazia. No Parquet, o mesmo valor aparece
como `null`, preservando melhor essa distinção.

## Classificação dos problemas

| Campo | Exemplo | Tratamento na staging | Destino |
| --- | --- | --- | --- |
| `nome` | `MARIA   SILVA  ` | Remover espaços nas extremidades; preservar o raw na camada anterior | coluna limpa |
| `nome` | `  ana paula` | Remover espaços nas extremidades; decidir regra de caixa | coluna limpa |
| `codigo` | `ATIVO     ` | `TRIM`; validar domínio | coluna limpa |
| `codigo` | `NULL` | Preservar como nulo | coluna limpa |
| `valor` | `1.234,56` | Interpretar locale brasileiro e converter para decimal | coluna limpa + status |
| `valor` | `1234.56` | Aceitar formato decimal alternativo após validação | coluna limpa + status |
| `valor` | `R$ 500,00` | Remover símbolo, normalizar separadores e converter | coluna limpa + status |
| `valor` | `-` | Não converter automaticamente; usar `NULL` até existir regra de negócio | célula rejeitada |
| `data_texto` | `15/03/2024` | Tentar máscara conhecida | coluna limpa + status |
| `data_texto` | `2024-03-15` | Tentar máscara ISO | coluna limpa + status |
| `data_texto` | `20240315` | Tentar máscara compacta | coluna limpa + status |
| `data_texto` | `15-MAR-24` | Converter com idioma explícito, nunca depender da sessão | coluna limpa + status |
| `data_texto` | `31/02/2023` | Manter a linha e deixar a data limpa como `NULL` | célula rejeitada |

## Camadas

### Raw

Mantém o arquivo extraído fiel ao Oracle. Não faz `TRIM`, conversão de moeda,
conversão de data ou correção de caixa. Essa camada permite reprocessar os
dados sem consultar o Oracle novamente.

### Staging

Cria colunas limpas. O par raw + limpo só deve existir quando a transformação
pode perder informação ou falhar. Uma transformação reversível e trivial, como
`TRIM`, não precisa duplicar a coluna: o valor original continua disponível na
camada raw.

Exemplos em que o par é justificável:

- `valor_raw` e `valor_decimal`
- `data_texto_raw` e `data_normalizada`
- texto monetário ou data que pode falhar na conversão

Exemplos em que não é necessário duplicar:

- `codigo` após um `TRIM` simples
- `nome` após remover espaços nas extremidades

Toda célula transformada recebe `status_validacao` e, quando necessário,
`motivo_rejeicao`.

Nenhum valor inválido deve desaparecer. Quando uma coluna secundária falhar,
a linha entra na staging com essa coluna limpa como `NULL`, e a rejeição é
registrada por célula. Assim um pedido de alto valor não desaparece apenas
porque uma data auxiliar está inválida.

O domínio de `status_validacao` é fechado:

- `OK`: valor já estava válido e não precisou de ajuste
- `CONVERTIDO`: valor foi convertido ou normalizado com sucesso
- `NULO_ORIGEM`: origem trouxe `NULL` ou string vazia
- `REJEITADO`: valor não pôde ser convertido ou validado

Exemplo de constraint para staging:

```sql
CHECK (status_validacao IN ('OK', 'CONVERTIDO', 'NULO_ORIGEM', 'REJEITADO'))
```

### Rejeitados

Registra uma célula problemática, não necessariamente uma linha inteira:
tabela, chave da linha, coluna, valor raw, erro e data do processamento. A
linha inteira só deve ser rejeitada quando o problema estiver na chave ou em um
campo essencial sem o qual o registro não tem significado, como pedido sem
cliente ou item sem pedido.

## Decisão sobre `-` em `valor`

`-` deve virar **nulo por padrão**, não zero. Tecnicamente não há como saber se
significa ausência de informação, valor não aplicável, não informado ou zero.
Converter para zero inventaria um fato financeiro que a origem não afirmou.

A conversão para zero só deve acontecer depois de uma regra de negócio formal,
validada com o responsável pelo domínio. Até lá, o valor raw deve ser
preservado, a coluna limpa deve ficar nula e a linha deve ser marcada para
revisão.