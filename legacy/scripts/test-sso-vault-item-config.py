#!/usr/bin/env python3
"""W3-1/D2 contract: both slot brokers select the seed-bearing SSO item."""
from pathlib import Path
import sys

path = Path(sys.argv[1])
source = path.read_text()
expected = "SSO_VAULT_ITEM=Authentik Spike User"
legacy = "SSO_VAULT_ITEM=Aikumi Connect"
interpolated = "SSO_VAULT_ITEM=${"
occurrences = source.count(expected)
legacy_occurrences = source.count(legacy)
interpolated_occurrences = source.count(interpolated)
print(f"explicit_item_occurrences: {occurrences}")
print(f"legacy_item_occurrences: {legacy_occurrences}")
print(f"interpolated_item_occurrences: {interpolated_occurrences}")
if occurrences != 2 or legacy_occurrences or interpolated_occurrences:
    raise SystemExit(1)
print("PASS both slot brokers explicitly select the seed-bearing SSO item")
