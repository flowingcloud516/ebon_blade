"""Trusted environment-type registry."""
from __future__ import annotations

from collections.abc import Callable

from .errors import RegistryError
from .model import EnvironmentModel
from .types import EnvironmentDefinition


ModelFactory = Callable[[], EnvironmentModel]


class EnvironmentRegistry:
    def __init__(self) -> None:
        self._factories: dict[str, ModelFactory] = {}
        self._definitions: dict[str, EnvironmentDefinition] = {}

    def register(self, type_id: str, model_type: type[EnvironmentModel] | ModelFactory) -> None:
        if type_id in self._factories:
            raise RegistryError(f"environment type already registered: {type_id}")
        try:
            if isinstance(model_type, type) and issubclass(model_type, EnvironmentModel):
                definition = model_type.definition()
            else:
                probe = model_type()
                if not isinstance(probe, EnvironmentModel):
                    raise RegistryError("model factory must return EnvironmentModel")
                definition = probe.definition()
        except RegistryError:
            raise
        except (AttributeError, TypeError) as exc:
            raise RegistryError("registered model must expose definition()") from exc
        if not isinstance(definition, EnvironmentDefinition):
            raise RegistryError("definition() must return EnvironmentDefinition")
        if definition.type_id != type_id:
            raise RegistryError(
                f"registration ID {type_id!r} does not match definition {definition.type_id!r}"
            )
        self._factories[type_id] = model_type
        self._definitions[type_id] = definition

    def resolve(self, type_id: str) -> EnvironmentModel:
        factory = self._factories.get(type_id)
        if factory is None:
            raise RegistryError(f"unknown environment type: {type_id}")
        model = factory()
        if not isinstance(model, EnvironmentModel):
            raise RegistryError(f"factory for {type_id!r} did not return EnvironmentModel")
        return model

    def definitions(self) -> tuple[EnvironmentDefinition, ...]:
        return tuple(self._definitions.values())
