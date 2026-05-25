# pk-copilot CLI entry point
#
# REGULATORY BOUNDARY (v1.x):
# This tool is intended for exploratory analysis, data preprocessing, and
# report drafting. It is NOT a 21 CFR Part 11 compliant system. Part 11
# technical controls (audit trail, e-signature, RBAC, WORM retention) are
# planned for v2.0. See docs/10-21cfr-part11.md for the full disclaimer.
"""
pk-copilot command-line interface.

Exposes the same computational kernel as the MCP server via a standard CLI.
Each subcommand delegates to the corresponding ``impl_*`` function from
:mod:`pkplugin.mcp_server`.  Results are printed as JSON to stdout.
Exit code 0 on success, 1 on error.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any


def _print_result(result: Any) -> int:
    """Print *result* as JSON and return the appropriate exit code."""
    if isinstance(result, dict) and result.get("status") == "error":
        print(json.dumps(result), file=sys.stderr)
        return 1
    print(json.dumps(result))
    return 0


def _parse_init_params(raw: str) -> dict[str, float]:
    """Parse 'K=1.0,V=10' style string into a dict[str, float]."""
    params: dict[str, float] = {}
    for token in raw.split(","):
        token = token.strip()
        if not token:
            continue
        if "=" not in token:
            raise argparse.ArgumentTypeError(
                f"Invalid parameter token {token!r}. Expected NAME=VALUE."
            )
        name, _, value = token.partition("=")
        try:
            params[name.strip()] = float(value.strip())
        except ValueError as exc:
            raise argparse.ArgumentTypeError(
                f"Cannot parse value for {name!r}: {value!r}"
            ) from exc
    return params


# ---------------------------------------------------------------------------
# Sub-command handlers
# ---------------------------------------------------------------------------


def _cmd_nca(args: argparse.Namespace) -> int:
    from pkplugin.mcp_server import impl_run_nca

    config: dict[str, Any] = {}
    if args.config:
        import importlib.util
        import pathlib

        cfg_path = pathlib.Path(args.config)
        if not cfg_path.is_file():
            print(json.dumps({"status": "error", "error": f"Config file not found: {cfg_path}"}), file=sys.stderr)
            return 1
        # Support simple YAML-ish or JSON config files.
        try:
            with open(cfg_path) as fh:
                raw = fh.read().strip()
            # Try JSON first, then minimal key:value parsing.
            try:
                config = json.loads(raw)
            except json.JSONDecodeError:
                # Very basic "key: value" YAML subset (no dependencies).
                for line in raw.splitlines():
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    if ":" in line:
                        k, _, v = line.partition(":")
                        config[k.strip()] = v.strip()
        except OSError as exc:
            print(json.dumps({"status": "error", "error": str(exc)}), file=sys.stderr)
            return 1

    result = impl_run_nca(
        dataset_path=args.dataset,
        config=config or None,
        audit_dir=args.out,
    )
    return _print_result(result)


def _cmd_be(args: argparse.Namespace) -> int:
    from pkplugin.mcp_server import impl_run_be

    result = impl_run_be(
        parameter_dataset_path=args.parameters,
        endpoint=args.endpoint,
        design=args.design,
    )
    return _print_result(result)


def _cmd_fit(args: argparse.Namespace) -> int:
    from pkplugin.mcp_server import impl_fit_pk_model

    try:
        init_params = _parse_init_params(args.init)
    except argparse.ArgumentTypeError as exc:
        print(json.dumps({"status": "error", "error": str(exc)}), file=sys.stderr)
        return 1

    result = impl_fit_pk_model(
        dataset_path=args.dataset,
        model_name=args.model,
        initial_params=init_params,
        dose=args.dose,
    )
    return _print_result(result)


def _cmd_pd_fit(args: argparse.Namespace) -> int:
    from pkplugin.mcp_server import impl_fit_pd_model

    try:
        init_params = _parse_init_params(args.init)
    except argparse.ArgumentTypeError as exc:
        print(json.dumps({"status": "error", "error": str(exc)}), file=sys.stderr)
        return 1

    result = impl_fit_pd_model(
        pd_dataset_path=args.pd_dataset,
        model_name=args.model,
        initial_params=init_params,
    )
    return _print_result(result)


def _cmd_report(args: argparse.Namespace) -> int:
    from pkplugin.mcp_server import impl_generate_report

    result = impl_generate_report(
        run_id=args.run_id,
        format=args.format,
    )
    return _print_result(result)


def _cmd_compare(args: argparse.Namespace) -> int:
    from pkplugin.mcp_server import impl_compare_against_reference

    result = impl_compare_against_reference(
        run_id=args.run_id,
        reference_backend=args.backend,
    )
    return _print_result(result)


def _cmd_doctor(args: argparse.Namespace) -> int:  # noqa: ARG001
    from pkplugin.mcp_server import impl_r_backend_status
    from pkplugin import __version__

    import importlib.metadata

    dep_versions: dict[str, str] = {}
    for dep in ("numpy", "scipy", "pandas", "lmfit", "statsmodels", "pydantic"):
        try:
            dep_versions[dep] = importlib.metadata.version(dep)
        except importlib.metadata.PackageNotFoundError:
            dep_versions[dep] = "not installed"

    r_status = impl_r_backend_status()

    report = {
        "pkplugin_version": __version__,
        "python_version": sys.version,
        "dependencies": dep_versions,
        "r_backend": r_status,
    }
    print(json.dumps(report, indent=2))
    return 0


def _cmd_sbom(args: argparse.Namespace) -> int:
    from pkplugin.sbom import generate_sbom

    output = generate_sbom(format=args.format)
    print(output)
    return 0


# ---------------------------------------------------------------------------
# Parser construction
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pkplugin",
        description="pk-copilot CLI — WinNonlin-compatible PK/PD analysis.",
    )
    from pkplugin import __version__

    parser.add_argument(
        "--version",
        action="version",
        version=__version__,
    )

    sub = parser.add_subparsers(dest="command", metavar="COMMAND")

    # nca
    p_nca = sub.add_parser("nca", help="Run Non-Compartmental Analysis.")
    p_nca.add_argument("dataset", metavar="dataset.csv", help="Concentration dataset CSV.")
    p_nca.add_argument("--config", metavar="nca_config.yaml", default=None, help="Optional NCA config file (JSON or key: value).")
    p_nca.add_argument("--out", metavar="runs/", default=None, help="Audit output directory.")

    # be
    p_be = sub.add_parser("be", help="Run Bioequivalence analysis.")
    p_be.add_argument("parameters", metavar="parameters.csv", help="Subject-level parameter CSV.")
    p_be.add_argument("--endpoint", default="AUC0_t", help="PK endpoint (default: AUC0_t).")
    p_be.add_argument("--design", default="crossover_2x2", help="BE design (default: crossover_2x2).")

    # fit
    p_fit = sub.add_parser("fit", help="Fit a PK compartmental model.")
    p_fit.add_argument("dataset", metavar="dataset.csv", help="Concentration dataset CSV.")
    p_fit.add_argument("--model", required=True, help="Model name (e.g. cmt1_iv_bolus).")
    p_fit.add_argument("--dose", type=float, default=None, help="Dose amount.")
    p_fit.add_argument("--init", required=True, metavar="V=10,k=0.1", help="Initial parameter values.")

    # pd-fit
    p_pdfit = sub.add_parser("pd-fit", help="Fit a PD model.")
    p_pdfit.add_argument("pd_dataset", metavar="pd_dataset.csv", help="PD dataset CSV (time, concentration, effect).")
    p_pdfit.add_argument("--model", required=True, help="PD model name (e.g. emax).")
    p_pdfit.add_argument("--init", required=True, metavar="E0=0,Emax=100,EC50=10", help="Initial parameter values.")

    # report
    p_report = sub.add_parser("report", help="Generate a report for a previous run.")
    p_report.add_argument("run_id", help="Run ID from a previous nca or be run.")
    p_report.add_argument("--format", choices=["html", "pdf"], default="html", help="Report format (default: html).")

    # compare
    p_compare = sub.add_parser("compare", help="Compare a run against R reference backend.")
    p_compare.add_argument("run_id", help="Run ID to compare.")
    p_compare.add_argument("--backend", choices=["pknca", "noncompart"], default="pknca", help="Reference backend (default: pknca).")

    # doctor
    sub.add_parser("doctor", help="Print version + dependency info + R backend status.")

    # sbom
    p_sbom = sub.add_parser("sbom", help="Generate Software Bill of Materials.")
    p_sbom.add_argument(
        "--format",
        choices=["cyclonedx-json", "cyclonedx-xml"],
        default="cyclonedx-json",
        help="SBOM format (default: cyclonedx-json).",
    )

    return parser


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

_COMMAND_MAP = {
    "nca": _cmd_nca,
    "be": _cmd_be,
    "fit": _cmd_fit,
    "pd-fit": _cmd_pd_fit,
    "report": _cmd_report,
    "compare": _cmd_compare,
    "doctor": _cmd_doctor,
    "sbom": _cmd_sbom,
}


def main(argv: list[str] | None = None) -> int:
    """Entry point for the ``pkplugin`` console command."""
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help()
        return 0

    handler = _COMMAND_MAP.get(args.command)
    if handler is None:
        parser.print_help()
        return 1

    try:
        return handler(args)
    except Exception as exc:  # pragma: no cover
        print(json.dumps({"status": "error", "error": str(exc)}), file=sys.stderr)
        return 1
