#!/usr/bin/env python3
"""Schémas d'architecture du k3s-lab, générés depuis l'état réel du cluster.
Règle : nœuds = nom de l'outil seul ; flèches = verbe court (1-3 mots).
Usage : python lab_diagram.py [--context k3s-lab] [--out DIR]
"""
import argparse, json, os, subprocess

from diagrams import Cluster, Diagram, Edge
from diagrams.custom import Custom
from diagrams.onprem.certificates import CertManager
from diagrams.onprem.client import User
from diagrams.onprem.database import Postgresql
from diagrams.onprem.gitops import Flux
from diagrams.onprem.monitoring import Grafana, Prometheus
from diagrams.onprem.network import Traefik
from diagrams.onprem.security import Vault
from diagrams.onprem.vcs import Gitea, Github
from diagrams.programming.language import Python

HERE = os.path.dirname(os.path.abspath(__file__))
ICON = lambda n: os.path.join(HERE, "icons", f"{n}.png")

# clé -> (namespace, préfixe pod, titre, icône)
APPS = {
    "authentik": ("authentik", "authentik-server", "Authentik", lambda t: Custom(t, ICON("authentik"))),
    "postgres": ("authentik", "authentik-postgresql", "Postgres", Postgresql),
    "hermes": ("hermes", "hermes-", "Hermes", Python),
    "grafana": ("monitoring", "grafana", "Grafana", Grafana),
    "prometheus": ("monitoring", "prometheus-server", "Prometheus", Prometheus),
    "alertmanager": ("monitoring", "prometheus-alertmanager", "Alertmanager", lambda t: Custom(t, ICON("alertmanager"))),
    "gitea": ("gitea", "gitea", "Gitea", Gitea),
    "flux": ("flux-system", "source-controller", "Flux", Flux),
    "kyverno": ("kyverno", "kyverno-admission", "Kyverno", lambda t: Custom(t, ICON("kyverno"))),
    "certmanager": ("cert-manager", "cert-manager-", "cert-manager", CertManager),
}

GRAPH = {"fontsize": "20", "fontname": "Helvetica", "bgcolor": "white", "pad": "0.5",
         "nodesep": "0.8", "ranksep": "1.2", "splines": "spline"}
NODE = {"fontname": "Helvetica", "fontsize": "13"}
EDGE = {"fontname": "Helvetica", "fontsize": "11", "fontcolor": "#555555"}
CLUSTER = lambda c: {"bgcolor": c, "fontname": "Helvetica-Bold", "fontsize": "14",
                     "style": "rounded", "pencolor": "#BBBBBB", "margin": "20"}

HTTP = dict(color="#2E7D32")
AUTH = dict(color="#C62828")
DATA = dict(color="#757575", style="dashed")


def legend():
    """Légende compacte (table HTML Graphviz) : 3 traits, 1 mot chacun."""
    from diagrams import getdiagram
    row = lambda c, st, t: (f'<tr><td><font color="{c}" point-size="16">{st}</font></td>'
                            f'<td align="left"><font point-size="11" color="#555555">{t}</font></td></tr>')
    html = ('<<table border="1" color="#CCCCCC" cellborder="0" cellspacing="2" cellpadding="3" style="rounded">'
            + row("#2E7D32", "━━━", "trafic") + row("#C62828", "━━━", "authentification")
            + row("#757575", "╍╍╍", "données") + '</table>>')
    getdiagram().dot.node("legend", label=html, shape="plaintext")


def kubectl(ctx, *args):
    return json.loads(subprocess.run(["kubectl", "--context", ctx, *args, "-o", "json"],
                                     check=True, capture_output=True, text=True).stdout)["items"]


def placement(ctx):
    nodes = {n["metadata"]["name"]: "node-role.kubernetes.io/control-plane" in n["metadata"]["labels"]
             for n in kubectl(ctx, "get", "nodes")}
    where = {}
    for p in kubectl(ctx, "get", "pods", "-A", "--field-selector=status.phase=Running"):
        ns, name = p["metadata"]["namespace"], p["metadata"]["name"]
        for k, (ans, pre, *_) in APPS.items():
            if ns == ans and name.startswith(pre):
                where.setdefault(k, p["spec"]["nodeName"])
    return nodes, where


def overview(nodes, where, out):
    """Vue par fonction (plus lisible que par nœud) ; le nœud est en sous-titre discret."""
    lab = lambda k: f"{APPS[k][2]}\n{where.get(k, '?')}"
    mk = lambda k: APPS[k][3](lab(k))
    with Diagram("k3s-lab", filename=os.path.join(out, "k3s-lab-overview"), show=False,
                 direction="LR", graph_attr=GRAPH, node_attr=NODE, edge_attr=EDGE, outformat="png"):
        user = User("Admin")
        with Cluster("Accès", graph_attr=CLUSTER("#F3F3F3")):
            ts = Custom("Tailscale", ICON("tailscale"))
            tr = Traefik("Traefik")
        with Cluster("Identité", graph_attr=CLUSTER("#FDECEA")):
            ak, pg = mk("authentik"), mk("postgres")
        with Cluster("Applications", graph_attr=CLUSTER("#EAF2FB")):
            he, gf, gt = mk("hermes"), mk("grafana"), mk("gitea")
        with Cluster("Observabilité", graph_attr=CLUSTER("#EEF7EE")):
            pr, am = mk("prometheus"), mk("alertmanager")
        legend()

        user >> Edge(label="HTTPS", **HTTP) >> ts >> Edge(label="WireGuard", **HTTP) >> tr
        tr >> Edge(label="forward-auth", constraint="false", **AUTH) >> ak
        ak >> Edge(**DATA) >> pg
        tr >> Edge(**HTTP) >> [he, gf, gt]
        [gf, gt] >> Edge(label="OIDC", **AUTH) >> ak
        gf >> Edge(label="query", **DATA) >> pr
        pr >> Edge(label="alerts", **DATA) >> am


def gitops(out):
    with Diagram("GitOps", filename=os.path.join(out, "k3s-lab-gitops"), show=False,
                 direction="LR", graph_attr=GRAPH, node_attr=NODE, edge_attr=EDGE, outformat="png"):
        dev = User("Admin")
        vault = Vault("Vault")
        gh = Github("GitHub")
        with Cluster("k3s-lab", graph_attr=CLUSTER("#EAF2FB")):
            fx = Flux("Flux")
            ky = Custom("Kyverno", ICON("kyverno"))
            ak = Custom("Authentik", ICON("authentik"))
            apps = Traefik("Apps")
        legend()
        dev >> Edge(label="git push", **HTTP) >> gh
        vault >> Edge(label="SOPS encrypt", **AUTH) >> gh
        gh >> Edge(label="pull", **HTTP) >> fx
        fx >> Edge(label="decrypt + apply", **HTTP) >> apps
        fx >> Edge(label="blueprints", **AUTH) >> ak
        ky >> Edge(label="audit", **DATA) >> apps


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--context", default="k3s-lab")
    ap.add_argument("--out", default=HERE)
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    nodes, where = placement(a.context)
    overview(nodes, where, a.out)
    gitops(a.out)
    print(json.dumps(where))
