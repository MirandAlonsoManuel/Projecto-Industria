"""
Pruebas unitarias del FrameSlot (política de último frame).

Ejecutar:
    cd backend
    pytest tests/test_frame_slot.py -v
"""

import asyncio

import numpy as np
import pytest

from app.services.frame_slot import FrameSlot, FrameSlotClosed


def _frame(value: int = 0) -> np.ndarray:
    return np.full((1, 1, 3), value, dtype=np.uint8)


def test_slot_entrega_solo_el_frame_mas_reciente():
    async def scenario():
        slot = FrameSlot()
        for i in range(5):
            slot.publish(_frame(i), float(i))
        return await slot.next(0)

    packet = asyncio.run(scenario())

    assert packet.seq == 5
    assert packet.captured_at == 4.0


def test_slot_espera_hasta_que_haya_un_frame_mas_nuevo():
    async def scenario():
        slot = FrameSlot()
        slot.publish(_frame(), 1.0)
        waiter = asyncio.create_task(slot.next(after_seq=1))
        await asyncio.sleep(0)
        assert not waiter.done()
        slot.publish(_frame(), 2.0)
        return await waiter

    assert asyncio.run(scenario()).seq == 2


def test_slot_despierta_a_varios_consumidores():
    async def scenario():
        slot = FrameSlot()
        waiters = [asyncio.create_task(slot.next(0)) for _ in range(2)]
        await asyncio.sleep(0)
        slot.publish(_frame(), 1.0)
        return await asyncio.gather(*waiters)

    assert [p.seq for p in asyncio.run(scenario())] == [1, 1]


def test_slot_cerrado_despierta_al_consumidor_con_su_codigo():
    async def scenario():
        slot = FrameSlot()
        waiter = asyncio.create_task(slot.next(0))
        await asyncio.sleep(0)
        slot.close("fin", code="CAMERA_NO_FRAMES")
        await waiter

    with pytest.raises(FrameSlotClosed) as info:
        asyncio.run(scenario())

    assert str(info.value) == "fin"
    assert info.value.code == "CAMERA_NO_FRAMES"


def test_slot_cerrado_entrega_el_ultimo_frame_pendiente():
    async def scenario():
        slot = FrameSlot()
        slot.publish(_frame(), 1.0)
        slot.close("fin")
        return await slot.next(0)

    assert asyncio.run(scenario()).seq == 1
