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
  t3mp3st/         # War Room offensive-security (Node.js)  — web :3333
  mercury-agent/   # agent 24/7 (TS, web UI + SQLite)       — web :6174
  hermes-agent/    # self-improving agent (Python, serve)   — web :9119
```

Tous les harnesses routent le LLM via OpenRouter → `deepseek/deepseek-v4-pro`.

## Secrets (hors Git — ce repo est public)

Les clés API ne sont **jamais** commitées. Créées à la main :

```bash
# clé OpenRouter partagée par les harnesses (même clé pour les 3)
kubectl create secret generic t3mp3st-secrets -n t3mp3st --from-literal=OPENROUTER_API_KEY=sk-or-...
kubectl create secret generic mercury-secrets -n mercury --from-literal=OPENAI_COMPAT_API_KEY=sk-or-...
kubectl create secret generic hermes-secrets  -n hermes  --from-literal=OPENROUTER_API_KEY=sk-or-...
```

## Accès aux UIs

Via `kubectl port-forward` uniquement (NetworkPolicy ingress deny-all).
T3MP3ST bind `0.0.0.0` (→ `svc`) ; mercury et hermes bindent `127.0.0.1` (→ `deploy`) :

```bash
kubectl -n t3mp3st port-forward svc/t3mp3st    3333:3333   # http://127.0.0.1:3333/ui/
kubectl -n mercury port-forward deploy/mercury 6174:6174   # http://127.0.0.1:6174
kubectl -n hermes  port-forward deploy/hermes  9119:9119   # http://127.0.0.1:9119
```

## Setup config-once (déjà fait)

- **mercury** : `kubectl -n mercury exec -it deploy/mercury -- mercury setup` (provider *OpenAI Compilations* → OpenRouter), puis `rollout restart`.
- **hermes** : config non-interactive — clé lue de l'env, `hermes config set model.default deepseek/deepseek-v4-pro`. Config persistée sur PVC `/opt/data`.

## Opérations Flux

```bash
flux get kustomizations          # état de la synchro
flux reconcile kustomization apps --with-source   # forcer une synchro
```
