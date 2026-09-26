import pulumi
import pulumi_docker as docker
import pulumi_random as random

config = pulumi.Config()
env = config.get("env") or "dev"
replicas = config.get_int("replicas") or 1
prod = env == "prod"


def image(key, name):
    return docker.RemoteImage(key, name=name, keep_locally=True)


app_image = image("app", "iac-app:1")
postgres_image = image("postgres", "postgres:16-alpine")
redis_image = image("redis", "redis:7-alpine")
nginx_image = image("nginx", "nginx:1.30.5-alpine")

password = random.RandomPassword("db", length=24, special=False)
front = docker.Network("front", name=f"stack-front-{env}")
back = docker.Network("back", name=f"stack-back-{env}", internal=True)
volume = docker.Volume("db", name=f"stack-db-{env}")


def on(*networks):
    return [docker.ContainerNetworksAdvancedArgs(name=n.name) for n in networks]


def healthy(*test):
    return docker.ContainerHealthcheckArgs(tests=list(test), interval="1s", timeout="3s",
                                           retries=30)


db = docker.Container(
    "db",
    name=f"stack-db-{env}",
    image=postgres_image.image_id,
    envs=["POSTGRES_USER=app", "POSTGRES_DB=app",
          password.result.apply(lambda p: f"POSTGRES_PASSWORD={p}")],
    networks_advanced=on(back),
    volumes=[docker.ContainerVolumeArgs(volume_name=volume.name,
                                        container_path="/var/lib/postgresql/data")],
    healthcheck=healthy("CMD-SHELL", "pg_isready -h 127.0.0.1 -U app -d app"),
    wait=True, wait_timeout=60)

stores = [db]
app_env = [pulumi.Output.all(password.result, db.name).apply(
    lambda a: f"DATABASE_URL=postgresql://app:{a[0]}@{a[1]}:5432/app")]
if prod:
    cache = docker.Container(
        "redis",
        name=f"stack-redis-{env}",
        image=redis_image.image_id,
        networks_advanced=on(back),
        healthcheck=healthy("CMD", "redis-cli", "ping"),
        wait=True, wait_timeout=60)
    stores.append(cache)
    app_env.append(cache.name.apply(lambda n: f"REDIS_URL=redis://{n}:6379/0"))

apps = [docker.Container(
            f"app-{i}",
            name=f"stack-app-{env}-{i}",
            image=app_image.image_id,
            envs=app_env,
            networks_advanced=on(front, back),
            opts=pulumi.ResourceOptions(depends_on=stores))
        for i in range(replicas)]

nginx_conf = pulumi.Output.all(*[a.name for a in apps]).apply(
    lambda names: "upstream app {\n"
                  + "".join(f"  server {n}:8000;\n" for n in names)
                  + "}\nserver {\n  listen 80;\n  location / {\n    proxy_pass http://app;\n  }\n}\n")

docker.Container(
    "lb",
    name=f"stack-lb-{env}",
    image=nginx_image.image_id,
    networks_advanced=on(front),
    ports=[docker.ContainerPortArgs(internal=80, external=8080)],
    uploads=[docker.ContainerUploadArgs(file="/etc/nginx/conf.d/default.conf",
                                        content=nginx_conf)])
