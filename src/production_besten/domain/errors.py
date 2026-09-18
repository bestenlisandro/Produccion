class DomainError(Exception):
    """Base error for expected business failures."""


class EntityNotFound(DomainError):
    """The entity does not exist in the active organization."""


class InvalidExecutionState(DomainError):
    """The operation cannot accept a remaining estimate in its current state."""


class RevisionConflict(DomainError):
    """The caller based the command on an obsolete remaining revision."""


class InvalidEstimate(DomainError):
    """The estimate or its resource dimensions is inconsistent."""


class ExecutionAlreadyActive(DomainError):
    """An active execution already exists for the required operation."""


class ExecutionAlreadyCompleted(DomainError):
    """The requested phase or operation was already completed."""


class GateBlocked(DomainError):
    """One or more generic operation gates are not satisfied."""


class StructuralAvailabilityConflict(DomainError):
    """A real person or resource is structurally unavailable."""


class InvalidProductDefinition(DomainError):
    """A productive definition command violates a business invariant."""


class ProductDefinitionConflict(DomainError):
    """The command conflicts with a concurrent or already persisted definition."""


class PrecedenceCycle(DomainError):
    """An operation precedence would make the productive graph cyclic."""


class IdempotencyConflict(DomainError):
    """An idempotency key was reused with incompatible command data."""


class InvalidSchedulingInput(DomainError):
    """A scheduling request or frozen base is invalid."""


class SchedulingBaseStale(DomainError):
    """The requested frozen base is no longer the current schedulable state."""
