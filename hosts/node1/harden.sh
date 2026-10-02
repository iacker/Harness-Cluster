#!/bin/bash
# Usage : sudo bash /tmp/k3s-hardening/harden.sh
set -euo pipefail
[ "$(id -u)" = 0 ] || { echo "Lancer avec sudo"; exit 1; }
cd "$(dirname "$0")"; D=/etc/rancher/k3s
BK=/root/k3s-hardening-backup-$(date +%Y%m%d-%H%M); mkdir -p "$BK"; cp -a $D "$BK/"; cp /etc/hosts "$BK/"
echo "Sauvegarde : $BK"
grep -q 'auth.k3s-lab.local' /etc/hosts || echo '100.65.116.45 auth.k3s-lab.local' >> /etc/hosts
install -m600 authn.yaml $D/authn.yaml; install -m600 audit.yaml $D/audit.yaml
mkdir -p $D/config.yaml.d /var/lib/rancher/k3s/server/logs; install -m600 50-hardening.yaml $D/config.yaml.d/50-hardening.yaml
echo "Redémarrage k3s (les pods continuent de tourner)..."; systemctl restart k3s
for i in $(seq 1 60); do k3s kubectl get --raw /readyz >/dev/null 2>&1 && break; sleep 3; done
k3s kubectl get --raw /readyz && echo " API OK"
echo "Réécriture des Secrets pour les chiffrer au repos..."
k3s kubectl get secrets -A -o json | k3s kubectl replace -f - >/dev/null && echo "Secrets réécrits"
k3s secrets-encrypt status | head -3
ls -la /var/lib/rancher/k3s/server/logs/audit.log
echo; echo "Rollback : rm $D/config.yaml.d/50-hardening.yaml && systemctl restart k3s (restaurer depuis $BK si besoin)"
