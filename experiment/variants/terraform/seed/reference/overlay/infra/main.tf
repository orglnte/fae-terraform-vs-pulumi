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

locals {
  prod = var.env == "prod"
}

data "docker_image" "app" { name = "iac-app:1" }
data "docker_image" "postgres" { name = "postgres:16-alpine" }
data "docker_image" "redis" { name = "redis:7-alpine" }
data "docker_image" "nginx" { name = "nginx:1.30.5-alpine" }

resource "random_password" "db" {
  length  = 24
  special = false
}

resource "docker_network" "front" {
  name = "stack-front-${var.env}"
}

resource "docker_network" "back" {
  name     = "stack-back-${var.env}"
  internal = true
}

resource "docker_volume" "db" {
  name = "stack-db-${var.env}"
}

resource "docker_container" "db" {
  name  = "stack-db-${var.env}"
  image = data.docker_image.postgres.id
  env = [
    "POSTGRES_USER=app",
    "POSTGRES_DB=app",
    "POSTGRES_PASSWORD=${random_password.db.result}",
  ]
  networks_advanced {
    name = docker_network.back.name
  }
  volumes {
    volume_name    = docker_volume.db.name
    container_path = "/var/lib/postgresql/data"
  }
  healthcheck {
    test     = ["CMD-SHELL", "pg_isready -h 127.0.0.1 -U app -d app"]
    interval = "1s"
    timeout  = "3s"
    retries  = 30
  }
  wait         = true
  wait_timeout = 60
}

resource "docker_container" "redis" {
  count = local.prod ? 1 : 0
  name  = "stack-redis-${var.env}"
  image = data.docker_image.redis.id
  networks_advanced {
    name = docker_network.back.name
  }
  healthcheck {
    test     = ["CMD", "redis-cli", "ping"]
    interval = "1s"
    timeout  = "3s"
    retries  = 30
  }
  wait         = true
  wait_timeout = 60
}

resource "docker_container" "app" {
  count = var.replicas
  name  = "stack-app-${var.env}-${count.index}"
  image = data.docker_image.app.id
  env = compact([
    "DATABASE_URL=postgresql://app:${random_password.db.result}@${docker_container.db.name}:5432/app",
    local.prod ? "REDIS_URL=redis://${docker_container.redis[0].name}:6379/0" : "",
  ])
  networks_advanced {
    name = docker_network.front.name
  }
  networks_advanced {
    name = docker_network.back.name
  }
  depends_on = [docker_container.db, docker_container.redis]
}

resource "docker_container" "lb" {
  name  = "stack-lb-${var.env}"
  image = data.docker_image.nginx.id
  networks_advanced {
    name = docker_network.front.name
  }
  ports {
    internal = 80
    external = 8080
  }
  upload {
    file    = "/etc/nginx/conf.d/default.conf"
    content = <<-EOT
      upstream app {
      %{for c in docker_container.app~}
        server ${c.name}:8000;
      %{endfor~}
      }
      server {
        listen 80;
        location / {
          proxy_pass http://app;
        }
      }
    EOT
  }
}
