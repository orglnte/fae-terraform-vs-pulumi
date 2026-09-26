import pulumi

config = pulumi.Config()
env = config.get("env") or "dev"
replicas = config.get_int("replicas") or 1

# TODO: the stack README.md describes.
