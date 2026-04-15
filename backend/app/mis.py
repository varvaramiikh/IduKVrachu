from abc import ABC, abstractmethod
from datetime import datetime, timedelta
import random
from typing import List, Optional
from pydantic import BaseModel

class Slot(BaseModel):
    datetime: datetime
    is_available: bool
    mis_external_id: str

class MISProvider(ABC):
    @abstractmethod
    async def get_slots(self, clinic_id: str, service_id: str, date_from: datetime, date_to: datetime) -> List[Slot]:
        pass

    @abstractmethod
    async def create_appointment(self, payload: dict) -> str:
        pass

    @abstractmethod
    async def cancel_appointment(self, external_id: str) -> bool:
        pass

    @abstractmethod
    async def reschedule_appointment(self, external_id: str, new_slot_datetime: datetime) -> bool:
        pass

class MockMISProvider(MISProvider):
    async def get_slots(self, clinic_id: str, service_id: str, date_from: datetime, date_to: datetime) -> List[Slot]:
        slots = []
        current_date = date_from.replace(hour=9, minute=0, second=0, microsecond=0)
        
        while current_date <= date_to:
            if current_date.weekday() < 5: # Mon-Fri
                for hour in range(9, 18):
                    for minute in [0, 30]:
                        slot_time = current_date.replace(hour=hour, minute=minute)
                        if slot_time > datetime.now():
                            slots.append(Slot(
                                datetime=slot_time,
                                is_available=random.random() > 0.3,
                                mis_external_id=f"slot_{slot_time.strftime('%Y%m%d%H%M')}_{clinic_id}_{service_id}"
                            ))
            current_date += timedelta(days=1)
        return slots

    async def create_appointment(self, payload: dict) -> str:
        # 5% chance of failure
        if random.random() < 0.05:
            raise Exception("Слот уже занят в МИС")
        return f"ext_app_{random.randint(100000, 999999)}"

    async def cancel_appointment(self, external_id: str) -> bool:
        return True

    async def reschedule_appointment(self, external_id: str, new_slot_datetime: datetime) -> bool:
        return True

mis_provider = MockMISProvider()
