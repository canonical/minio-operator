# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""Define Interface tests fixtures."""

import pytest
from interface_tester.plugin import InterfaceTester

from charm import MinIOOperator


@pytest.fixture
def interface_tester(interface_tester: InterfaceTester):
    """Fixture to configure the interface tester for MinIOOperator."""
    interface_tester.configure(charm_type=MinIOOperator)
    yield interface_tester
