#!/bin/bash
# Fresh qualification host only. No application, credentials or business admission.
set -euo pipefail
umask 077
install -d -m 0700 /etc/epm/bootstrap /var/lib/epm-bootstrap
exec 9>/etc/epm/bootstrap/os.lock
flock -n 9
if test -f /var/lib/epm-bootstrap/os-ready; then
  exit 0
fi
. /etc/os-release
test "$ID" = ubuntu
test "$VERSION_ID" = 24.04
test "$(uname -m)" = x86_64
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y e2fsprogs quota util-linux \
  apparmor apparmor-utils nftables gcc libseccomp-dev python3-venv python3-pip \
  pkg-config ca-certificates curl xz-utils
@@PINNED_DOCKER_PACKAGES@@
systemctl disable --now unattended-upgrades.service apt-daily.timer apt-daily-upgrade.timer || true
printf 'quota_v2\nbr_netfilter\n' >/etc/modules-load.d/epm-h02.conf
printf 'net.bridge.bridge-nf-call-iptables=1\nnet.bridge.bridge-nf-call-ip6tables=1\n' >/etc/sysctl.d/90-epm-h02.conf
if ! modprobe quota_v2; then
  apt-get install -y linux-modules-extra-"$(uname -r)"
  modprobe quota_v2
fi
modprobe br_netfilter
sysctl -p /etc/sysctl.d/90-epm-h02.conf
# Prevent Docker from starting after reboot unless the retained data mount exists.
install -d -m 0755 /etc/systemd/system/docker.service.d
printf '[Unit]\nRequires=srv-epm-data.mount\nAfter=srv-epm-data.mount\n' >/etc/systemd/system/docker.service.d/epm-data.conf
systemctl stop docker.service docker.socket
systemctl daemon-reload
printf 'OS prerequisites installed; explicit empty-disk initialization still required.\n' >/var/lib/epm-bootstrap/os-ready
