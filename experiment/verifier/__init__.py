"""Judges the stack an agent wrote: deploys it to an empty Docker daemon with
the agent's tool and checks it, in two scenarios (each attempt must pass both):

  prod  apply with env=prod, replicas=3 -> it serves through nginx -> only
        nginx is reachable from outside -> the database password is generated,
        not written in the source -> applying again changes nothing ->
        replicas=5 keeps the same database and its rows -> destroy leaves
        nothing behind
  dev   apply with env=dev, replicas=1 -> it serves, without Redis -> destroy
        leaves nothing behind

The first failed check ends the scenario and costs the agent the attempt. A
daemon that does not answer is the rig's fault: the attempt is refunded."""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from pathlib import Path

from fae import experiment as _experiment
from fae.cell.infra import secrunner
from fae.cell.infra.base import HookFailure
from fae.cell.verify import Verdict, Verifier

from .. import stack

HERE = Path(__file__).resolve().parent
SERVE_WAIT_S = 90
PROBES = 40


class Failed(Exception):
    def __init__(self, stage, why, charge=True):
        super().__init__(why)
        self.stage, self.why, self.charge = stage, why, charge


class World:
    """What the cell daemon holds, read through `docker inspect`."""

    def __init__(self, host):
        self.host = host
        self.image_ids = {}
        for img in (stack.APP_TAG, *stack.REGISTRY_IMAGES):
            p = stack.docker(host, "image", "inspect", "--format", "{{.Id}}", img)
            self.image_ids[p.stdout.strip()] = img

    def containers(self, stopped=False):
        ids = stack.docker(self.host, "ps", *(["-a"] if stopped else []), "-q").stdout.split()
        if not ids:
            return []
        return json.loads(stack.docker(self.host, "inspect", *ids).stdout or "[]")

    def by_image(self, img, stopped=False):
        return [c for c in self.containers(stopped) if self.image_ids.get(c["Image"]) == img]

    def one(self, img, what):
        cs = self.by_image(img)
        if len(cs) != 1:
            raise Failed("topology", f"expected one running {what} container ({img}), found {len(cs)}")
        return cs[0]

    @staticmethod
    def published(c):
        return sorted({b.get("HostPort") for bs in (c["NetworkSettings"]["Ports"] or {}).values()
                       for b in (bs or []) if b.get("HostPort")})

    @staticmethod
    def networks(c):
        return set(c["NetworkSettings"]["Networks"])

    @staticmethod
    def env(c, key):
        for kv in c["Config"]["Env"] or []:
            k, _, v = kv.partition("=")
            if k == key:
                return v
        return None


class Http:
    def __init__(self, host, port):
        self.base = f"http://{host}:{port}"

    def call(self, method, path, body=None):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.base + path, data=data, method=method,
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                return r.status, json.loads(r.read() or b"{}")
        except urllib.error.HTTPError as e:
            return e.code, {}
        except (urllib.error.URLError, OSError, ValueError) as e:
            return None, {"error": str(e)}

    def settle(self, replicas):
        """Wait until `replicas` distinct replicas have answered through the
        load balancer: apply may return before every container listens."""
        deadline = time.time() + SERVE_WAIT_S
        seen, last = set(), None
        while time.time() < deadline:
            code, body = self.call("GET", "/health")
            if code == 200:
                seen.add(body.get("replica"))
                if len(seen) >= replicas:
                    return
            else:
                last = code or body.get("error")
                time.sleep(0.5)
        raise Failed("serve", f"within {SERVE_WAIT_S}s of apply, {len(seen)} of {replicas} "
                              f"replica(s) answered GET /health through port {stack.LB_PORT} "
                              f"(last failure: {last})", charge=bool(seen))


