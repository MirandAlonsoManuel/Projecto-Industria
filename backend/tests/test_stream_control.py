"""Mensaje de control update_roi: validación, versiones y respuestas (sin FastAPI)."""

from __future__ import annotations

import json

import pytest

from app.services.stream_control import (
    ROI_OUT_OF_FRAME,
    StreamControl,
    roi_to_dict,
)


def _update(control: StreamControl, roi, **extra) -> dict:
    return control.handle_text(json.dumps({"type": "update_roi", "roi": roi, **extra}))


def _box(x1=10, y1=20, x2=50, y2=60) -> dict:
    return {"x1": x1, "y1": y1, "x2": x2, "y2": y2}


def test_new_control_starts_with_full_frame():
    control = StreamControl()
    assert control.config.roi is None
    assert control.config.version == 0
    assert control.startup_notice is None


def test_valid_update_is_confirmed_with_active_configuration():
    control = StreamControl()
    control.set_frame_size(640, 480)
    reply = _update(control, _box(), request_id="r1")
    assert reply == {
        "type": "roi_updated",
        "ok": True,
        "request_id": "r1",
        "roi": _box(),
        "roi_version": 1,
        "frame_width": 640,
        "frame_height": 480,
    }
    assert control.config.roi == (10, 20, 50, 60)


def test_corners_in_any_order_are_normalized():
    control = StreamControl()
    reply = _update(control, _box(x1=50, y1=60, x2=10, y2=20))
    assert reply["roi"] == _box(10, 20, 50, 60)


def test_integral_floats_are_accepted_fractional_are_not():
    control = StreamControl()
    assert _update(control, _box(x1=10.0))["type"] == "roi_updated"
    reply = _update(control, _box(x1=10.5))
    assert reply["error"] == "INVALID_ROI"


def test_consecutive_updates_increase_version():
    control = StreamControl()
    versions = [_update(control, _box(x2=50 + i))["roi_version"] for i in range(3)]
    assert versions == [1, 2, 3]


def test_null_roi_returns_to_full_frame():
    control = StreamControl()
    _update(control, _box())
    reply = _update(control, None)
    assert reply["type"] == "roi_updated"
    assert reply["roi"] is None
    assert reply["roi_version"] == 2
    assert control.config.roi is None


@pytest.mark.parametrize(
    "roi",
    [
        _box(x1=-1),  # negativa
        _box(x1=10, x2=10),  # ancho cero
        _box(y1=5, y2=5),  # alto cero
        {"x1": 1, "y1": 2, "x2": 3},  # falta una clave
        {**_box(), "extra": 1},  # clave de más
        {**_box(), "x1": "10"},  # texto en vez de número
        {**_box(), "x1": True},  # booleano
        {**_box(), "y2": None},
        "10,10,50,50",  # no es objeto
        [10, 10, 50, 50],
    ],
)
def test_invalid_roi_is_recoverable_and_keeps_last_valid_config(roi):
    control = StreamControl()
    _update(control, _box())  # última ROI válida
    reply = _update(control, roi, request_id=7)
    assert reply["type"] == "error"
    assert reply["error"] == "INVALID_ROI"
    assert reply["recoverable"] is True
    assert reply["request_id"] == 7
    assert reply["description"]
    # El error informa la configuración que sigue activa
    assert reply["roi"] == _box()
    assert reply["roi_version"] == 1
    assert control.config.roi == (10, 20, 50, 60)
    assert control.config.version == 1


def test_roi_outside_known_frame_is_rejected_and_config_kept():
    control = StreamControl()
    control.set_frame_size(100, 80)
    _update(control, _box(0, 0, 100, 80))  # justo en el borde: válida
    reply = _update(control, _box(90, 0, 120, 30))
    assert reply["error"] == ROI_OUT_OF_FRAME
    assert reply["recoverable"] is True
    assert reply["roi"] == _box(0, 0, 100, 80)
    assert control.config.version == 1


def test_roi_larger_than_unknown_frame_is_accepted_until_a_frame_arrives():
    # Antes del primer frame solo se valida formato; el tamaño se revisa por frame.
    control = StreamControl()
    assert _update(control, _box(0, 0, 5000, 5000))["type"] == "roi_updated"


@pytest.mark.parametrize(
    "text, code",
    [
        ("no es json", "INVALID_MESSAGE"),
        ("[1, 2]", "INVALID_MESSAGE"),
        ('"hola"', "INVALID_MESSAGE"),
        ('{"type": "update_roi"}', "INVALID_MESSAGE"),  # falta roi
        ('{"type": "otra_cosa"}', "UNKNOWN_MESSAGE_TYPE"),
        ("{}", "UNKNOWN_MESSAGE_TYPE"),
        ("x" * 5000, "INVALID_MESSAGE"),
    ],
)
def test_malformed_control_messages_get_a_recoverable_error(text, code):
    control = StreamControl()
    reply = control.handle_text(text)
    assert reply["type"] == "error"
    assert reply["error"] == code
    assert reply["recoverable"] is True
    assert control.config.version == 0


def test_request_id_is_echoed_only_when_simple():
    control = StreamControl()
    assert _update(control, None, request_id={"a": 1})["request_id"] is None
    assert _update(control, None, request_id=True)["request_id"] is None
    assert len(_update(control, None, request_id="z" * 500)["request_id"]) == 64


# -- ROI inicial (query params) ---------------------------------------------------


def test_initial_roi_string_format_is_converted_to_corners():
    control = StreamControl()
    control.set_initial_roi(roi="10,20,30,40")  # x,y,ancho,alto
    assert control.config.roi == (10, 20, 40, 60)
    assert control.config.version == 0
    assert control.startup_notice is None


def test_initial_roi_two_points():
    control = StreamControl()
    control.set_initial_roi(x1=40, y1=60, x2=10, y2=20)
    assert control.config.roi == (10, 20, 40, 60)


def test_initial_roi_absent_means_full_frame():
    control = StreamControl()
    control.set_initial_roi()
    assert control.config.roi is None
    assert control.startup_notice is None


@pytest.mark.parametrize(
    "args",
    [{"roi": "-1,0,5,5"}, {"roi": "abc"}, {"x1": 1, "y1": 2, "x2": 3}, {"roi": "1,1,5,5", "x1": 1, "y1": 1, "x2": 5, "y2": 5}],
)
def test_invalid_initial_roi_does_not_close_it_leaves_a_notice(args):
    control = StreamControl()
    control.set_initial_roi(**args)
    notice = control.startup_notice
    assert notice["type"] == "error"
    assert notice["error"] == "INVALID_ROI"
    assert notice["recoverable"] is True
    assert notice["roi"] is None  # arranca con el frame completo
    assert control.config.roi is None


def test_roi_to_dict_roundtrip():
    assert roi_to_dict(None) is None
    assert roi_to_dict((1, 2, 3, 4)) == {"x1": 1, "y1": 2, "x2": 3, "y2": 4}
