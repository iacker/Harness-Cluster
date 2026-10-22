# node1 (control-plane) : durcissement apiserver

Pas géré par Flux (config hôte). Appliquer avec :

```bash
scp hosts/node1/* node1:/tmp/k3s-hardening/ && ssh -t node1 sudo bash /tmp/k3s-hardening/harden.sh
```

Active : auth OIDC Authentik pour kubectl (groupes `oidc:lab-*`), audit log, chiffrement des Secrets au repos.

## Tailscale serve (dashboard Hermes sur le tailnet)

Config hôte, hors Flux. `https://node1.<tailnet>.ts.net` termine le TLS et renvoie vers Traefik sur l'IP LAN de node1, qui route vers `hermes` (Ingress `hermes-tailnet`) :

```bash
sudo tailscale serve --bg --https=443 http://<IP-LAN-node1>:80
```

Ne pas viser directement le ClusterIP du Service : les paquets de tailscaled portent le fwmark `0x80000`, que flannel (VXLAN sur `tailscale0`) recopie sur le paquet encapsulé. Celui-ci est alors routé hors du tailnet et perdu dès que le pod tourne sur un autre nœud.
