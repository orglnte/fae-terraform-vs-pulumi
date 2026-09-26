# The Terraform arm's agent layer over the agents' base: the same CLI and
# providers the verifier uses, so the agent can init and validate offline.
ARG BASE
FROM $BASE
USER root
ARG TERRAFORM_VERSION=1.16.4
ARG DOCKER_PROVIDER=4.6.0
ARG RANDOM_PROVIDER=3.9.1
RUN arch="$(dpkg --print-architecture)" \
    && curl -fsSL -o /tmp/tf.zip "https://releases.hashicorp.com/terraform/${TERRAFORM_VERSION}/terraform_${TERRAFORM_VERSION}_linux_${arch}.zip" \
    && python3 -c "import zipfile; zipfile.ZipFile('/tmp/tf.zip').extract('terraform', '/usr/local/bin')" \
    && chmod 755 /usr/local/bin/terraform && rm /tmp/tf.zip \
    && mkdir /tmp/mirror \
    && printf 'terraform {\n  required_providers {\n    docker = { source = "kreuzwerker/docker", version = "%s" }\n    random = { source = "hashicorp/random", version = "%s" }\n  }\n}\n' \
         "$DOCKER_PROVIDER" "$RANDOM_PROVIDER" > /tmp/mirror/main.tf \
    && terraform -chdir=/tmp/mirror providers mirror /opt/terraform-mirror \
    && rm -rf /tmp/mirror \
    && printf 'provider_installation {\n  filesystem_mirror {\n    path = "/opt/terraform-mirror"\n  }\n}\n' > /opt/terraform.rc \
    && chmod -R a+rX /opt/terraform-mirror /opt/terraform.rc \
    && terraform version
ENV TF_CLI_CONFIG_FILE=/opt/terraform.rc CHECKPOINT_DISABLE=1
USER node
