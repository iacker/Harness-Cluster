# Harness-Cluster

GitOps pour un lab k3s 2 nœuds (Tailscale), piloté par **Flux CD**. Héberge des
harnesses agentic / offensive-security.

## Cluster

- **node1** — k3s server / control-plane (Tailscale `100.122.146.39`)
- **node2** — k3s agent (Tailscale `100.83.189.79`)
- 2× mini-PC Celeron G3900T, 2 vCPU / 4 Go chacun. Réseau cluster sur Tailscale.

## Structure

```
clusters/k3s-lab/
  flux-system/     # composants Flux (généré par `flux bootstrap`)
  apps.yaml        # Flux Kustomization -> ./apps
apps/
  kustomization.yaml
  t3mp3st/         # War Room offensive-security (Node.js)
  mercury-agent/   # agent 24/7 (TS, web UI + SQLite)   [en cours]
  hermes-agent/    # self-improving agent (Python)       [en cours]
```

## Secrets (hors Git — ce repo est public)

Les clés API ne sont **jamais** commitées. Créées à la main :

```bash
# clé OpenRouter partagée par les harnesses
kubectl create secret generic t3mp3st-secrets -n t3mp3st \
  --from-literal=OPENROUTER_API_KEY=sk-or-...
```

## Accès aux UIs

Via `kubectl port-forward` uniquement (NetworkPolicy ingress deny-all) :

```bash
kubectl -n t3mp3st port-forward svc/t3mp3st 3333:3333   # http://127.0.0.1:3333/ui/
```

## Opérations Flux

```bash
flux get kustomizations          # état de la synchro
flux reconcile kustomization apps --with-source   # forcer une synchro
```
