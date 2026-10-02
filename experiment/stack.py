"""What both variants share: the Docker daemon each cell deploys to (a
docker-in-docker container of its own), the images preloaded into it, and one
runner per tool that applies, re-plans and destroys the agent's stack."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

from fae.cell import image as _image
from fae.cell.infra.dind import DindSidecar
from fae.cell.variants import base

HERE = Path(__file__).resolve().parent
APP_DIR = HERE / "app"
APP_TAG = "iac-app:1"
DIND_IMAGE = "docker:27-dind"
POSTGRES = "postgres:16-alpine"
REDIS = "redis:7-alpine"
NGINX = "nginx:1.30.5-alpine"
REGISTRY_IMAGES = (POSTGRES, REDIS, NGINX)
LB_PORT = 8080
DEFAULT_NETWORKS = {"bridge", "host", "none"}


def app_image():
    """The app's content-addressed tag on the host daemon."""
    return _image.tag("iac-app", APP_DIR)


def daemon_url(cid):
    """The cell daemon as the verify container reaches it, on the cell network."""
    return f"tcp://{DindSidecar.name_for(cid)}:2375"


def lb_host(cid):
    return DindSidecar.name_for(cid)


def docker(host, *argv, timeout=120, stdin=None):
    return subprocess.run(["docker", "-H", host, *argv], capture_output=True,
                          text=True, timeout=timeout, input=stdin)


def load_images(host, log):
    """Every image a stack uses, present in the daemon at `host`: loaded
    from the host daemon (a stream between the two), never pulled. The app
    is re-tagged to the name the contract promises."""
    want = [*REGISTRY_IMAGES, app_image()]
    have = set(docker(host, "images", "--format", "{{.Repository}}:{{.Tag}}").stdout.split())
    missing = [i for i in want if i not in have]
    if missing:
        save = subprocess.Popen(["docker", "save", *missing], stdout=subprocess.PIPE,
                                stderr=subprocess.DEVNULL)
        load = subprocess.run(["docker", "-H", host, "load"], stdin=save.stdout,
                              capture_output=True)
        save.stdout.close()
        save.wait()
        if save.returncode or load.returncode:
            raise base.HookFailure(f"HALT[infra]: loading {missing} into {host} failed")
        log(f"loaded into the cell daemon: {' '.join(missing)}")
    if docker(host, "tag", app_image(), APP_TAG).returncode:
        raise base.HookFailure(f"HALT[infra]: tagging {APP_TAG} in {host} failed")


def residue(host):
    """(containers, volumes, networks) the daemon holds beyond its defaults."""
    cs = docker(host, "ps", "-aq").stdout.split()
    vs = docker(host, "volume", "ls", "-q").stdout.split()
    ns = [n for n in docker(host, "network", "ls", "--format", "{{.Name}}").stdout.split()
          if n not in DEFAULT_NETWORKS]
    return cs, vs, ns


def snapshot(host):
    """Every container's name and state, plus the log tail of each one that
    is not running: what a failed check's message carries."""
    rows = docker(host, "ps", "-a", "--format", "{{.Names}}\t{{.Status}}").stdout.strip()
    lines = [f"  {r}" for r in rows.splitlines()] or ["  (no containers)"]
    for row in rows.splitlines():
        name, _, status = row.partition("\t")
        if not status.startswith("Up"):
            tail = docker(host, "logs", "--tail", "15", name)
            lines.append(f"  --- {name} log:")
            lines += [f"    {l}" for l in (tail.stdout + tail.stderr).strip().splitlines()]
    return "\n".join(lines)


def clean(host, log):
    """Remove every container, volume and network in the cell daemon."""
    cs, vs, ns = residue(host)
    if cs:
        docker(host, "rm", "-f", "-v", *cs)
    if vs:
        docker(host, "volume", "rm", "-f", *vs)
    if ns:
        docker(host, "network", "rm", *ns)
    if cs or vs or ns:
        log(f"cleared {len(cs)} container(s), {len(vs)} volume(s), {len(ns)} network(s)")


