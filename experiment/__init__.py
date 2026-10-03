"""Terraform vs Pulumi: coding agents write the same local Docker stack with
each tool; the experiment counts the attempts each needs to get it right.
The two variants are `variants/terraform.toml` and `variants/pulumi.toml`."""
from __future__ import annotations

from fae.experiment import Gate

NAME = "iac"


GATE = Gate(("prod", "dev"),
            feedback_note="Each attempt deploys your stack twice, as prod and as dev; "
                          "both must pass.")


def verifier_class():
    from .verifier import StackVerifier
    return StackVerifier
