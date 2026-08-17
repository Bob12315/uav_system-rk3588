from __future__ import annotations

from contracts.core.action import ActionContractRef, ActionDefinition, ActionRegistration


class ActionDefinitionCatalog:
    def __init__(self, definitions: tuple[ActionDefinition, ...]) -> None:
        by_name: dict[str, ActionDefinition] = {}
        by_ref: dict[ActionContractRef, ActionDefinition] = {}
        for definition in definitions:
            if definition.name in by_name or definition.contract_ref in by_ref:
                raise ValueError(f"duplicate Action definition: {definition.name}")
            by_name[definition.name] = definition
            by_ref[definition.contract_ref] = definition
        self._by_name = by_name
        self._by_ref = by_ref

    def all(self) -> tuple[ActionDefinition, ...]:
        return tuple(self._by_name[name] for name in sorted(self._by_name))

    def get(self, name: str) -> ActionDefinition | None:
        return self._by_name.get(name)

    def resolve(self, ref: ActionContractRef) -> ActionDefinition | None:
        return self._by_ref.get(ref)


class ActionRegistrationCatalog:
    def __init__(self, registrations: tuple[ActionRegistration, ...]) -> None:
        self._definitions = ActionDefinitionCatalog(tuple(item.definition for item in registrations))
        self._by_ref = {item.definition.contract_ref: item for item in registrations}

    @property
    def definitions(self) -> ActionDefinitionCatalog:
        return self._definitions

    def resolve(self, ref: ActionContractRef) -> ActionRegistration | None:
        return self._by_ref.get(ref)

    def all(self) -> tuple[ActionRegistration, ...]:
        return tuple(sorted(self._by_ref.values(), key=lambda item: item.definition.name))
