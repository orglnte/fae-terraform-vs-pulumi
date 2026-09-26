terraform {
  required_providers {
    docker = { source = "kreuzwerker/docker", version = "4.6.0" }
    random = { source = "hashicorp/random", version = "3.9.1" }
  }
}

provider "docker" {}

variable "env" {
  type    = string
  default = "dev"
}

variable "replicas" {
  type    = number
  default = 1
}

# TODO: the stack README.md describes.