class Check:
    def __init__(self, runner, world, http, artifacts, log):
        self.runner, self.world, self.http = runner, world, http
        self.artifacts, self.log = Path(artifacts), log
        self.passed = []

    def ok(self, name, detail=""):
        self.passed.append(name)
        self.log(f"ok   {name}{': ' + detail if detail else ''}")

    def apply(self, env, replicas):
        ok, tail = self.runner.apply(env, replicas)
        if not ok:
            raise Failed("apply", f"apply env={env} replicas={replicas} failed: {tail[-600:]}")
        self.ok("apply", f"env={env} replicas={replicas}")

    def serves(self, replicas, cache):
        if not self.world.by_image(stack.NGINX, stopped=True):
            raise Failed("serve", f"the stack has no nginx container ({stack.NGINX}): "
                                  f"nothing can serve port {stack.LB_PORT}")
        try:
            self.http.settle(replicas)
        except Failed as f:
            # nothing got through the port, yet nginx serves inside: the path is the rig's
            if not f.charge and self.nginx_answers_inside():
                raise Failed("rig", f"nginx answers GET /health inside its container, but port "
                                    f"{stack.LB_PORT} of the daemon refuses: the daemon's port "
                                    f"path, not the stack", charge=False) from f
            raise Failed(f.stage, f.why) from f
        seen = set()
        for _ in range(PROBES):
            code, body = self.http.call("GET", "/health")
            if code != 200:
                raise Failed("serve", f"GET /health answered {code or body.get('error')} "
                                      f"through the load balancer, after every replica had answered")
            if body.get("cache") is not cache:
                raise Failed("serve", f"a replica reports cache={body.get('cache')}, "
                                      f"expected {cache} (REDIS_URL {'set' if cache else 'unset'})")
            seen.add(body.get("replica"))
        apps = self.world.by_image(stack.APP_TAG)
        if len(apps) != replicas:
            raise Failed("replicas", f"expected {replicas} running app containers, found {len(apps)}")
        if len(seen) != replicas:
            raise Failed("replicas", f"{PROBES} requests reached {len(seen)} distinct replica(s), "
                                     f"expected {replicas}: the load balancer does not spread "
                                     f"across every replica")
        code, item = self.http.call("POST", "/items", {"name": "probe"})
        if code != 201:
            raise Failed("serve", f"POST /items answered {code}")
        code, got = self.http.call("GET", f"/items/{item['id']}")
        if code != 200 or got.get("name") != "probe":
            raise Failed("serve", f"GET /items/{item['id']} answered {code} {got}")
        self.ok("serve", f"{replicas} replica(s) behind the load balancer, cache={cache}")
        return item["id"]

    def nginx_answers_inside(self):
        lbs = self.world.by_image(stack.NGINX)
        if len(lbs) != 1:
            return False
        p = stack.docker(self.world.host, "exec", lbs[0]["Id"], "wget", "-qO-", "-T", "5",
                         "http://127.0.0.1:80/health")
        return p.returncode == 0 and '"ok": true' in p.stdout

    def private(self, cache):
        db = self.world.one(stack.POSTGRES, "Postgres")
        lb = self.world.one(stack.NGINX, "nginx")
        stores = [db] + ([self.world.one(stack.REDIS, "Redis")] if cache else [])
        for c in stores + self.world.by_image(stack.APP_TAG):
            if World.published(c):
                raise Failed("private", f"{c['Name'].lstrip('/')} publishes port(s) "
                                        f"{World.published(c)} on the daemon's host")
        if World.published(lb) != [str(stack.LB_PORT)]:
            raise Failed("private", f"nginx publishes {World.published(lb)}, "
                                    f"expected exactly [{stack.LB_PORT}]")
        for c in stores:
            shared = World.networks(lb) & World.networks(c)
            if shared:
                raise Failed("private", f"nginx shares network(s) {sorted(shared)} with "
                                        f"{c['Name'].lstrip('/')}: the stores must be reachable "
                                        f"from the app containers only")
        if not cache and self.world.by_image(stack.REDIS):
            raise Failed("topology", "a Redis container runs in env=dev")
        self.ok("private", "only nginx publishes a port; the stores share no network with it")
        return db

    def secret(self, db):
        pw = World.env(db, "POSTGRES_PASSWORD") or ""
        if len(pw) < 16:
            raise Failed("secret", f"the database password is {len(pw)} characters, expected >= 16")
        for p in sorted(self.artifacts.rglob("*")):
            if p.is_file() and ".terraform" not in p.parts and pw in p.read_text(errors="replace"):
                raise Failed("secret", f"the database password is written in "
                                       f"{p.relative_to(self.artifacts)}: generate it, keep it in state")
        self.ok("secret", "generated, not in the source")

    def unchanged(self, env, replicas):
        ok, tail = self.runner.unchanged(env, replicas)
        if not ok:
            raise Failed("idempotent", f"a second plan with the same inputs is not empty: {tail[-600:]}")
        self.ok("idempotent")

    def scale(self, db, item_id, replicas):
        self.apply("prod", replicas)
        self.serves(replicas, cache=True)
        after = self.world.one(stack.POSTGRES, "Postgres")
        if after["Id"] != db["Id"]:
            raise Failed("scale", f"replicas={replicas} replaced the database container")
        got = stack.docker(self.world.host, "exec", after["Id"], "psql", "-U", "app", "-d", "app",
                           "-tAc", f"SELECT name FROM items WHERE id = {int(item_id)}").stdout.strip()
        if got != "probe":
            raise Failed("scale", f"item {item_id} written before replicas={replicas} is gone "
                                  f"(read {got!r})")
        self.ok("scale", f"replicas={replicas}, same database, rows kept")

    def destroy(self, env, replicas):
        ok, tail = self.runner.destroy(env, replicas)
        if not ok:
            raise Failed("destroy", f"destroy failed: {tail[-600:]}")
        cs, vs, ns = stack.residue(self.world.host)
        if cs or vs or ns:
            raise Failed("destroy", f"destroy left {len(cs)} container(s), {len(vs)} volume(s), "
                                    f"{len(ns)} network(s)")
        gone = [i for i in (stack.APP_TAG, *stack.REGISTRY_IMAGES)
                if stack.docker(self.world.host, "image", "inspect", i).returncode]
        if gone:
            raise Failed("destroy", f"destroy removed image(s) {gone}: the images are given, not the stack's")
        self.ok("destroy", "nothing left")


