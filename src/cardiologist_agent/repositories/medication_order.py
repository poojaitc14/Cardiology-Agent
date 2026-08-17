from __future__ import annotations

from abc import ABC, abstractmethod

from cardiologist_agent.domain.enums import AuthorizationStatus
from cardiologist_agent.domain.patient import MedicationOrder


class MedicationOrderRepository(ABC):
    @abstractmethod
    async def get_active_orders(self, patient_id: str) -> list[MedicationOrder]: ...

    @abstractmethod
    async def authorization_source_status(self) -> AuthorizationStatus: ...


class UnavailableMedicationOrderRepository(MedicationOrderRepository):
    async def get_active_orders(self, patient_id: str) -> list[MedicationOrder]:
        return []

    async def authorization_source_status(self) -> AuthorizationStatus:
        return AuthorizationStatus.UNAVAILABLE


class JsonMedicationOrderRepository(MedicationOrderRepository):
    """Loads approved orders from a separate JSON file when supplied."""

    def __init__(self, orders: list[MedicationOrder]) -> None:
        self._by_patient: dict[str, list[MedicationOrder]] = {}
        for order in orders:
            self._by_patient.setdefault(order.patient_id, []).append(order)

    async def get_active_orders(self, patient_id: str) -> list[MedicationOrder]:
        return [
            o
            for o in self._by_patient.get(patient_id, [])
            if o.authorization_status.value == "SIGNED"
        ]

    async def authorization_source_status(self) -> AuthorizationStatus:
        return AuthorizationStatus.SIGNED if self._by_patient else AuthorizationStatus.UNAVAILABLE
