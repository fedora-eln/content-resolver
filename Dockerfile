FROM registry.fedoraproject.org/fedora:44

# Configure DNF to skip ldconfig in container builds
# An error is caused because DNF is trying to update the dynamic linker cache in the container.
RUN echo "tsflags=nodocs" >> /etc/dnf/dnf.conf && \
    echo "install_weak_deps=False" >> /etc/dnf/dnf.conf

RUN dnf -y update fedora-gpg-keys && \
    dnf -y install git python3-jinja2 python3-koji python3-yaml python3-libdnf5 && \
    dnf clean all && \
    rm -rf /var/cache/dnf

WORKDIR /workspace
