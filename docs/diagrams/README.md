# Schémas d'architecture (générés)

`lab_diagram.py` lit l'état réel du cluster (`kubectl`) et produit :
- `k3s-lab-overview.png` : tailnet → Traefik → Authentik → applis, par nœud
- `k3s-lab-gitops.png` : Git → Flux → Kustomizations, secrets Vault → SOPS/age

```bash
brew install graphviz && pip install diagrams
python lab_diagram.py --public            # sans IP (README)
python lab_diagram.py --out <vault>/assets  # avec IP (doc interne)
```
