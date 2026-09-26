"""Terraform vs Pulumi: coding agents write the same local Docker stack with
each tool; the experiment counts the attempts each needs to get it right."""
from __future__ import annotations

from fae.cell.experiment import Gate

NAME = "iac"


def variant_classes():
    from .variants import VARIANTS
    return VARIANTS


# (variant, condition) -> (the tool doc the agent is handed, its minimum lines)
SEED_DOCS = {("terraform", "apidocs"): ("any.terraform.api.md", 30),
             ("pulumi", "apidocs"): ("any.pulumi.api.md", 30)}

GATE = Gate(("prod", "dev"),
            feedback_note="Each attempt deploys your stack twice, as prod and as dev; "
                          "both must pass.")


def verifier_class():
    from .verifier import StackVerifier
    return StackVerifier
