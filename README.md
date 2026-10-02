# fae-terraform-vs-pulumi

An example experiment built with [FAE](https://github.com/orglnte/fae):
coding agents write the same Docker stack in Terraform and in Pulumi, and the
experiment measures which tool they get right in fewer attempts, which check
each tool fails most, and how much code each takes.

## The stack

Every agent gets the same brief ([`README.md`](experiment/task/skeleton/README.md)
in its workspace) and writes it with one tool, against a Docker daemon of its
own:

1. an app (`iac-app:1`, given) as `replicas` containers behind **nginx**,
   the only container that publishes a port;
2. **Postgres** with its data on a volume, and **Redis** in `prod` only,
   both on a network nginx is not on;
3. a **generated** database password, never written in the source;
4. two inputs, `env` (`dev`/`prod`) and `replicas`.

## The checks

Each attempt deploys the stack twice, on an empty daemon each time:

| scenario | check | what it catches |
|---|---|---|
| prod | apply `env=prod replicas=3`; 3 replicas answer through nginx; an item round-trips | a stack that does not work |
| prod | only nginx publishes a port; the stores share no network with it | a stack that is not private |
| prod | the password is 16+ characters and in none of the agent's files | a hard-coded secret |
| prod | a second plan with the same inputs is empty | code that is not idempotent, e.g. a password from Python's `secrets` instead of `random_password` |
| prod | `replicas=5`: 5 replicas, the same Postgres container, the item still there | a change that recreates the database |
| prod | destroy leaves no container, network or volume, and every image | leaks |
| dev | `env=dev replicas=1`: one replica, no Redis, private, then destroy | the conditional |

The first failed check ends the attempt, and its message is the agent's
feedback for the next one. Ten attempts per cell.

## Run it

You need Python 3.11+ with `typer` and `ujson`, docker, and
[FAE](https://github.com/orglnte/fae) cloned beside this repo (`../fae`, or
set `FAE_DIR`).

```sh
docker pull docker:27-dind && docker pull postgres:16-alpine \
  && docker pull redis:7-alpine && docker pull nginx:1.30.5-alpine
python3 cli.py experiment init                # writes fae.toml, the machine-local config, then offers the walk
python3 cli.py experiment check               # everything in place, each tool's image built (--walk: step by step)
python3 cli.py experiment smoke --full-gate   # each tool's reference solution, both scenarios
```

```
=== SMOKE SUMMARY ===
  ok   terraform      GREEN at attempt 1
  ok   pulumi         GREEN at attempt 1
  PIPELINE OK on every variant.
```

One real agent, once its CLI is logged in (see the FAE README):

```sh
python3 cli.py cell spawn sonnet terraform --rep 1
python3 cli.py fleet-status
```

The comparison: five cells per tool for each model, then the table.

```sh
python3 cli.py conduct queue-add sonnet --matrix --reps 5
python3 cli.py conduct queue-add haiku --matrix --reps 5
python3 cli.py conduct run -n 2 --per-model 1      # foreground; Ctrl-C detaches, cells keep running
python3 cli.py results score
```

## What is where

```
experiment/
├── __init__.py            the definition: two variants, two scenarios, the verifier
├── stack.py               the cell's Docker daemon (`Stack`, the infra class), the images in it, one runner per tool
├── app/                   the service the stack deploys
├── task/
│   ├── T1.PROMPT.md       the brief (it becomes TODO.md)
│   └── skeleton/README.md the stack's requirements, the same for both tools
├── variants/
│   ├── terraform.toml     a variant: what the agent gets, how it is judged, its infra
│   ├── pulumi.toml
│   ├── terraform/
│   │   ├── seed/          the stub main.tf, the tool doc, the reference solution
│   │   ├── verify/        the verifier's Terraform layer: CLI and providers, offline
│   │   └── agent/         the agent's Terraform layer: the same, nothing else
│   └── pulumi/            the same four for Pulumi (Python)
├── verifier/              the checks above, and the verifier's base image
└── tests/                 python3 -m unittest discover -s experiment/tests
```

Nothing an agent writes runs on the host: the agent works in a sealed
container with no network and no Docker daemon (it can `terraform validate`
or compile its Python, not deploy), and the verifier deploys into a
docker-in-docker daemon that belongs to the cell and is emptied before every
scenario. An agent's image holds its own tool only: a Terraform agent has
no Pulumi, and the other way round.
