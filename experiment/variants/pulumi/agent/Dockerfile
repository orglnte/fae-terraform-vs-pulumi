# The Pulumi arm's agent layer over the agents' base: the same CLI, SDKs and
# plugins the verifier uses.
ARG BASE
FROM $BASE
USER root
ARG PULUMI_VERSION=3.265.0
ARG PULUMI_DOCKER=5.2.0
ARG PULUMI_RANDOM=4.21.2
ENV PULUMI_HOME=/opt/pulumi-home PULUMI_SKIP_UPDATE_CHECK=true \
    PULUMI_DISABLE_AUTOMATIC_PLUGIN_ACQUISITION=true PATH=/opt/pulumi:$PATH
RUN arch="$(dpkg --print-architecture)"; case "$arch" in amd64) pa=x64 ;; *) pa="$arch" ;; esac; \
    curl -fsSL "https://get.pulumi.com/releases/sdk/pulumi-v${PULUMI_VERSION}-linux-${pa}.tar.gz" | tar -xz -C /opt \
    && python3 -m pip install --no-cache-dir --break-system-packages "pulumi==${PULUMI_VERSION}" "pulumi_docker==${PULUMI_DOCKER}" "pulumi_random==${PULUMI_RANDOM}" \
    && pulumi plugin install resource docker "v${PULUMI_DOCKER}" \
    && pulumi plugin install resource random "v${PULUMI_RANDOM}" \
    && chmod -R a+rwX "$PULUMI_HOME" \
    && pulumi version && python3 -c "import pulumi, pulumi_docker, pulumi_random"
USER node
