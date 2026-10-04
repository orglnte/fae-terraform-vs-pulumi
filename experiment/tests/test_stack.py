"""The definition, the pins every doc and image must agree on, and the
verifier's judgments, without a daemon. The stack end to end is
`python3 cli.py experiment smoke --full-gate`."""
import re
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from _ctx import _ROOT as ROOT

from fae import experiment as _experiment

from experiment import stack
from experiment.verifier import Check, Failed, World

EXP = ROOT / "experiment"
Terraform, Pulumi = (_experiment.definition().variant(v) for v in ("terraform", "pulumi"))


def arg(dockerfile, name):
    return re.search(rf"^ARG {name}=(\S+)$", Path(dockerfile).read_text(), re.M).group(1)


class TestTheDefinition(unittest.TestCase):
    def test_two_variants_two_scenarios(self):
        d = _experiment.definition()
        self.assertEqual(d.ids, ("pulumi", "terraform"))
        self.assertEqual(d.gate.arrangements, ("prod", "dev"))

    def test_each_variant_has_its_own_verify_and_agent_image(self):
        for v in (Terraform, Pulumi):
            self.assertTrue((Path(v.IMAGE_DIR) / "Dockerfile").is_file())
            self.assertTrue((Path(v.AGENT_IMAGE_DIR) / "Dockerfile").is_file())
            self.assertNotEqual(v.IMAGE_DIR, v.AGENT_IMAGE_DIR)

    def test_the_agent_writes_infra_only(self):
        for v in (Terraform, Pulumi):
            self.assertEqual(v.AUTHORING_SURFACE, ((), ("infra/",)))

    def test_one_infra_class_and_a_runner_per_tool(self):
        from fae.cell.variants import files
        for v, runner in ((Terraform, stack.Terraform), (Pulumi, stack.Pulumi)):
            self.assertIs(v.INFRA, stack.Stack)
            self.assertIs(stack.RUNNERS[v.FACTORS["tool"]], runner)
            self.assertEqual(files.problems(v), [])
            self.assertEqual(v.INPUTS["docs/" + v.FACTORS["tool"] + ".md"].name,
                             f"any.{v.FACTORS['tool']}.api.md")


class TestThePinsAgree(unittest.TestCase):
    """The docs promise versions; the stub pins them; both images install
    them. One version drifting makes the agent's code fail for the rig's
    reason."""

    def test_terraform(self):
        tf = EXP / "variants" / "terraform"
        stub = (tf / "seed" / "overlay" / "infra" / "main.tf").read_text()
        doc = (tf / "seed" / "any.terraform.api.md").read_text()
        for layer in ("verify", "agent"):
            f = tf / layer / "Dockerfile"
            self.assertIn(f'"kreuzwerker/docker", version = "{arg(f, "DOCKER_PROVIDER")}"', stub)
            self.assertIn(f'"hashicorp/random", version = "{arg(f, "RANDOM_PROVIDER")}"', stub)
            self.assertIn(f"`terraform` {arg(f, 'TERRAFORM_VERSION')}", doc)

    def test_pulumi(self):
        pu = EXP / "variants" / "pulumi"
        doc = (pu / "seed" / "any.pulumi.api.md").read_text()
        for layer in ("verify", "agent"):
            f = pu / layer / "Dockerfile"
            self.assertIn(f"`pulumi` {arg(f, 'PULUMI_VERSION')}", doc)
            self.assertIn(f"`pulumi_docker` {arg(f, 'PULUMI_DOCKER')}", doc)
            self.assertIn(f"`pulumi_random`\n  {arg(f, 'PULUMI_RANDOM')}", doc)

    def test_the_contract_names_the_images_the_daemon_holds(self):
        readme = (EXP / "task" / "skeleton" / "README.md").read_text()
        for img in (stack.APP_TAG, *stack.REGISTRY_IMAGES):
            self.assertIn(f"`{img}`", readme)
        self.assertIn(f"`{stack.LB_PORT}`", readme)


class TestTheRunners(unittest.TestCase):
    def _runner(self, cls, rc):
        d = Path(tempfile.mkdtemp())
        (d / "infra").mkdir()
        r = cls(d / "infra", "tcp://daemon:2375", d / "tool.log")
        done = mock.Mock(returncode=rc, stdout="", stderr="")
        return r, mock.patch.object(stack.subprocess, "run", return_value=done)

    def test_a_terraform_plan_with_changes_is_not_unchanged(self):
        r, run = self._runner(stack.Terraform, 2)
        with run as m:
            self.assertFalse(r.unchanged("prod", 3)[0])
        argv = m.call_args.args[0]
        self.assertIn("-detailed-exitcode", argv)
        self.assertEqual(argv[-4:], ["-var", "env=prod", "-var", "replicas=3"])
        self.assertEqual(m.call_args.kwargs["env"]["DOCKER_HOST"], "tcp://daemon:2375")

    def test_an_empty_terraform_plan_is_unchanged(self):
        r, run = self._runner(stack.Terraform, 0)
        with run:
            self.assertTrue(r.unchanged("prod", 3)[0])

    def test_pulumi_selects_the_env_stack_and_sets_both_inputs(self):
        r, run = self._runner(stack.Pulumi, 0)
        with run as m:
            self.assertTrue(r.apply("prod", 5)[0])
        argvs = [c.args[0] for c in m.call_args_list]
        self.assertEqual(argvs[0][:5], ["pulumi", "stack", "select", "--create", "prod"])
        self.assertIn(["pulumi", "config", "set", "replicas", "5", "--non-interactive"], argvs)
        self.assertEqual(argvs[-1][:2], ["pulumi", "up"])
        self.assertTrue(m.call_args.kwargs["env"]["PULUMI_BACKEND_URL"].startswith("file://"))


def container(name, ports=None, networks=(), env=()):
    return {"Name": f"/{name}", "Id": name, "Image": "sha",
            "NetworkSettings": {"Ports": ports or {}, "Networks": {n: {} for n in networks}},
            "Config": {"Env": list(env)}}


class TestTheJudgments(unittest.TestCase):
    def test_published_ports_are_read_from_the_bindings(self):
        c = container("lb", ports={"80/tcp": [{"HostIp": "0.0.0.0", "HostPort": "8080"},
                                              {"HostIp": "::", "HostPort": "8080"}],
                                   "443/tcp": None})
        self.assertEqual(World.published(c), ["8080"])
        self.assertEqual(World.published(container("db")), [])

    def _check(self, files):
        d = Path(tempfile.mkdtemp())
        for name, text in files.items():
            (d / name).parent.mkdir(parents=True, exist_ok=True)
            (d / name).write_text(text)
        return Check(None, None, None, d, lambda _: None)

    def test_a_password_written_in_the_source_fails(self):
        pw = "s3cretS3cretS3cret"
        db = container("db", env=[f"POSTGRES_PASSWORD={pw}"])
        with self.assertRaises(Failed) as e:
            self._check({"main.tf": f'password = "{pw}"\n'}).secret(db)
        self.assertEqual(e.exception.stage, "secret")
        self.assertIn("main.tf", e.exception.why)

    def test_a_short_password_fails(self):
        with self.assertRaises(Failed):
            self._check({}).secret(container("db", env=["POSTGRES_PASSWORD=short"]))

    def test_a_generated_password_passes(self):
        check = self._check({"main.tf": 'resource "random_password" "db" {}\n'})
        check.secret(container("db", env=["POSTGRES_PASSWORD=" + "x" * 24]))
        self.assertEqual(check.passed, ["secret"])


if __name__ == "__main__":
    unittest.main()
