"""Environment-driver framework errors."""


class EnvironmentFrameworkError(RuntimeError):
    """Base class for environment framework failures."""


class DefinitionError(EnvironmentFrameworkError):
    """A static environment definition or execution plan is invalid."""


class RegistryError(EnvironmentFrameworkError):
    """An environment type cannot be registered or resolved."""


class ConfigurationError(EnvironmentFrameworkError):
    """The effective configuration is invalid."""


class ContextClosedError(EnvironmentFrameworkError):
    """A control context was used after its lifetime ended."""


class StepCancelledError(EnvironmentFrameworkError):
    """A step honored a cooperative cancellation request."""


class StepStateUnknownError(EnvironmentFrameworkError):
    """A step may have changed external state but its result is unknown."""
