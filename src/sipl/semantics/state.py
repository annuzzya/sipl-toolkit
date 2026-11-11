"""Стан виконання st: Var -> Z (часткова функція) та оновлення ∇."""
from __future__ import annotations

from typing import Iterable, Iterator, Mapping, Optional


class State(Mapping):
    """Незмінний стан. Порядок змінних — порядок першого присвоювання (як у підручнику)."""

    __slots__ = ("_d",)

    def __init__(self, values: Optional[Mapping[str, int]] = None):
        object.__setattr__(self, "_d", dict(values or {}))

    def __getitem__(self, name: str) -> int:
        return self._d[name]

    def __iter__(self) -> Iterator[str]:
        return iter(self._d)

    def __len__(self) -> int:
        return len(self._d)

    def __setattr__(self, key, value):  # noqa: D401
        raise AttributeError("State незмінний")

    def __eq__(self, other) -> bool:
        if isinstance(other, State):
            return self._d == other._d
        if isinstance(other, Mapping):
            return self._d == dict(other)
        return NotImplemented

    def __hash__(self) -> int:
        return hash(tuple(sorted(self._d.items())))

    def update(self, name: str, value: int) -> "State":
        """st∇[name ↦ value] — новий стан; решта змінних не змінюється."""
        d = dict(self._d)
        d[name] = value
        return State(d)

    def to_dict(self) -> dict:
        return dict(self._d)

    def __str__(self) -> str:
        return format_state(self)

    def __repr__(self) -> str:
        return f"State({self._d!r})"


def format_state(state: Mapping[str, int]) -> str:
    """`[N ↦ 3, S ↦ 0]` — нотація курсу."""
    return "[" + ", ".join(f"{k} ↦ {v}" for k, v in state.items()) + "]"


def parse_state(text: str) -> State:
    """Розбір рядка `N=3, X=5` (також `N=3;X=5`, `[N ↦ 3]`) у стан."""
    cleaned = text.strip().strip("[]").replace("↦", "=").replace(";", ",")
    values: dict[str, int] = {}
    for part in cleaned.split(","):
        part = part.strip()
        if not part:
            continue
        if "=" not in part:
            raise ValueError(f"очікувалось 'ім'я=число', отримано {part!r}")
        name, value = (x.strip() for x in part.split("=", 1))
        if not name or not (name[0].isalpha() or name[0] == "_") or not all(c.isalnum() or c == "_" for c in name):
            raise ValueError(f"некоректне ім'я змінної {name!r}")
        try:
            values[name] = int(value)
        except ValueError:
            raise ValueError(f"значення змінної {name} має бути цілим числом, отримано {value!r}") from None
    return State(values)