def fresh_daemon(cid, log):
    """The cell daemon emptied and holding every image: the state each
    arrangement starts from. Returns its URL."""
    host = daemon_url(cid)
    if not base.daemon_answers(["docker", "-H", host, "version"]):
        raise base.HookFailure(f"HALT[infra]: the cell daemon {host} does not answer")
    clean(host, log)
    load_images(host, log)
    return host


class StackSidecar(DindSidecar):
    """The cell's daemon, seeded with every image a stack uses."""

    def seed(self):
        load_images(self.api, self.log)


# --- the tools: one runner per arm, same verbs --------------------------------

class Runner:
    """Drives one tool over the authored project in `workdir` against the
    daemon at `host`. Each verb returns (ok, the tail of its output)."""

    TIMEOUT_S = 600

    def __init__(self, workdir, host, log_path):
        self.dir = Path(workdir)
        self.host = host
        self.log_path = Path(log_path)

    def env(self):
        return dict(os.environ, DOCKER_HOST=self.host, HOME=str(self.dir.parent / ".home"))

    def run(self, argv, ok_codes=(0,)):
        with self.log_path.open("a") as log:
            log.write(f"\n$ {' '.join(argv)}\n")
            log.flush()
            try:
                p = subprocess.run(argv, cwd=self.dir, env=self.env(), capture_output=True,
                                   text=True, timeout=self.TIMEOUT_S)
            except subprocess.TimeoutExpired:
                log.write(f"timed out after {self.TIMEOUT_S}s\n")
                return False, f"timed out after {self.TIMEOUT_S}s", None
            log.write(p.stdout + p.stderr)
        return p.returncode in ok_codes, (p.stdout + p.stderr).strip()[-1500:], p.returncode


class Terraform(Runner):
    def _vars(self, env, replicas):
        return ["-var", f"env={env}", "-var", f"replicas={replicas}"]

    def apply(self, env, replicas):
        ok, tail, _ = self.run(["terraform", "init", "-input=false", "-no-color"])
        if not ok:
            return False, tail
        ok, tail, _ = self.run(["terraform", "apply", "-auto-approve", "-input=false",
                                "-no-color", *self._vars(env, replicas)])
        return ok, tail

    def unchanged(self, env, replicas):
        ok, tail, rc = self.run(["terraform", "plan", "-detailed-exitcode", "-input=false",
                                 "-no-color", *self._vars(env, replicas)])
        return rc == 0, tail

    def destroy(self, env, replicas):
        ok, tail, _ = self.run(["terraform", "destroy", "-auto-approve", "-input=false",
                                "-no-color", *self._vars(env, replicas)])
        return ok, tail


class Pulumi(Runner):
    PASSPHRASE = "fae-terraform-vs-pulumi"

    def env(self):
        state = self.dir.parent / ".pulumi-state"
        state.mkdir(exist_ok=True)
        return dict(super().env(), PULUMI_BACKEND_URL=f"file://{state}",
                    PULUMI_CONFIG_PASSPHRASE=self.PASSPHRASE)

    def _configure(self, env, replicas):
        for argv in (["pulumi", "stack", "select", "--create", env, "--non-interactive"],
                     ["pulumi", "config", "set", "env", env, "--non-interactive"],
                     ["pulumi", "config", "set", "replicas", str(replicas), "--non-interactive"]):
            ok, tail, _ = self.run(argv)
            if not ok:
                return False, tail
        return True, ""

    def apply(self, env, replicas):
        ok, tail = self._configure(env, replicas)
        if not ok:
            return False, tail
        ok, tail, _ = self.run(["pulumi", "up", "--yes", "--skip-preview", "--non-interactive",
                                "--color", "never"])
        return ok, tail

    def unchanged(self, env, replicas):
        ok, tail = self._configure(env, replicas)
        if not ok:
            return False, tail
        ok, tail, _ = self.run(["pulumi", "preview", "--expect-no-changes", "--non-interactive",
                                "--color", "never"])
        return ok, tail

    def destroy(self, env, replicas):
        ok, tail = self._configure(env, replicas)
        if not ok:
            return False, tail
        ok, tail, _ = self.run(["pulumi", "destroy", "--yes", "--skip-preview",
                                "--non-interactive", "--color", "never"])
        return ok, tail
