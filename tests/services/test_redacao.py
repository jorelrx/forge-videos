from __future__ import annotations

import pytest

from forge.services.redacao import Redactor


def test_event_redactor_masks_exact_secret_values():
    redactor = Redactor(secrets=["sk-live-123"])
    assert redactor.clean({
        "message": "falhou com sk-live-123", "api_key": "another",
        "nested": ["safe", "token sk-live-123"],
    }) == {
        "message": "falhou com [REDACTED]", "api_key": "[REDACTED]",
        "nested": ["safe", "token [REDACTED]"],
    }


def test_event_redactor_masks_credential_keys():
    redactor = Redactor(secrets=[])
    assert redactor.clean({
        "token": "abc", "authorization": "bearer x", "password": "secret",
        "safe": "ok",
    }) == {
        "token": "[REDACTED]", "authorization": "[REDACTED]",
        "password": "[REDACTED]", "safe": "ok",
    }


def test_event_redactor_is_recursive():
    redactor = Redactor(secrets=["top-secret"])
    assert redactor.clean({
        "outer": {"inner": {"token": "top-secret", "value": "ok"}},
    }) == {
        "outer": {"inner": {"token": "[REDACTED]", "value": "ok"}},
    }


def test_event_redactor_does_not_modify_safe_values():
    redactor = Redactor(secrets=["secret"])
    data = {"message": "hello", "count": 42, "name": "world"}
    assert redactor.clean(data) == data


def test_event_redactor_masks_substring_in_message():
    redactor = Redactor(secrets=["sk-abc"])
    assert redactor.clean({
        "message": "key is sk-abc here",
    }) == {
        "message": "key is [REDACTED] here",
    }


def test_event_redactor_handles_none_gracefully():
    redactor = Redactor(secrets=["secret"])
    assert redactor.clean({"message": None, "count": 1}) == {
        "message": None, "count": 1,
    }


def test_event_redactor_handles_list_of_strings():
    redactor = Redactor(secrets=["bad"])
    assert redactor.clean({
        "items": ["good", "bad", "ugly"],
    }) == {
        "items": ["good", "[REDACTED]", "ugly"],
    }