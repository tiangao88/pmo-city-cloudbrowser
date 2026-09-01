import pytest

from cloudbrowser.deployment import InstanceNamespace


def test_instance_namespace_derives_every_persistent_name():
    first = InstanceNamespace("cloudbrowser-alpha")
    second = InstanceNamespace("cloudbrowser-beta")

    assert first.network != second.network
    assert first.volume("router-state") != second.volume("router-state")
    assert first.volume("downloads") != second.volume("downloads")
    assert first.secret_namespace != second.secret_namespace
    assert first.network.startswith("cloudbrowser-alpha-")
    assert first.volume("router-state").startswith("cloudbrowser-alpha-")


def test_instance_namespace_rejects_unsafe_or_ambiguous_ids():
    for value in ("", "CloudBrowser", "../other", "one/two", "a_b"):
        with pytest.raises(ValueError):
            InstanceNamespace(value)
