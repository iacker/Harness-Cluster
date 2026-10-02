#!/usr/bin/env python3
"""Génère les schémas d'architecture du k3s-lab à partir de l'état RÉEL du cluster.

Usage : python lab_diagram.py [--context k3s-lab] [--out DIR] [--public]
  --public : masque les IP (pour README / LinkedIn).
Dépendances : graphviz (dot), pip install diagrams.
Sorties : k3s-lab-overview.png, k3s-lab-gitops.png
"""
import argparse, json, os, subprocess
from collections import defaultdict

from diagrams import Cluster, Diagram, Edge
from diagrams.custom import Custom
from diagrams.k8s.compute import Pod
from diagrams.programming.language import Python
from diagrams.onprem.certificates import CertManager
from diagrams.onprem.client import Users
from diagrams.onprem.database import Postgresql
from diagrams.onprem.gitops import Flux
from diagrams.onprem.logging import Loki
from diagrams.onprem.monitoring import Grafana, Prometheus
from diagrams.onprem.network import Traefik
from diagrams.onprem.security import Vault
from diagrams.onprem.vcs import Gitea, Github

HERE = os.path.dirname(os.path.abspath(__file__))
ICON = lambda n: os.path.join(HERE, "icons", f"{n}.png")

# Composants affichés : (namespace, préfixe pod) -> (label, fabrique d'icône)
APPS = [
    ("authentik", "authentik-server", "Authentik\nSSO / OIDC / MFA", lambda l: Custom(l, ICON("authentik"))),
    ("authentik", "authentik-postgresql", "Postgres 17\n(authentik)", Postgresql),
    ("hermes", "hermes-", "Hermes agent\n(Ényo, A2A)", Python),
    ("monitoring", "grafana", "Grafana", Grafana),
    ("monitoring", "prometheus-server", "Prometheus", Prometheus),
    ("monitoring", "prometheus-alertmanager", "Alertmanager", lambda l: Custom(l, ICON("alertmanager"))),
    ("logging", "loki", "Loki", Loki),
    ("gitea", "gitea", "Gitea", Gitea),
    ("flux-system", "source-controller", "Flux", Flux),
    ("kyverno", "kyverno-admission", "Kyverno\n(policy audit)", lambda l: Custom(l, ICON("kyverno"))),
    ("cert-manager", "cert-manager-", "cert-manager\nCA interne", CertManager),
]
SSO = {"grafana.": "OIDC", "gitea.": "OIDC", "hermes.": "forward-auth",
       "prometheus.": "forward-auth", "alertmanager.": "forward-auth", "auth.": "IdP"}


def kubectl(ctx, *args):
    out = subprocess.run(["kubectl", "--context", ctx, *args, "-o", "json"],
                         check=True, capture_output=True, text=True).stdout
    return json.loads(out)["items"]


def collect(ctx):
    nodes = []
    for n in kubectl(ctx, "get", "nodes"):
        labels = n["metadata"]["labels"]
        ip = next((a["address"] for a in n["status"]["addresses"] if a["type"] == "InternalIP"), "?")
        mem = int(n["status"]["capacity"]["memory"].rstrip("Ki")) / 1024 / 1024
        cpu = n["status"]["capacity"]["cpu"]
        role = "control-plane" if "node-role.kubernetes.io/control-plane" in labels else "worker"
        nodes.append(dict(name=n["metadata"]["name"], ip=ip, role=role, mem=round(mem, 1), cpu=cpu))
    placement = defaultdict(list)  # node -> [app index]
    for p in kubectl(ctx, "get", "pods", "-A", "--field-selector=status.phase=Running"):
        ns, name, node = p["metadata"]["namespace"], p["metadata"]["name"], p["spec"].get("nodeName")
        for i, (ans, pre, *_ ) in enumerate(APPS):
            if ns == ans and name.startswith(pre) and not any(i in v for v in placement.values()):
                placement[node].append(i)
    ingresses = []
    for i in kubectl(ctx, "get", "ingress", "-A"):
        for r in i["spec"].get("rules", []):
            h = r["host"]
            ingresses.append((h, next((v for k, v in SSO.items() if h.startswith(k)), "local login")))
    return nodes, placement, sorted(ingresses)


