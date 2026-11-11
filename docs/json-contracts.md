# JSON-контракти (`schema_version: 1`)

Усі команди з `--json` пишуть один JSON-об'єкт у stdout. Спільні поля: `schema_version` (=1), `command`, `ok`.
Код завершення процесу дублює результат (див. README). Ключі зі `schema_version: 1` не змінюються в межах 0.x без збільшення версії схеми.

**Позиція (`span`)**: `{start, end, line, col, end_line, end_col}` — зміщення в символах, рядки/стовпці з 1.

| Команда | Додаткові поля |
|---------|----------------|
| `check` | `file`, `inputs[]`, `assigned[]`, `variables[]`, `diagnostics[]` (`code`, `severity`, `message`, `span`, `hint`). При помилці `ok:false` і діагностика `E-…` |
| `parse` | `file`, `ast` (вузли: `node`, `span`, дочірні поля) |
| `tree` | `file`, `leaf_count`, `tree` (вузол: `symbol`, `kind` terminal/nonterminal, `span`, `source`, `rule`, `children[]`; листок: `leaf_index`, `token_kind`) |
| `term` | `term` (рядок), `term_tree` (JSON-терм: `term` = seq/assign/while/if/skip/sup/const/denom…), `rewrite_steps` (з `--explain`) |
| `eval` | `initial_state{}`, `defined`, `state{}` або `null`, `steps`, `trace_truncated`, `error` (`code`, `message`) або `null`, `trace[]` (з `--trace`: `index`, `depth`, `rule`, `term`, `before`, `after`, `note`, `loop_head`) |
| `prove` | `name`, `mode`, `verdict` (proved/bounded/refuted), `assumptions[]`, `limits[]`, `steps[]` (`id`, `title`, `kind` exact/bounded/empirical/info, `status` ok/fail/unknown, `details[]`, `counterexample`) |

JSON-терм можна подати назад: `sipl eval --term term.json --state "x=4"`.

## Специфікація доведення (`--spec`)
```json
{
  "name": "…", "params": ["n"],
  "pre": "N = n and n > 0", "post": "2*S = 3*n*(n+1)",
  "inputs": {"N": "n"},
  "invariant": "…", "variant": "N",
  "closed_form": {"N": "n-k", "S": "3*k*(k+1)/2", "T": "3*k"}, "iterations": "n",
  "domain": 8, "max_steps": 100000
}
```
Обов'язкові: `pre`, `post` і щонайменше `invariant` або `closed_form` (+ `iterations`). Невідоме поле → код 2.
