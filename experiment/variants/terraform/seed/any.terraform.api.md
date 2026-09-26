# Terraform

Write the stack as a Terraform root module in `infra/`.

## What is installed

- `terraform` 1.16.4
- two providers, and only these, mirrored locally (there is no network):
  `kreuzwerker/docker` 4.6.0 and `hashicorp/random` 3.9.1. `infra/main.tf`
  already pins both.

## The interface

- **Inputs**: the variables `env` (string, default `"dev"`) and `replicas`
  (number, default `1`), declared in `infra/main.tf`.
- **The daemon**: `provider "docker" {}` with no `host`: it reads
  `DOCKER_HOST`.
- **State**: local. Declare no backend.

## What the verifier runs, in `infra/`

```sh
terraform init -input=false
terraform apply -auto-approve -var env=prod -var replicas=3
terraform plan -detailed-exitcode -var env=prod -var replicas=3   # must exit 0: no changes
terraform apply -auto-approve -var env=prod -var replicas=5
terraform destroy -auto-approve -var env=prod -var replicas=5
```

and, on a fresh copy of your files, the same with `env=dev replicas=1`
(no second plan, no scaling).

## Checking your work here

`terraform init` and `terraform validate` work offline in `infra/`.
`plan` and `apply` need the daemon, which only the verifier has.
