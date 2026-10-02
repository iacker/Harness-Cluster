# node1 (control-plane) : durcissement apiserver

Pas géré par Flux (config hôte). Appliquer avec :

```bash
scp hosts/node1/* node1:/tmp/k3s-hardening/ && ssh -t node1 sudo bash /tmp/k3s-hardening/harden.sh
```

Active : auth OIDC Authentik pour kubectl (groupes `oidc:lab-*`), audit log, chiffrement des Secrets au repos.
