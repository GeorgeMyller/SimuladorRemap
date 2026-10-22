"""Construção rápida dos contratos do hot path (``EngineState``, ``SensorReadings``).

``fast_constructor(cls)`` devolve uma função equivalente a ``cls.model_construct(**values)``
quando TODOS os campos são passados (o caso do passo físico): mesmo ``__dict__`` na ordem
dos campos, mesmo ``__pydantic_fields_set__``, sem extra nem atributos privados. Custa
cerca de um terço do ``model_construct`` genérico do pydantic (feature 003, T025).

Qualquer caso fora disso (campos em falta ou a mais, alias, ``model_post_init``,
atributos privados, ``extra="allow"``) cai no ``model_construct`` original.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from pydantic import BaseModel

__all__ = ["fast_constructor"]


def _eligible(cls: type[BaseModel]) -> bool:
    fields = cls.__pydantic_fields__
    return (
        not getattr(cls, "__pydantic_root_model__", False)
        and not getattr(cls, "__pydantic_post_init__", None)
        and not cls.__private_attributes__
        and cls.model_config.get("extra") != "allow"
        and all(f.alias is None or f.alias == name for name, f in fields.items())
    )


def fast_constructor[M: BaseModel](cls: type[M]) -> Callable[..., M]:
    """Construtor sem validação equivalente a ``model_construct`` com todos os campos."""
    if not _eligible(cls):
        return cls.model_construct
    order = tuple(cls.__pydantic_fields__)
    count = len(order)
    new = cls.__new__
    set_attr = object.__setattr__
    slow = cls.model_construct

    def build(**values: Any) -> M:
        if len(values) != count:
            return slow(**values)
        try:
            data = {name: values[name] for name in order}
        except KeyError:
            return slow(**values)
        model = new(cls)
        set_attr(model, "__dict__", data)
        set_attr(model, "__pydantic_fields_set__", set(order))
        set_attr(model, "__pydantic_extra__", None)
        set_attr(model, "__pydantic_private__", None)
        return model

    return build
