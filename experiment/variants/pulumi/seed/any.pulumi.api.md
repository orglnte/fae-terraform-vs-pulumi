# Pulumi

Write the stack as a Pulumi program in Python, in `infra/`.

## What is installed

- the `pulumi` CLI 3.265.0
- three Python packages, and only these (there is no network, and nothing
  to install): `pulumi` 3.265.0, `pulumi_docker` 5.2.0 and `pulumi_random`
  4.21.2, with their provider plugins.

## The interface

- **The project**: `infra/Pulumi.yaml` (given: `runtime: python`, no
  virtualenv) and `infra/__main__.py`, which may import modules of yours
  from `infra/`.
- **Inputs**: the config keys `env` (default `"dev"`) and `replicas`
  (integer, default `1`), read with `pulumi.Config()`; the stub reads both.
- **The daemon**: the default docker provider reads `DOCKER_HOST`; configure
  no host.
- **State**: the verifier sets the backend (a local file) and the secrets
  passphrase. The stack is named after `env`.

## What the verifier runs, in `infra/`

```sh
pulumi stack select --create prod
pulumi config set env prod
pulumi config set replicas 3
pulumi up --yes --skip-preview
pulumi preview --expect-no-changes          # must pass: no changes
pulumi config set replicas 5
pulumi up --yes --skip-preview
pulumi destroy --yes --skip-preview
```

and, on a fresh copy of your files, the same with a `dev` stack, `env=dev`,
`replicas=1` (no preview, no scaling).

## Checking your work here

`python3 -m py_compile infra/__main__.py` and importing the packages work
here. `pulumi preview` and `pulumi up` need the daemon, which only the
verifier has.