def overview(nodes, placement, ingresses, out, public):
    attr = {"fontsize": "22", "bgcolor": "white", "pad": "0.4", "nodesep": "0.5", "ranksep": "1.0"}
    with Diagram("k3s-lab : architecture", filename=os.path.join(out, "k3s-lab-overview"),
                 show=False, direction="LR", graph_attr=attr, outformat="png"):
        user = Users("Erwan\n(navigateur)")
        ts = Custom("Tailscale\n(tailnet WireGuard)", ICON("tailscale"))
        with Cluster("Ingress (Traefik + TLS CA lab)"):
            tr = Traefik("Traefik\n" + "\n".join(f"{h.split('.')[0]} [{m}]" for h, m in ingresses))
        user >> Edge(xlabel="HTTPS") >> ts >> tr
        objs = {}
        for n in sorted(nodes, key=lambda x: (x["role"] != "control-plane", x["name"])):
            ip = "" if public else f"\n{n['ip']}"
            title = f"{n['name']} ({n['role']}) · {n['cpu']} vCPU · {n['mem']} Gi{ip}"
            with Cluster(title, graph_attr={"bgcolor": "#EEF4FB" if n["role"] == "worker" else "#FDF2E9"}):
                ids = placement.get(n["name"], [])
                if not ids:
                    objs[n["name"]] = [Pod("system pods")]
                for i in ids:
                    _, _, label, mk = APPS[i]
                    objs[i] = mk(label)
        with Cluster("Légende", graph_attr={"bgcolor": "#FAFAFA", "fontsize": "12"}):
            Pod("vert : trafic HTTPS\nrouge plein : forward-auth\nrouge tirets : OIDC\npointillés : scrape/alertes")
        ak = objs.get(0)
        if ak:
            tr >> Edge(xlabel="auth", color="firebrick", style="bold") >> ak
            for i in (3, 7):  # OIDC
                if i in objs: objs[i] >> Edge(color="firebrick", style="dashed") >> ak
            if 1 in objs: ak >> objs[1]
        for i in (2, 3, 4, 5, 7):
            if i in objs: tr >> Edge(color="darkgreen") >> objs[i]
        if 4 in objs and 3 in objs: objs[3] >> Edge(style="dotted") >> objs[4]
        if 4 in objs and 5 in objs: objs[4] >> Edge(style="dotted") >> objs[5]


def gitops(out):
    attr = {"fontsize": "22", "bgcolor": "white", "pad": "0.4", "ranksep": "0.9"}
    with Diagram("k3s-lab : GitOps & secrets", filename=os.path.join(out, "k3s-lab-gitops"),
                 show=False, direction="LR", graph_attr=attr, outformat="png"):
        dev = Users("Erwan / Arès")
        gh = Github("GitHub\niacker/Harness-Cluster")
        with Cluster("Secrets"):
            vault = Vault("HashiCorp Vault\n(Mac, source de vérité)")
            age = Vault("SOPS + age\n(*.sops.yaml)")
        with Cluster("k3s-lab"):
            fx = Flux("Flux\nsource + kustomize + helm")
            with Cluster("Kustomizations isolées (wait:false)"):
                ks = [Pod(n) for n in ("apps (hermes)", "monitoring", "authentik", "gitea", "kyverno")]
            ak = Custom("Authentik blueprints\n(groupes, providers, MFA)", ICON("authentik"))
            ky = Custom("Kyverno\naudit-first", ICON("kyverno"))
        dev >> Edge(label="git push") >> gh >> Edge(label="pull") >> fx
        vault >> Edge(label="valeurs") >> age >> Edge(label="chiffré dans Git") >> gh
        for j, k in enumerate(ks):
            fx >> Edge(xlabel="déchiffre SOPS (age)" if j == 2 else "") >> k
        ks[2] >> ak
        fx >> Edge(style="dotted") >> ky


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--context", default="k3s-lab")
    ap.add_argument("--out", default=HERE)
    ap.add_argument("--public", action="store_true")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    nodes, placement, ing = collect(a.context)
    overview(nodes, placement, ing, a.out, a.public)
    gitops(a.out)
    print(json.dumps({"nodes": [n["name"] for n in nodes],
                      "placement": {k: [APPS[i][2].split("\n")[0] for i in v] for k, v in placement.items()},
                      "ingresses": ing}, ensure_ascii=False))
