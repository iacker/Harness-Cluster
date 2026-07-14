<p align="center">
  <img src="docs/logo.png" alt="Harness-Cluster" width="220">
</p>

<h1 align="center">Harness-Cluster</h1>

<p align="center">
  Un petit lab qui fait tourner des harnesses d'agents IA en continu, sur du vieux hardware recyclé, géré en GitOps avec Flux CD.
</p>

## L'idée

Plutôt que de lancer mes agents à la main, je les fais vivre 24/7 sur un cluster k3s de 2 mini-PC, et tout est décrit dans ce repo. Flux se charge de synchroniser le cluster avec le Git. Je pousse, ça se déploie.

## Le cluster

- **node1**, k3s server / control-plane (Tailscale `100.x.y.1`)
- **node2**, k3s agent (Tailscale `100.x.y.2`)
- 2 mini-PC Celeron G3900T, 2 vCPU et 4 Go chacun. Réseau cluster sur Tailscale.

## Ce qui tourne dessus

```
clusters/k3s-lab/
  flux-system/     composants Flux (générés par flux bootstrap)
  apps.yaml        Flux Kustomization vers ./apps
  kepler.yaml      Flux Kustomization vers ./apps/kepler
  monitoring.yaml  Flux Kustomization vers ./apps/monitoring
apps/
  kustomization.yaml
  t3mp3st/         war room offensive-security (Node.js), web sur 3333
  hermes-agent/    agent self-improving généraliste (Python), web sur 9119
  kepler/          mesure de conso énergie par pod
  monitoring/      Grafana et Prometheus
```

Les harnesses routent le LLM via OpenRouter vers `deepseek/deepseek-v4-pro`.

## Les secrets restent hors du Git

Ce repo est public, donc aucune clé API n'est commitée. On les crée à la main.

```bash
kubectl create secret generic t3mp3st-secrets -n t3mp3st \
  --from-literal=OPENROUTER_API_KEY=sk-or-...
kubectl create secret generic hermes-secrets  -n hermes  \
  --from-literal=OPENROUTER_API_KEY=sk-or-...
```

## Accéder aux interfaces

Tout passe par `kubectl port-forward`, l'ingress est en deny-all via NetworkPolicy.

```bash
kubectl -n t3mp3st port-forward svc/t3mp3st    3333:3333   # http://127.0.0.1:3333/ui/
kubectl -n hermes  port-forward deploy/hermes  9119:9119   # http://127.0.0.1:9119
```

## Mettre en route depuis zéro

Il faut déjà un cluster k3s et le CLI Flux.

```bash
flux bootstrap github \
  --owner=iacker --repository=Harness-Cluster \
  --branch=main --path=clusters/k3s-lab
```

Ensuite on crée les secrets ci-dessus, et Flux déploie le reste tout seul.

## Opérations Flux au quotidien

```bash
flux get kustomizations                            # état de la synchro
flux reconcile kustomization apps --with-source    # forcer une synchro
```