class StackVerifier(Verifier):
    IMAGE_DIR = HERE
    FILES = ("verify.log", "tool.log")
    INFRA_PREFIXES = {"container": stack.DindSidecar.PREFIX}

    def verify(self, ctx):
        t0 = time.time()
        out = Path(ctx.out)
        variant = _experiment.current().variant(ctx.variant)
        arrangement = ctx.arrangement or "prod"
        workdir = secrunner.fresh_copy(Path(ctx.artifacts), out) / "infra"
        logf = (out / "verify.log").open("w")

        def log(line):
            logf.write(line + "\n")
            logf.flush()

        def verdict(ok, stage="", why="", charge=True, passed=()):
            log(f"checks passed: {', '.join(passed) or 'none'}")
            return Verdict(ok=ok, stage=stage, why=why, charge=charge,
                           metrics={"arrangement": arrangement, "passed": list(passed),
                                    "failed": stage or None},
                           seconds=time.time() - t0)

        try:
            return self._run(ctx, variant, arrangement, workdir, out, log, verdict)
        finally:
            logf.close()

    @staticmethod
    def _run(ctx, variant, arrangement, workdir, out, log, verdict):
        try:
            host = stack.fresh_daemon(ctx.cid, log)
        except HookFailure as e:
            return verdict(False, "infra", str(e), charge=False)
        if not workdir.is_dir():
            return verdict(False, "layout", "no infra/ directory in the workspace")
        check = Check(stack.RUNNERS[variant.FACTORS["tool"]](workdir, host, out / "tool.log"), World(host),
                      Http(stack.lb_host(ctx.cid), stack.LB_PORT), Path(ctx.artifacts) / "infra", log)
        log(f"arrangement {arrangement}, {variant.LABEL}, daemon {host}")
        try:
            if arrangement == "prod":
                check.apply("prod", 3)
                item_id = check.serves(3, cache=True)
                db = check.private(cache=True)
                check.secret(db)
                check.unchanged("prod", 3)
                check.scale(db, item_id, 5)
                check.destroy("prod", 5)
            else:
                check.apply("dev", 1)
                check.serves(1, cache=False)
                db = check.private(cache=False)
                check.secret(db)
                check.destroy("dev", 1)
        except Failed as f:
            state = stack.snapshot(host)
            log(f"FAIL[{f.stage}] {f.why}\ncontainers at the failure:\n{state}")
            return verdict(False, f.stage, f"{f.why}\ncontainers at the failure:\n{state}",
                           charge=f.charge, passed=check.passed)
        finally:
            stack.clean(host, log)
        return verdict(True, passed=check.passed)
