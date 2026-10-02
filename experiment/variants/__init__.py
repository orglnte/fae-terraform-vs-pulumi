"""Two ways to write the same stack: Terraform (HCL) and Pulumi (Python).
The task, the checks and the Docker daemon the stack is deployed to are the
same for both; only the tool differs."""
from __future__ import annotations

from pathlib import Path

from fae.cell import image as _image
from fae.cell.variants import base
from fae.cell.variants.base import Variant, cksum

from .. import stack


class StackVariant(Variant):
    CONDITIONS = ("apidocs",)
    AUTHORING_SURFACE = ((), ("infra/",))
    INFRA_PREFIXES = {"container": stack.DindSidecar.PREFIX}
    RUNNER = None
    # host loopback ports of the sidecar's API and its load balancer, per cell
    API_BASE = 27000

    @classmethod
    def infra_identities(cls, cid):
        return [("container", stack.DindSidecar.name_for(cid))]

    def ports(self):
        api = self.API_BASE + 2 * (cksum(self.cid) % 800)
        return api, api + 1

    def sidecar(self):
        api, lb = self.ports()
        return stack.StackSidecar(self.cid, api, lb, stack.LB_PORT, stack.DIND_IMAGE, "",
                                  self.log, self.TECH, network=self.network())

    def infra_ok(self):
        if not base._ok(["docker", "info"]):
            self.log("HALT[infra]: docker unreachable")
            return False
        for img in (stack.DIND_IMAGE, *stack.REGISTRY_IMAGES):
            if not base._ok(["docker", "image", "inspect", img]):
                self.log(f"HALT[infra]: image {img} not present — docker pull {img}")
                return False
        try:
            _image.ensure("iac-app", stack.APP_DIR, log=self.log)
        except RuntimeError as e:
            self.log(f"HALT[infra]: {e}")
            return False
        return True

    def infra_alive(self):
        return self.sidecar().answers()

    def author_setup(self):
        self.sidecar().ensure()
        return {}

    def author_teardown(self):
        self.sidecar().remove()

    def verify_setup(self, ctx, env):
        return {"DOCKER_HOST": stack.fresh_daemon(ctx.cid, self.log)}

    def verify_teardown(self, ctx, env):
        stack.clean(stack.daemon_url(ctx.cid), self.log)


HERE = Path(__file__).resolve().parent


class Terraform(StackVariant):
    ARM = TECH = "terraform"
    LABEL = "Terraform"
    IMAGE_DIR = HERE / "terraform" / "verify"
    AGENT_IMAGE_DIR = HERE / "terraform" / "agent"
    SEED = HERE / "terraform" / "seed"
    RUNNER = stack.Terraform


class Pulumi(StackVariant):
    ARM = TECH = "pulumi"
    LABEL = "Pulumi"
    IMAGE_DIR = HERE / "pulumi" / "verify"
    AGENT_IMAGE_DIR = HERE / "pulumi" / "agent"
    SEED = HERE / "pulumi" / "seed"
    RUNNER = stack.Pulumi


VARIANTS = (Terraform, Pulumi)
