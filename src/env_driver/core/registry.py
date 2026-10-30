"""Trusted environment-driver registry."""
from __future__ import annotations

from collections.abc import Callable

from .errors import RegistryError
from .driver import EnvironmentDriver
from .types import EnvironmentDefinition


DriverFactory = Callable[[], EnvironmentDriver]


class EnvironmentRegistry:
    def __init__(self) -> None:
        self._factories: dict[str, DriverFactory] = {}
        self._definitions: dict[str, EnvironmentDefinition] = {}

    def register(
        self,
        type_id: str,
        driver_type: type[EnvironmentDriver] | DriverFactory,
    ) -> None:
        if type_id in self._factories:
            raise RegistryError(f"environment type already registered: {type_id}")
        try:
            if isinstance(driver_type, type) and issubclass(driver_type, EnvironmentDriver):
                definition = driver_type.definition()
            else:
                probe = driver_type()
                if not isinstance(probe, EnvironmentDriver):
                    raise RegistryError("driver factory must return EnvironmentDriver")
                definition = probe.definition()
        except RegistryError:
            raise
        except (AttributeError, TypeError) as exc:
            raise RegistryError("registered driver must expose definition()") from exc
        if not isinstance(definition, EnvironmentDefinition):
            raise RegistryError("definition() must return EnvironmentDefinition")
        if definition.type_id != type_id:
            raise RegistryError(
                f"registration ID {type_id!r} does not match definition {definition.type_id!r}"
            )
        self._factories[type_id] = driver_type
        self._definitions[type_id] = definition

    def resolve(self, type_id: str) -> EnvironmentDriver:
        factory = self._factories.get(type_id)
        if factory is None:
            raise RegistryError(f"unknown environment type: {type_id}")
        driver = factory()
        if not isinstance(driver, EnvironmentDriver):
            raise RegistryError(f"factory for {type_id!r} did not return EnvironmentDriver")
        return driver

    def definitions(self) -> tuple[EnvironmentDefinition, ...]:
        return tuple(self._definitions.values())
